from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import redis.asyncio as aioredis

from backend.app.database.database import get_async_db
from backend.app.config import settings

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
    try:
        # Check Redis liveness
        r = aioredis.from_url(settings.REDIS_URL)
        await r.ping()
        await r.close()
    except Exception as e:
        redis_status = f"unhealthy: {str(e)}"
        
    return {
        "status": "healthy" if db_status == "healthy" and redis_status == "healthy" else "degraded",
        "api": "online",
        "database": db_status,
        "cache_broker": redis_status
    }
