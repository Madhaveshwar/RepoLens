from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from app.database.database import get_async_db
from app.models.models import User, AuditLog
from app.schemas.schemas import AuditLogOut
from app.auth.security import get_current_user

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])

@router.get("", response_model=List[AuditLogOut])
async def get_audit_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    action: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    query = select(AuditLog).where(AuditLog.user_id == current_user.id)
    
    if action:
        query = query.where(AuditLog.action == action)
        
    query = query.order_by(desc(AuditLog.created_at)).offset(skip).limit(limit)
    res = await db.execute(query)
    return res.scalars().all()
