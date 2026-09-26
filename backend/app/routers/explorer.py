from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
import asyncio
import uuid
import os

from app.database.database import get_async_db
from app.models.models import User, Repository, Analysis
from app.auth.security import get_current_user
from app.auth.encryption import encryptor
from app.services.github_service import GitHubService
from app.tasks.tasks import enqueue_analysis_task
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger("explorer_router")

router = APIRouter(prefix="/repositories", tags=["Explorer"])

# Extensions that are never rendered as text in the code viewer.
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tiff", ".svg",
    ".zip", ".tar", ".gz", ".tgz", ".bz2", ".rar", ".7z", ".xz",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".o", ".a", ".lib", ".out",
    ".mp4", ".mkv", ".avi", ".mov", ".flv", ".mp3", ".wav", ".flac", ".ogg",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".db", ".sqlite", ".dat", ".jar", ".class", ".pyc",
}

# GitHub contents API hard limit: files > 1 MB cannot be returned via this API.
MAX_FILE_BYTES = 1_000_000

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


async def _resolve_scan_snapshot(repo, db: AsyncSession):
    """Resolve the commit SHA + branch this repository's scans are pinned to.

    Single source of truth for the analyzed snapshot: the latest completed
    full-repository scan records its exact commit SHA on the Analysis row
    (analyses.commit_sha). Code Explorer serves THAT snapshot so findings,
    reports, chat and file content always describe the same code state —
    never the moving branch HEAD.
    """
    scan_res = await db.execute(
        select(Analysis)
        .where(
            (Analysis.repository_id == repo.id)
            & (Analysis.status == "completed")
            & ((Analysis.is_deleted == False) | (Analysis.is_deleted.is_(None)))
            & (Analysis.pull_request_id.is_(None))
        )
        .order_by(Analysis.timestamp.desc())
        .limit(1)
    )
    latest_scan = scan_res.scalars().first()
    if latest_scan and latest_scan.commit_sha:
        return latest_scan.commit_sha, (latest_scan.branch or repo.default_branch)
    # No completed snapshot recorded (or pre-migration scan): fall back to the
    # branch ref so the explorer still works, and say so via the branch return.
    return None, repo.default_branch


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
        
        # Resolve the analyzed snapshot: pinned scan commit when available,
        # otherwise the default branch ref. The tree is fetched ONCE against
        # this exact ref and cached by React Query on the frontend.
        ref, branch_used = await _resolve_scan_snapshot(repo, db)
        if not ref:
            ref = repo.default_branch or "main"
        
        # PyGithub is synchronous: run off the event loop with a hard timeout
        # (on-loop calls previously froze the entire server — see repositories
        # router PR-sync note).
        def _fetch_tree():
            gh_repo = github_service.client.get_repo(repo.name)
            return gh_repo.get_git_tree(ref, recursive=True)
        git_tree = await asyncio.wait_for(asyncio.to_thread(_fetch_tree), timeout=30)
        tree = build_explorer_tree(git_tree.tree)
        return {
            "tree": tree,
            "ref": ref,
            "branch": branch_used,
            # True when the tree is served from the pinned scan commit rather
            # than a moving branch name.
            "snapshot_pinned": bool(ref and ref != branch_used),
            "truncated": bool(getattr(git_tree, "truncated", False)),
        }
    except Exception as e:
        # repr() instead of str(): GithubException.__str__ can be "None" when
        # the API returns no payload, which produced useless error messages.
        logger.error(f"Explorer tree generation failed: {e!r}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Failed to fetch directory tree: {e!r}")

