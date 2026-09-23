from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
import uuid

from app.database.database import get_async_db
from app.models.models import User, CodeSmell, Analysis, Repository
from app.schemas.schemas import CodeSmellOut
from app.auth.security import get_current_user

router = APIRouter(prefix="/code-quality", tags=["Code Quality"])

@router.get("/analysis/{analysis_id}", response_model=List[CodeSmellOut])
async def get_code_smells(
    analysis_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    # Verify user access
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
        select(CodeSmell).where(CodeSmell.analysis_id == analysis_id)
    )
    return findings_res.scalars().all()
