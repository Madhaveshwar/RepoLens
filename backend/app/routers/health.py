from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import redis.asyncio as aioredis

from app.database.database import get_async_db
from app.config import settings

router = APIRouter(prefix="/health", tags=["Health Checks"])

@router.get("")
async def health_check(db: AsyncSession = Depends(get_async_db)):
    db_status = "healthy"
    try:
        # Check DB liveness
        await db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"
        
    redis_status = "healthy"
    r = None
    try:
        # Check Redis liveness
        r = aioredis.from_url(settings.REDIS_URL, socket_timeout=3, socket_connect_timeout=3)
        await r.ping()
    except Exception as e:
        redis_status = f"unhealthy: {str(e)}"
    finally:
        if r is not None:
            try:
                await r.aclose()
            except Exception:
                pass
        
    return {
        "status": "healthy" if db_status == "healthy" and redis_status == "healthy" else "degraded",
        "api": "online",
        "database": db_status,
        "cache_broker": redis_status,
        # Surface the actual DB file so a server started from the wrong
        # directory is immediately obvious (empty/duplicate dev.db bug).
        "db_path": settings.DATABASE_URL.split("///")[-1] if settings.DATABASE_URL.startswith("sqlite") else "external",
        "environment": settings.ENVIRONMENT,
    }
