import asyncio
import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from app.config import settings
from app.database.database import get_async_db
from app.models.models import User, PasswordResetToken
from app.schemas.schemas import (
    UserCreate,
    Token,
    UserOut,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
)
from app.auth.security import get_password_hash, verify_password, create_access_token
from app.services.email_service import is_email_configured, send_password_reset_email_sync
from app.utils.audit import log_audit_event
from app.utils.logger import get_logger

logger = get_logger("auth_router")

router = APIRouter(prefix="/auth", tags=["Authentication"])

# ── Email normalization ─────────────────────────────────────────────────────

def _normalize_email(email: str) -> str:
    """Normalize an email for storage and comparison.

    Registration stores emails fully lowercased; every lookup strips
    surrounding whitespace and compares case-insensitively so that users who
    typed mixed-case addresses (e.g. mobile autocapitalize) can still sign in
    with the same address.
    """
    return (email or "").strip().lower()


async def _find_user_by_email(db: AsyncSession, email: str) -> User | None:
    """Look up a user by email, ignoring case and surrounding whitespace."""
    normalized = _normalize_email(email)
    if not normalized:
        return None
    # Fast path: exact match (hits the unique index).
    result = await db.execute(select(User).where(User.email == normalized))
    user = result.scalars().first()
    if user is None:
        # Case-insensitive fallback for legacy rows stored with mixed case.
        result = await db.execute(
            select(User).where(func.lower(User.email) == normalized)
        )
        user = result.scalars().first()
    return user


# ── Password reset helpers ──────────────────────────────────────────────────

