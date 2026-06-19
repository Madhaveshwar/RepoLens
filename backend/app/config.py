import os
import sys
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

# Load env variables from root or backend directory if present
load_dotenv()

class Settings(BaseSettings):
    PROJECT_NAME: str = "AI Code Reviewer API"
    API_V1_STR: str = "/api/v1"
    
    # JWT Secrets
    SECRET_KEY: str = os.getenv("JWT_SECRET", "")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    
    # Database and Redis
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://reviewer_user:reviewer_password@postgres:5432/code_reviewer")
    SYNC_DATABASE_URL: str = os.getenv("SYNC_DATABASE_URL", "postgresql://reviewer_user:reviewer_password@postgres:5432/code_reviewer")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    BACKEND_CORS_ORIGINS: str = os.getenv("BACKEND_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000,http://localhost:8000")
    
    # Encryption key for all user API keys (AES-256, 32-byte URL-safe base64)
    ENCRYPTION_KEY: str = os.getenv("ENCRYPTION_KEY", "")
    
    # Global/fallback integration credentials (not used for SaaS - users provide their own)
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    
    # GitHub App Credentials
    GITHUB_APP_ID: str | None = os.getenv("GITHUB_APP_ID", None)
    GITHUB_APP_PRIVATE_KEY: str | None = os.getenv("GITHUB_APP_PRIVATE_KEY", None)
    GITHUB_WEBHOOK_SECRET: str | None = os.getenv("GITHUB_WEBHOOK_SECRET", None)
    
    # LangSmith Tracing (optional)
    LANGCHAIN_TRACING_V2: str = os.getenv("LANGCHAIN_TRACING_V2", "false")
    LANGCHAIN_API_KEY: str = os.getenv("LANGCHAIN_API_KEY", "")
    LANGCHAIN_PROJECT: str = os.getenv("LANGCHAIN_PROJECT", "Automated_Code_Reviewer")
    
    # Force LLM requests to bypass cache
    FORCE_GROQ_ANALYSIS: bool = os.getenv("FORCE_GROQ_ANALYSIS", "false").lower() == "true"
    
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

settings = Settings()

# ========== STARTUP VALIDATION ==========
# These validations run at module import time to fail fast.

REQUIRED_VARS = {
    "JWT_SECRET": "Used to sign and verify JWT authentication tokens. Generate with: python -c \"import secrets; print(secrets.token_urlsafe(32))\"",
    "ENCRYPTION_KEY": "Used to AES-256 encrypt user API keys at rest. Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"",
}

# Check if we're running tests (skip required validation for test suite)
IS_TESTING = os.getenv("TESTING", "").lower() in ("1", "true", "yes")

if not IS_TESTING:
    missing = []
    for var_name, description in REQUIRED_VARS.items():
        if not getattr(settings, var_name if var_name != "JWT_SECRET" else "SECRET_KEY", ""):
            # Map JWT_SECRET to the SECRET_KEY attr
            attr_name = "SECRET_KEY" if var_name == "JWT_SECRET" else var_name
            if not getattr(settings, attr_name, ""):
                missing.append(f"  - {var_name}: {description}")

    if missing:
        error_msg = (
            "\n" + "=" * 70 + "\n"
            "STARTUP FAILED: Missing required environment variables.\n"
            "The application cannot start without these values.\n"
            "Set them in your .env file or environment before starting.\n"
            + "=" * 70 + "\n\n"
            + "\n".join(missing) + "\n"
            + "=" * 70
        )
        print(error_msg, file=sys.stderr)
        sys.exit(1)

# ENCRYPTION_KEY format validation
if settings.ENCRYPTION_KEY:
    try:
        from cryptography.fernet import Fernet
        Fernet(settings.ENCRYPTION_KEY.encode())
    except Exception:
        print(
            "WARNING: ENCRYPTION_KEY is not a valid Fernet key. "
            "User API key encryption/decryption will fail. "
            "Generate a valid key with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"",
            file=sys.stderr
        )

# DATABASE_URL validation
if not settings.DATABASE_URL:
    print("WARNING: DATABASE_URL not set. Using SQLite as fallback (not production-safe).", file=sys.stderr)

print(f"[Config] Startup configuration validated. ENCRYPTION_KEY: {'SET' if settings.ENCRYPTION_KEY else 'MISSING'}")