@router.get("/{id}/files")
async def get_file_content(
    id: uuid.UUID,
    path: str,
    ref: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """Return the COMPLETE content of one file.

    The file is fetched in a single GitHub API call against the analyzed
    snapshot commit (or ?ref=) — never in pieces. Scrolling on the frontend
    never triggers additional requests: the full content is returned here and
    cached by React Query keyed on (repository, ref, path).
    """
    logger.info(f"User {current_user.id} requested file content: {path} for repository: {id}")
    if not path or not path.strip():
        raise HTTPException(status_code=400, detail="File path is required.")
    
    result = await db.execute(
        select(Repository).where((Repository.id == id) & (Repository.user_id == current_user.id))
    )
    repo = result.scalars().first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found.")
        
    pat = encryptor.decrypt(current_user.github_pat_encrypted) if current_user.github_pat_encrypted else settings.GITHUB_TOKEN
    if not pat:
         raise HTTPException(status_code=400, detail="GitHub PAT is not configured.")

    # Snapshot consistency: default to the pinned scan commit when one exists,
    # so the viewer shows exactly the code the analysis ran against.
    pinned_sha, _branch = await _resolve_scan_snapshot(repo, db)
    effective_ref = ref or pinned_sha or repo.default_branch

    if os.path.splitext(path)[1].lower() in BINARY_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"'{os.path.basename(path)}' is a binary file and cannot be displayed as text.")
         
    try:
        github_service = GitHubService(token=pat)
        # Single blocking GitHub call — off the event loop, hard timeout.
        def _fetch_file():
            gh_repo = github_service.client.get_repo(repo.name)
            return gh_repo.get_contents(path, ref=effective_ref)
        try:
            content_file = await asyncio.wait_for(asyncio.to_thread(_fetch_file), timeout=30)
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="GitHub did not respond in time while fetching the file. Please retry.")
        except Exception as gh_err:
            msg = str(gh_err)
            if "404" in msg or "Not Found" in msg:
                raise HTTPException(status_code=404, detail=f"File '{path}' not found at ref '{effective_ref}'. It may exist on a different branch or commit.")
            if "403" in msg or "rate limit" in msg.lower():
                raise HTTPException(status_code=429, detail="GitHub API rate limit exceeded or access denied. Check your PAT or retry later.")
            raise
        if isinstance(content_file, list):
            raise HTTPException(status_code=400, detail=f"'{path}' is a directory, not a file.")
        if (content_file.size or 0) > MAX_FILE_BYTES or content_file.content is None:
            raise HTTPException(status_code=413, detail=f"File '{path}' is too large to display (GitHub contents API limit is 1 MB).")
        raw = content_file.decoded_content or b""
        if b"\x00" in raw[:8000]:
            raise HTTPException(status_code=415, detail=f"'{os.path.basename(path)}' appears to be a binary file and cannot be displayed as text.")
        content = raw.decode("utf-8", errors="replace")
        line_count = len(content.splitlines())
        logger.info(f"Returned COMPLETE file {path} ({line_count} lines, {len(content)} chars) at ref {effective_ref}")
        return {
            "content": content,
            "path": path,
            "ref": effective_ref,
            "snapshot_pinned": bool(pinned_sha),
            "size": content_file.size,
            "line_count": line_count,
        }
    except HTTPException:
        raise
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
        
        # Blocking commit operations — off the event loop, hard timeout.
        def _commit_update():
            gh_repo = github_service.client.get_repo(repo.name)
            contents = gh_repo.get_contents(req.path, ref=repo.default_branch)
            if isinstance(contents, list):
                return None
            gh_repo.update_file(
                path=req.path,
                message=req.commit_message,
                content=req.content,
                sha=contents.sha,
                branch=repo.default_branch,
            )
            return True
        commit_result = await asyncio.wait_for(asyncio.to_thread(_commit_update), timeout=60)
        if commit_result is None:
            raise HTTPException(status_code=400, detail="Target path is a directory list, not a file.")
        logger.info(f"Committed save to {req.path} directly to branch {repo.default_branch}")
        
        # Trigger background analysis re-scan only if no scan is currently running
        running_scan = await db.execute(
            select(Analysis).where(
                (Analysis.repository_id == repo.id) &
                (Analysis.status.in_(["pending", "running"])) &
                ((Analysis.is_deleted == False) | (Analysis.is_deleted.is_(None)))
            )
        )
        existing_running = running_scan.scalars().first()
        
        if existing_running:
            logger.info(f"Re-scan skipped — analysis {existing_running.id} is already running for repo {repo.id}")
            return {"success": True, "analysis_id": str(existing_running.id), "note": "scan_already_running"}
        
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
            enqueue_analysis_task(background_tasks, str(new_analysis.id))
            logger.info(f"Re-scan analysis queued successfully: {new_analysis.id}")
        except Exception as queue_err:
            logger.error(f"Failed to queue re-scan analysis task {new_analysis.id}: {queue_err}", exc_info=True)
            new_analysis.status = "failed"
            new_analysis.progress = 100
            new_analysis.insights = f"Failed to queue re-scan task: {queue_err}"
            db.add(new_analysis)
            await db.commit()
        
        return {"success": True, "analysis_id": str(new_analysis.id), "note": "scan_queued"}
    except Exception as e:
        logger.error(f"Commit save failed for file {req.path}: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Failed to commit changes to GitHub: {str(e)}")
