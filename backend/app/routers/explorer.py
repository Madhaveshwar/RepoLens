from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
import uuid
import os

from backend.app.database.database import get_async_db
from backend.app.models.models import User, Repository, Analysis
from backend.app.auth.security import get_current_user
from backend.app.auth.encryption import encryptor
from backend.app.services.github_service import GitHubService
from backend.app.tasks.tasks import run_analysis_task
from backend.app.config import settings
from backend.app.utils.logger import get_logger

logger = get_logger("explorer_router")

router = APIRouter(prefix="/repositories", tags=["Explorer"])

class SaveFileRequest(BaseModel):
    path: str
    content: str
    commit_message: str

def build_explorer_tree(tree_elements) -> list:
    root = []
    path_map = {}
    
    # Sort elements so that directories are processed before files (optional but makes tree clean)
    sorted_elements = sorted(tree_elements, key=lambda e: e.path)
    
    for element in sorted_elements:
        # Ignore common ignored patterns
        ignored_patterns = ["node_modules", ".git", "dist", "build", ".pytest_cache", "__pycache__"]
        if any(pat in element.path.split("/") for pat in ignored_patterns):
            continue
            
        parts = element.path.split("/")
        current_level = root
        current_path = ""
        
        for i, part in enumerate(parts):
            current_path = f"{current_path}/{part}" if current_path else part
            is_file = (i == len(parts) - 1) and (element.type == "blob")
            
            if current_path not in path_map:
                node = {
                    "name": part,
                    "type": "file" if is_file else "dir",
                    "path": current_path
                }
                if not is_file:
                    node["children"] = []
                path_map[current_path] = node
                current_level.append(node)
                
            if not is_file:
                current_level = path_map[current_path]["children"]
                
    return root

@router.get("/{id}/explorer")
async def get_repository_explorer(
    id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    logger.info(f"User {current_user.id} requested explorer tree for repository: {id}")
    # 1. Fetch Repository
    result = await db.execute(
        select(Repository).where((Repository.id == id) & (Repository.user_id == current_user.id))
    )
    repo = result.scalars().first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found.")
        
    pat = encryptor.decrypt(current_user.github_pat_encrypted) if current_user.github_pat_encrypted else settings.GITHUB_TOKEN
    if not pat:
        raise HTTPException(status_code=400, detail="GitHub Personal Access Token is not configured.")
        
    try:
        github_service = GitHubService(token=pat)
        gh_repo = github_service.client.get_repo(repo.name)
        
        # Get full git tree for default branch
        git_tree = gh_repo.get_git_tree(repo.default_branch, recursive=True)
        tree = build_explorer_tree(git_tree.tree)
        return tree
    except Exception as e:
        logger.error(f"Explorer tree generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Failed to fetch directory tree: {str(e)}")

@router.get("/{id}/files")
async def get_file_content(
    id: uuid.UUID,
    path: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    logger.info(f"User {current_user.id} requested file content: {path} for repository: {id}")
    result = await db.execute(
        select(Repository).where((Repository.id == id) & (Repository.user_id == current_user.id))
    )
    repo = result.scalars().first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found.")
        
    pat = encryptor.decrypt(current_user.github_pat_encrypted) if current_user.github_pat_encrypted else settings.GITHUB_TOKEN
    if not pat:
         raise HTTPException(status_code=400, detail="GitHub PAT is not configured.")
         
    try:
        github_service = GitHubService(token=pat)
        content = github_service.get_file_content(repo.name, path, ref=repo.default_branch)
        return {"content": content, "path": path}
    except Exception as e:
        logger.error(f"Failed to download file content for {path}: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Failed to download file: {str(e)}")

@router.post("/{id}/files")
async def save_file_content(
    id: uuid.UUID,
    req: SaveFileRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    logger.info(f"User {current_user.id} requested saving content to file: {req.path} for repository: {id}")
    result = await db.execute(
        select(Repository).where((Repository.id == id) & (Repository.user_id == current_user.id))
    )
    repo = result.scalars().first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found.")
        
    pat = encryptor.decrypt(current_user.github_pat_encrypted) if current_user.github_pat_encrypted else settings.GITHUB_TOKEN
    if not pat:
         raise HTTPException(status_code=400, detail="GitHub PAT is not configured.")
         
    try:
        github_service = GitHubService(token=pat)
        gh_repo = github_service.client.get_repo(repo.name)
        
        # Get file contents details to fetch SHA
        contents = gh_repo.get_contents(req.path, ref=repo.default_branch)
        if isinstance(contents, list):
            raise HTTPException(status_code=400, detail="Target path is a directory list, not a file.")
            
        # Push commit
        gh_repo.update_file(
            path=req.path,
            message=req.commit_message,
            content=req.content,
            sha=contents.sha,
            branch=repo.default_branch
        )
        logger.info(f"Committed save to {req.path} directly to branch {repo.default_branch}")
        
        # Trigger background analysis re-scan immediately to update findings
        new_analysis = Analysis(
            repository_id=repo.id,
            pull_request_id=None,
            status="pending",
            progress=0,
            is_deleted=False
        )
        db.add(new_analysis)
        await db.commit()
        await db.refresh(new_analysis)
        
        try:
            run_analysis_task.delay(str(new_analysis.id))
            logger.info(f"Re-scan analysis queued successfully: {new_analysis.id}")
        except Exception as queue_err:
            logger.warning(f"Failed to queue re-scan Celery analysis task {new_analysis.id}, falling back to FastAPI BackgroundTasks: {queue_err}")
            try:
                background_tasks.add_task(run_analysis_task, None, str(new_analysis.id))
                logger.info(f"Successfully enqueued re-scan analysis task {new_analysis.id} via BackgroundTasks fallback.")
            except Exception as bg_err:
                logger.error(f"Failed to queue background re-scan analysis task {new_analysis.id} even with fallback: {bg_err}", exc_info=True)
                new_analysis.status = "failed"
                new_analysis.progress = 100
                new_analysis.insights = f"Failed to queue background re-scan task: {bg_err}"
                db.add(new_analysis)
                await db.commit()
        
        return {"success": True, "analysis_id": str(new_analysis.id)}
    except Exception as e:
        logger.error(f"Commit save failed for file {req.path}: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Failed to commit changes to GitHub: {str(e)}")

