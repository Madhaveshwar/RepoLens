from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from typing import AsyncGenerator, Generator
from app.config import settings

# ── Connection pooling ──────────────────────────────────────────────────
# Reuse pooled connections instead of paying TCP+TLS+auth setup per request
# (significant against cloud Postgres such as Render).pool_size of 10 with
# overflow 20 comfortably serves the API; pre_ping guards against stale
# connections. SQLite (tests) must NOT use pool sizing options.
_IS_SQLITE = settings.DATABASE_URL.startswith("sqlite")

# Async Engine and Session for FastAPI
async_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,
    **({} if _IS_SQLITE else {"pool_size": 10, "max_overflow": 20, "pool_recycle": 1800}),
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False
)

# Sync Engine and Session for Celery & Alembic (sync Postgres engine)
# Make sure postgresql:// driver is parsed
sync_db_url = settings.SYNC_DATABASE_URL
if sync_db_url.startswith("postgresql+asyncpg://"):
    sync_db_url = sync_db_url.replace("postgresql+asyncpg://", "postgresql://")

sync_engine = create_engine(
    sync_db_url,
    echo=False,
    pool_pre_ping=True,
    **({} if sync_db_url.startswith("sqlite") else {"pool_size": 5, "max_overflow": 10, "pool_recycle": 1800}),
)

SessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,
    autoflush=False
)

Base = declarative_base()

async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for async FastAPI database sessions."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

def get_sync_db() -> Generator:
    """Helper for sync database sessions (e.g. Celery tasks)."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
