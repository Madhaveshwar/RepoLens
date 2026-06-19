from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.app.database.database import get_async_db
from backend.app.models.models import User
from backend.app.schemas.schemas import UserCreate, Token, UserOut
from backend.app.auth.security import get_password_hash, verify_password, create_access_token
from backend.app.utils.logger import get_logger

logger = get_logger("auth_router")

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(user_in: UserCreate, db: AsyncSession = Depends(get_async_db)):
    logger.info(f"Received registration request for email: {user_in.email}")
    try:
        result = await db.execute(select(User).where(User.email == user_in.email))
        existing_user = result.scalars().first()
        if existing_user:
            logger.warning(f"Registration failed: User with email {user_in.email} already exists.")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A user with this email already exists."
            )
        
        logger.info(f"Hashing password and creating new user for {user_in.email}")
        hashed_password = get_password_hash(user_in.password)
        new_user = User(
            email=user_in.email,
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
        result = await db.execute(select(User).where(User.email == form_data.username))
        user = result.scalars().first()
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