# Naive UTC timestamps, consistent with the existing models (datetime.utcnow).
def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash_token(raw_token: str) -> str:
    """Only the SHA-256 hash of the raw token is ever persisted."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _build_reset_url(raw_token: str) -> str:
    base = settings.FRONTEND_URL.rstrip("/")
    return f"{base}/#/reset-password?token={raw_token}"


# Simple in-memory throttle: max N reset requests per email per window.
_RESET_REQUEST_LIMIT = 3
_RESET_REQUEST_WINDOW_SECONDS = 15 * 60
_reset_request_times: dict[str, list[float]] = {}


def _throttled(email_key: str) -> bool:
    now = time.monotonic()
    timestamps = [t for t in _reset_request_times.get(email_key, []) if now - t < _RESET_REQUEST_WINDOW_SECONDS]
    if len(timestamps) >= _RESET_REQUEST_LIMIT:
        _reset_request_times[email_key] = timestamps
        return True
    timestamps.append(now)
    _reset_request_times[email_key] = timestamps
    return False


# Shared registration/reset password policy: 8+ chars with at least one
# letter and one digit. Used by both register and reset-password so the two
# flows cannot disagree about what counts as a valid password.
def _validate_password(password: str) -> None:
    if len(password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long."
        )
    if not any(c.isalpha() for c in password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must contain at least one letter."
        )
    if not any(c.isdigit() for c in password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must contain at least one number."
        )


# ── Existing endpoints ──────────────────────────────────────────────────────

@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(user_in: UserCreate, db: AsyncSession = Depends(get_async_db)):
    logger.info(f"Received registration request for email: {user_in.email}")
    try:
        normalized_email = _normalize_email(user_in.email)
        result = await db.execute(select(User).where(User.email == normalized_email))
        existing_user = result.scalars().first()
        if existing_user is None:
            # Case-insensitive duplicate check so "John@X.com" cannot create a
            # second account when "john@x.com" already exists.
            result = await db.execute(
                select(User).where(func.lower(User.email) == normalized_email)
            )
            existing_user = result.scalars().first()
        if existing_user:
            logger.warning(f"Registration failed: User with email {normalized_email} already exists.")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A user with this email already exists."
            )
        
        logger.info(f"Hashing password and creating new user for {normalized_email}")
        _validate_password(user_in.password)
        hashed_password = get_password_hash(user_in.password)
        new_user = User(
            email=normalized_email,
            hashed_password=hashed_password
        )
        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
        
        logger.info(f"Successfully registered user with id: {new_user.id}")
        return UserOut(
            id=new_user.id,
            email=new_user.email,
            created_at=new_user.created_at,
            has_github_pat=False,
            has_groq_api_key=False
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during registration of {user_in.email}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during registration."
        )

@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_async_db)
):
    logger.info(f"Login attempt received for email: {form_data.username}")
    try:
        user = await _find_user_by_email(db, form_data.username)
        if not user or not verify_password(form_data.password, user.hashed_password):
            logger.warning(f"Failed login attempt for email: {form_data.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        logger.info(f"Successful login for user_id: {user.id}")
        access_token = create_access_token(subject=user.id)
        return Token(access_token=access_token, token_type="bearer")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during login of {form_data.username}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during login."
        )


# ── Password reset endpoints ────────────────────────────────────────────────

@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_db)
):
    """Request a password-reset link.

    Always responds 200 with a generic message so the endpoint cannot be used
    to discover which emails are registered. When email sending is configured,
    the reset link is emailed to the user. When it is NOT configured (local
    development) and the app is not running in production, the reset link is
    returned in the response so development can continue without SMTP.
    """
    try:
        email = _normalize_email(payload.email)
        email_key = email

        if _throttled(email_key):
            logger.warning(f"Password-reset request throttled for {email_key}")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many reset requests. Please try again later."
            )

        generic_message = (
            "If an account exists for that email, a password reset link has been sent. "
            "Please check your inbox."
        )

        user = await _find_user_by_email(db, email)

        if user is None:
            logger.info(f"Password reset requested for unknown email: {email_key}")
            return ForgotPasswordResponse(message=generic_message)

        if _throttled(str(user.id)):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many reset requests. Please try again later."
            )

        # Invalidate any previous unused tokens for this user.
        result = await db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
        )
        for stale in result.scalars().all():
            stale.used_at = _utcnow()

        raw_token = secrets.token_urlsafe(32)
        record = PasswordResetToken(
            user_id=user.id,
            token_hash=_hash_token(raw_token),
            expires_at=_utcnow() + timedelta(minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES),
        )
        db.add(record)
        audit = await log_audit_event(
            db,
            action="PASSWORD_RESET_REQUESTED",
            user_id=user.id,
            details={"email": user.email},
            ip_address=request.client.host if request.client else None,
        )
        if audit is not None:
            db.add(audit)
        await db.commit()

        reset_url = _build_reset_url(raw_token)

        email_sent = False
        if is_email_configured():
            email_sent = await asyncio.to_thread(send_password_reset_email_sync, user.email, reset_url)
            if not email_sent:
                logger.error(f"Password-reset email could not be sent to {user.email}.")

        response = ForgotPasswordResponse(message=generic_message)
        # Development-only fallback: expose the reset link ONLY when email is
        # not configured AND we are not in production.
        if not email_sent and not settings.IS_PRODUCTION:
            response.dev_reset_url = reset_url
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during forgot-password for {payload.email}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while processing the password reset request."
        )


@router.post("/reset-password", response_model=ResetPasswordResponse)
async def reset_password(
    payload: ResetPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_db)
):
    """Complete a password reset using a valid, unexpired, unused token."""
    try:
        if payload.new_password != payload.confirm_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Passwords do not match."
            )
        _validate_password(payload.new_password)

        result = await db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == _hash_token(payload.token)
            )
        )
        record = result.scalars().first()

        invalid_detail = "Invalid or expired reset link. Please request a new one."
        if record is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=invalid_detail)
        if record.used_at is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This reset link has already been used. Please request a new one."
            )
        if record.expires_at < _utcnow():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This reset link has expired. Please request a new one."
            )

        result = await db.execute(select(User).where(User.id == record.user_id))
        user = result.scalars().first()
        if user is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=invalid_detail)

        # Reuse the application's existing password hashing (argon2 via passlib).
        user.hashed_password = get_password_hash(payload.new_password)

        # Consume this token and invalidate any other outstanding tokens.
        now = _utcnow()
        record.used_at = now
        result = await db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
        )
        for other in result.scalars().all():
            other.used_at = now

        audit = await log_audit_event(
            db,
            action="PASSWORD_RESET_COMPLETED",
            user_id=user.id,
            details={"email": user.email},
            ip_address=request.client.host if request.client else None,
        )
        if audit is not None:
            db.add(audit)
        await db.commit()

        logger.info(f"Password successfully reset for user_id: {user.id}")
        return ResetPasswordResponse(
            message="Your password has been reset successfully. You can now sign in with your new password."
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during reset-password: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while resetting the password."
        )
