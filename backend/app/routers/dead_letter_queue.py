import uuid
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from backend.app.database.database import get_async_db
from backend.app.models.models import User, DeadLetterTask, Analysis, Repository
from backend.app.schemas.schemas import DeadLetterTaskOut
from backend.app.auth.security import get_current_user
from backend.app.tasks.tasks import run_analysis_task
from backend.app.utils.audit import log_audit_event
from backend.app.utils.logger import get_logger

logger = get_logger("dlq_router")
router = APIRouter(prefix="/dead-letter-queue", tags=["dead-letter-queue"])

@router.get("", response_model=List[DeadLetterTaskOut])
async def get_dlq_tasks(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    resolved: Optional[bool] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    # Retrieve DLQ tasks for analysis runs linked to the current user's connected repositories
    repo_ids_res = await db.execute(
        select(Repository.id).where(Repository.user_id == current_user.id)
    )
    repo_ids = [str(r) for r in repo_ids_res.scalars().all()]
    
    if not repo_ids:
        return []
        
    query = select(DeadLetterTask)
    
    # Filter only tasks whose analysis runs match user's repository list
    # The analysis_id is stored in arguments -> e.g. {"analysis_id": "uuid"}
    # For SQLite compatibility, we can select all tasks and filter in memory, or use JSON extracts if simple.
    # To ensure 100% database compatibility between sqlite and postgres, let's load recent DLQ tasks and filter.
    raw_tasks_res = await db.execute(
        select(DeadLetterTask).order_by(desc(DeadLetterTask.failed_at)).offset(skip).limit(limit)
    )
    raw_tasks = raw_tasks_res.scalars().all()
    
    user_tasks = []
    for t in raw_tasks:
        if resolved is not None and t.resolved != resolved:
            continue
            
        args = t.arguments or {}
        analysis_id_str = args.get("analysis_id")
        if not analysis_id_str:
            continue
            
        # Verify the analysis run belongs to the user
        try:
            an_uuid = uuid.UUID(analysis_id_str)
            an_res = await db.execute(
                select(Analysis.repository_id).where(Analysis.id == an_uuid)
            )
            rep_id = an_res.scalar()
            if rep_id and str(rep_id) in repo_ids:
                user_tasks.append(t)
        except Exception:
            continue
            
    return user_tasks

@router.post("/{task_id}/retry", response_model=DeadLetterTaskOut)
async def retry_dlq_task(
    task_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    dlq_res = await db.execute(
        select(DeadLetterTask).where(DeadLetterTask.id == task_id)
    )
    dlq_task = dlq_res.scalars().first()
    if not dlq_task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="DLQ task not found.")
        
    args = dlq_task.arguments or {}
    analysis_id_str = args.get("analysis_id")
    if not analysis_id_str:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incomplete task arguments, missing analysis_id.")
        
    # Check authorization
    an_uuid = uuid.UUID(analysis_id_str)
    an_res = await db.execute(
        select(Analysis).where(Analysis.id == an_uuid)
    )
    analysis = an_res.scalars().first()
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis record not found.")
        
    repo_res = await db.execute(
        select(Repository).where((Repository.id == analysis.repository_id) & (Repository.user_id == current_user.id))
    )
    repo = repo_res.scalars().first()
    if not repo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to repository scan.")
        
    # Reset analysis record status to pending and reset progress
    analysis.status = "pending"
    analysis.progress = 0
    analysis.timestamp = datetime.utcnow()
    
    # Mark task as resolved
    dlq_task.resolved = True
    dlq_task.resolved_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(dlq_task)
    
    # Dispatch to Celery
    run_analysis_task.delay(str(analysis.id))
    
    await log_audit_event(
        db=db,
        action="DLQ_TASK_RETRY_TRIGGERED",
        user_id=current_user.id,
        details={
            "dlq_task_id": str(task_id),
            "analysis_id": str(analysis.id),
            "repository": repo.name
        }
    )
    
    return dlq_task
