from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
import uuid

from app.database.database import get_async_db
from app.models.models import User, SecurityFinding, Analysis, Repository
from app.schemas.schemas import SecurityFindingOut
from app.auth.security import get_current_user

router = APIRouter(prefix="/security", tags=["Security"])

@router.get("/analysis/{analysis_id}", response_model=List[SecurityFindingOut])
async def get_security_findings(
    analysis_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    # Verify user has access to this analysis
    result = await db.execute(
        select(Analysis)
        .join(Repository)
        .where((Analysis.id == analysis_id) & (Repository.user_id == current_user.id))
    )
    analysis = result.scalars().first()
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis not found or permission denied."
        )
        
    findings_res = await db.execute(
        select(SecurityFinding).where(SecurityFinding.analysis_id == analysis_id)
    )
    return findings_res.scalars().all()
