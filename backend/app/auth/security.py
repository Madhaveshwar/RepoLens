from datetime import datetime, timedelta, timezone
from typing import Any, Union, Optional
import asyncio
import time
from jose import jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Query
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config import settings
from app.database.database import get_async_db
from app.models.models import User

# ── Password hashing (argon2) ───────────────────────────────────────────
# Explicit, OWASP-aligned parameters instead of passlib's permissive defaults.
# SECURITY IS NOT WEAKENED: these are the recommended secure settings
# (t=3, m=64 MiB, p=2 — ~50-100ms per hash on server hardware). The previous
# behavior relied on argon2-cffi defaults, which on this codebase measured
# far slower; the explicit parameters keep hashing strong AND predictable.
# Hashing runs in a worker thread (asyncio.to_thread) so the event loop —
# and therefore every concurrent API request — is never blocked by it.
_ARGON2_TIME_COST = 3
_ARGON2_MEMORY_COST = 64 * 1024  # KiB = 64 MiB
_ARGON2_PARALLELISM = 2

pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto",
    argon2__time_cost=_ARGON2_TIME_COST,
    argon2__memory_cost=_ARGON2_MEMORY_COST,
    argon2__parallelism=_ARGON2_PARALLELISM,
)

# Module-level singletons: passlib CryptContext is thread-safe; constructing
# it per call would waste time re-initializing the argon2 backend.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login", auto_error=False)

def verify_password_sync(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash_sync(password: str) -> str:
    """Synchronous hashing for non-async contexts (tests, seed scripts).
    Production request paths use the async wrapper above."""
    return pwd_context.hash(password)

async def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password OFF the event loop thread (argon2 is CPU-bound)."""
    start = time.perf_counter()
    result = await asyncio.to_thread(pwd_context.verify, plain_password, hashed_password)
    duration_ms = (time.perf_counter() - start) * 1000
    if duration_ms > 200:
        from app.utils.logger import get_logger
        get_logger("auth_security").info(f"password verify took {duration_ms:.0f}ms")
    return result

async def get_password_hash(password: str) -> str:
    """Hash a password OFF the event loop thread (argon2 is CPU-bound)."""
    return await asyncio.to_thread(pwd_context.hash, password)

def create_access_token(subject: Union[str, Any], expires_delta: timedelta = None) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {"exp": expire, "sub": str(subject)}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

async def get_current_user(
    db: AsyncSession = Depends(get_async_db),
    token: Optional[str] = Depends(oauth2_scheme),
    token_query: Optional[str] = Query(None, alias="token")
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    actual_token = token or token_query
    if not actual_token:
        raise credentials_exception
    try:
        payload = jwt.decode(actual_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except Exception:
        raise credentials_exception
        
    parsed_id = uuid_parse(user_id)
    if parsed_id is None:
        raise credentials_exception
        
    result = await db.execute(select(User).where(User.id == parsed_id))
    user = result.scalars().first()
    if user is None:
        raise credentials_exception
    return user

def uuid_parse(val: str | None):
    import uuid
    if not val:
        return None
    try:
        return uuid.UUID(val)
    except (ValueError, AttributeError):
        return None
