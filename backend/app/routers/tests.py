from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
import uuid

from backend.app.database.database import get_async_db
from backend.app.models.models import User, TestSuggestion, Analysis, Repository
from backend.app.schemas.schemas import TestSuggestionOut
from backend.app.auth.security import get_current_user

router = APIRouter(prefix="/tests", tags=["Test Generation"])

@router.get("/analysis/{analysis_id}", response_model=List[TestSuggestionOut])
async def get_test_suggestions(
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
        select(TestSuggestion).where(TestSuggestion.analysis_id == analysis_id)
    )
    return findings_res.scalars().all()
