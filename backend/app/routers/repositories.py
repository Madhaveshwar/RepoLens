from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
import asyncio
import uuid

from app.database.database import get_async_db
from app.models.models import User, Repository, PullRequest, Analysis
from app.schemas.schemas import RepositoryConnect, RepositoryOut, PullRequestOut
from app.auth.security import get_current_user
from app.auth.encryption import encryptor
from app.services.github_service import GitHubService, parse_repo_url
from app.config import settings
from app.utils.logger import get_logger
from app.schemas.schemas import GitPushRequest, GitAutomationRequest

logger = get_logger("repositories_router")

router = APIRouter(prefix="/repositories", tags=["Repositories"])

@router.get("", response_model=List[RepositoryOut])
async def list_repositories(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    result = await db.execute(
        select(Repository).where(
            (Repository.user_id == current_user.id) &
            ((Repository.is_connected == True) | (Repository.is_connected.is_(None)))
        )
    )
    repos = result.scalars().all()
    pat = encryptor.decrypt(current_user.github_pat_encrypted) if current_user.github_pat_encrypted else settings.GITHUB_TOKEN
    github_service = None
    if pat:
        try:
            github_service = GitHubService(token=pat)
        except Exception as e:
            logger.error(f"Error initializing GitHubService in list_repositories: {e}")

    out_repos = []
    for r in repos:
        # Get latest completed scan stats
        scan_res = await db.execute(
            select(Analysis)
            .where((Analysis.repository_id == r.id) & (Analysis.status == "completed") & ((Analysis.is_deleted == False) | (Analysis.is_deleted.is_(None))))
            .order_by(Analysis.timestamp.desc())
            .limit(1)
        )
        latest_scan = scan_res.scalars().first()
        r.last_scanned_at = latest_scan.timestamp if latest_scan else None
        r.latest_risk_score = latest_scan.risk_score if latest_scan else None
        
        perms = {"admin": False, "push": False, "pull": True}
        if github_service:
            try:
                # PyGithub is synchronous — NEVER call it directly on the event
                # loop: a slow/rate-limited GitHub response would freeze EVERY
                # endpoint (observed live). Run off-loop with a hard timeout;
                # on timeout/failure we keep the default permissive-less perms.
                async def _perms():
                    return await asyncio.to_thread(
                        lambda: getattr(github_service.client.get_repo(r.name), "permissions", None)
                    )
                gh_perms = await asyncio.wait_for(_perms(), timeout=20)
                if gh_perms:
                    perms = {
                        "admin": bool(getattr(gh_perms, "admin", False)),
                        "push": bool(getattr(gh_perms, "push", False)),
                        "pull": bool(getattr(gh_perms, "pull", True))
                    }
            except Exception as e:
                logger.error(f"Error checking repo permissions for {r.name} in list_repositories: {e}")
        r.permissions = perms
        out_repos.append(r)
    return out_repos

@router.post("", response_model=RepositoryOut, status_code=status.HTTP_201_CREATED)
async def connect_repository(
    repo_in: RepositoryConnect,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    logger.info(f"[Audit Log] User {current_user.id} requested connecting repository: {repo_in.url}")
    repo_name = parse_repo_url(repo_in.url)
    if not repo_name:
        logger.warning(f"Failed to connect repository: Invalid URL '{repo_in.url}'")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid GitHub repository URL. Use format: https://github.com/owner/repo or owner/repo."
        )
        
    # Check if repository already connected for this user
    result = await db.execute(
        select(Repository).where(
            (Repository.name == repo_name) & (Repository.user_id == current_user.id)
        )
    )
    existing_repo = result.scalars().first()
    if existing_repo:
        if not existing_repo.is_connected:
            existing_repo.is_connected = True
            await db.commit()
            await db.refresh(existing_repo)
            logger.info(f"[Audit Log] Reconnected existing repository {repo_name} for user {current_user.id}.")
        return existing_repo
        
    # Get user token for loading details
    pat = encryptor.decrypt(current_user.github_pat_encrypted) if current_user.github_pat_encrypted else settings.GITHUB_TOKEN
    
    try:
        logger.info(f"Loading details for repo: {repo_name} (token_configured: {bool(pat)})")
        github_service = GitHubService(token=pat)
        # Blocking PyGithub calls MUST run off the event loop (see PR sync note
        # below); get_repo_details makes several sequential GitHub requests.
        details = await asyncio.wait_for(
            asyncio.to_thread(github_service.get_repo_details, repo_name),
            timeout=45,
        )
    except asyncio.TimeoutError:
        logger.error(f"GitHub request timeout while fetching details for {repo_name}")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="GitHub did not respond in time. Please try again."
        )
    except Exception as exc:
        logger.error(f"Failed to fetch repo details for {repo_name}: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch repository details: {str(exc)}"
        )
        
    new_repo = Repository(
        user_id=current_user.id,
        name=details["name"],
        description=details["description"],
        stars=details["stars"],
        forks=details["forks"],
        open_prs_count=details["open_prs_count"],
        open_issues_count=details["open_issues_count"],
        default_branch=details["default_branch"],
        languages=details["languages"],
        is_connected=True
    )
    db.add(new_repo)
    await db.commit()
    await db.refresh(new_repo)
    
    # Pre-sync pull requests (off the event loop — one lazy GitHub request
    # PER PR attribute here previously froze the whole server)
    try:
        prs = await asyncio.wait_for(
            asyncio.to_thread(github_service.get_open_pull_requests, repo_name),
            timeout=30,
        )
        for pr_data in prs:
            db.add(PullRequest(
                repository_id=new_repo.id,
                number=pr_data.get("number", 0),
                title=pr_data.get("title", "Unknown PR"),
                author=pr_data.get("author", "unknown"),
                state=pr_data.get("state", "open"),
                additions=pr_data.get("additions", 0),
                deletions=pr_data.get("deletions", 0),
                head_sha=pr_data.get("head_sha", ""),
                base_sha=pr_data.get("base_sha", "")
            ))
        await db.commit()
    except Exception as pr_sync_err:
        print(f"Non-critical PR sync issue on registration: {pr_sync_err}")
        
    # Set permissions
    perms = {"admin": False, "push": False, "pull": True}
    if pat:
        try:
            github_service = GitHubService(token=pat)
            # Off-loop GitHub call with hard timeout (see list_repositories).
            gh_perms = await asyncio.wait_for(asyncio.to_thread(
                lambda: getattr(github_service.client.get_repo(new_repo.name), "permissions", None)
            ), timeout=20)
            if gh_perms:
                perms = {
                    "admin": bool(getattr(gh_perms, "admin", False)),
                    "push": bool(getattr(gh_perms, "push", False)),
                    "pull": bool(getattr(gh_perms, "pull", True))
                }
        except Exception as e:
            logger.error(f"Error checking repo permissions for {new_repo.name} in connect_repository: {e}")
    new_repo.permissions = perms
    return new_repo

@router.get("/{id}", response_model=RepositoryOut)
async def get_repository(
    id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    result = await db.execute(
        select(Repository).where(
            (Repository.id == id) & (Repository.user_id == current_user.id)
        )
    )
    repo = result.scalars().first()
    if not repo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found.")
        
    scan_res = await db.execute(
        select(Analysis)
        .where((Analysis.repository_id == repo.id) & (Analysis.status == "completed") & ((Analysis.is_deleted == False) | (Analysis.is_deleted.is_(None))))
        .order_by(Analysis.timestamp.desc())
        .limit(1)
    )
    latest_scan = scan_res.scalars().first()
    repo.last_scanned_at = latest_scan.timestamp if latest_scan else None
    repo.latest_risk_score = latest_scan.risk_score if latest_scan else None
    
    # Check permissions
    pat = encryptor.decrypt(current_user.github_pat_encrypted) if current_user.github_pat_encrypted else settings.GITHUB_TOKEN
    perms = {"admin": False, "push": False, "pull": True}
    if pat:
        try:
            github_service = GitHubService(token=pat)
            # Off-loop GitHub call with hard timeout (see list_repositories).
            gh_perms = await asyncio.wait_for(asyncio.to_thread(
                lambda: getattr(github_service.client.get_repo(repo.name), "permissions", None)
            ), timeout=20)
            if gh_perms:
                perms = {
                    "admin": bool(getattr(gh_perms, "admin", False)),
                    "push": bool(getattr(gh_perms, "push", False)),
                    "pull": bool(getattr(gh_perms, "pull", True))
                }
        except Exception as e:
            logger.error(f"Error checking repo permissions for {repo.name} in get_repository: {e}")
    repo.permissions = perms
    return repo

@router.get("/{id}/scan-identity")
async def get_scan_identity(
    id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """Scan identity / snapshot check.

    Compares the commit SHA of the user's latest completed scan with the
    CURRENT head of the repository's default branch on GitHub, so the UI can
    honestly say whether this exact repository state has already been
    analyzed — instead of silently producing a different-looking rescan.

    Returns real values only: nulls when data is unavailable.
    """
    result = await db.execute(
        select(Repository).where(
            (Repository.id == id) & (Repository.user_id == current_user.id)
        )
    )
    repo = result.scalars().first()
    if not repo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found.")

    # Latest completed scan + its snapshot (snapshot rows carry the pinned SHA)
    scan_res = await db.execute(
        select(Analysis)
        .where(
            (Analysis.repository_id == repo.id)
            & (Analysis.status == "completed")
            & ((Analysis.is_deleted == False) | (Analysis.is_deleted.is_(None)))
            & (Analysis.pull_request_id.is_(None))  # full repo scans only
        )
        .order_by(Analysis.timestamp.desc())
        .limit(1)
    )
    latest_scan = scan_res.scalars().first()

    from app.models.models import RepositoryHealthSnapshot
    last_scan_commit = None
    last_scan_at = None
    last_scan_id = None
    if latest_scan:
        last_scan_at = latest_scan.timestamp.isoformat() if latest_scan.timestamp else None
        last_scan_id = str(latest_scan.id)
        # Preferred source: the scan row itself (analyses.commit_sha is pinned
        # by the scan pipeline). Fall back to the health snapshot for scans
        # recorded before the snapshot columns existed.
        last_scan_commit = latest_scan.commit_sha
        if not last_scan_commit:
            snap_res = await db.execute(
                select(RepositoryHealthSnapshot)
                .where(RepositoryHealthSnapshot.analysis_id == latest_scan.id)
                .limit(1)
            )
            snapshot = snap_res.scalars().first()
            last_scan_commit = snapshot.commit_sha if snapshot else None

    # Current head on GitHub (may be unavailable — offline/PAT issues)
    current_head = None
    branch = repo.default_branch
    pat = encryptor.decrypt(current_user.github_pat_encrypted) if current_user.github_pat_encrypted else settings.GITHUB_TOKEN
    if pat:
        try:
            # Off-loop GitHub calls with hard timeout (see list_repositories).
            async def _head():
                def _resolve():
                    gh_repo = GitHubService(token=pat).client.get_repo(repo.name)
                    br = gh_repo.default_branch or branch
                    return br, gh_repo.get_branch(br).commit.sha
                return await asyncio.to_thread(_resolve)
            branch, current_head = await asyncio.wait_for(_head(), timeout=30)
        except Exception as e:
            logger.error(f"scan-identity: could not resolve current head for {repo.name}: {e}")

    same_state = bool(
        last_scan_commit and current_head and last_scan_commit == current_head
    )

    return {
        "repository_id": str(repo.id),
        "repository": repo.name,
        "branch": branch,
        "last_scan": {
            "analysis_id": last_scan_id,
            "commit_sha": last_scan_commit,
            "timestamp": last_scan_at,
        } if latest_scan else None,
        "current_head_commit": current_head,
        "already_analyzed": same_state,
        "message": (
            "This exact commit has already been analyzed." if same_state
            else "New repository state — a fresh scan is required."
            if current_head else None
        ),
    }


@router.get("/{id}/prs", response_model=List[PullRequestOut])
async def list_repository_prs(
    id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    result = await db.execute(
        select(Repository).where(
            (Repository.id == id) & (Repository.user_id == current_user.id)
        )
    )
    repo = result.scalars().first()
    if not repo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found.")
        
    pat = encryptor.decrypt(current_user.github_pat_encrypted) if current_user.github_pat_encrypted else settings.GITHUB_TOKEN
    try:
        github_service = GitHubService(token=pat)
        # CRITICAL PERF FIX: PyGithub is synchronous and makes MULTIPLE API
        # calls per PR (lazy attributes like additions/deletions trigger one
        # request EACH). Running it on the event loop thread blocked the ENTIRE
        # server whenever GitHub was slow — py-spy confirmed the loop frozen
        # inside PullRequest.additions. Offload to a worker thread with a hard
        # timeout so the loop (and /health) stay responsive.
        try:
            prs = await asyncio.wait_for(
                asyncio.to_thread(github_service.get_open_pull_requests, repo.name),
                timeout=30,
            )
        except asyncio.TimeoutError:
            logger.warning(f"GitHub PR sync timed out for {repo.name}; serving cached DB state.")
            prs = None
        
        db_prs_res = await db.execute(select(PullRequest).where(PullRequest.repository_id == repo.id))
        db_prs = {p.number: p for p in db_prs_res.scalars().all()}
        
        active_numbers = set()
        for pr_data in (prs or []):
            num = pr_data.get("number", 0)
            active_numbers.add(num)
            
            if num in db_prs:
                pr_obj = db_prs[num]
                pr_obj.title = pr_data.get("title", "Unknown PR")
                pr_obj.state = pr_data.get("state", "open")
                pr_obj.additions = pr_data.get("additions", 0)
                pr_obj.deletions = pr_data.get("deletions", 0)
                pr_obj.head_sha = pr_data.get("head_sha", "")
                pr_obj.base_sha = pr_data.get("base_sha", "")
                db.add(pr_obj)
            else:
                db.add(PullRequest(
                    repository_id=repo.id,
                    number=num,
                    title=pr_data.get("title", "Unknown PR"),
                    author=pr_data.get("author", "unknown"),
                    state=pr_data.get("state", "open"),
                    additions=pr_data.get("additions", 0),
                    deletions=pr_data.get("deletions", 0),
                    head_sha=pr_data.get("head_sha", ""),
                    base_sha=pr_data.get("base_sha", "")
                ))
                
        for num, pr_obj in db_prs.items():
            if num not in active_numbers:
                pr_obj.state = "closed"
                db.add(pr_obj)
                
        await db.commit()
    except Exception as e:
        print(f"Failed to sync PRs on request: {e}")
        
    final_prs = await db.execute(
        select(PullRequest).where(
            (PullRequest.repository_id == repo.id) & (PullRequest.state == "open")
        ).order_by(PullRequest.number.desc())
    )
    prs_list = list(final_prs.scalars().all())
    prs_list.sort(key=lambda x: x.number, reverse=True)
    return prs_list

@router.delete("/{id}")
async def delete_repository(
    id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    import os
    from app.models.models import Report, Analysis
    logger.info(f"[Audit Log] User {current_user.id} requested deletion of Repository id: {id}")
    result = await db.execute(
        select(Repository).where(
            (Repository.id == id) & (Repository.user_id == current_user.id)
        )
    )
    repo = result.scalars().first()
    if not repo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found.")
        
    # 1. Delete all associated physical report files
    analyses_res = await db.execute(select(Analysis.id).where(Analysis.repository_id == id))
    analysis_ids = analyses_res.scalars().all()
    if analysis_ids:
        reports_res = await db.execute(select(Report).where(Report.analysis_id.in_(analysis_ids)))
        reports = reports_res.scalars().all()
        for report in reports:
            if report.filepath and os.path.exists(report.filepath):
                try:
                    os.remove(report.filepath)
                    logger.info(f"Deleted report file: {report.filepath}")
                except Exception as e:
                    logger.error(f"Error removing report file: {e}")
                    
    # 2. Hard delete Repository and cascade database entries
    await db.delete(repo)
    await db.commit()
    logger.info(f"[Audit Log] Successfully deleted repository {repo.name} and all associated scans/reports.")
    return {"success": True}

@router.post("/{id}/disconnect")
async def disconnect_repository(
    id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    logger.info(f"[Audit Log] User {current_user.id} requested disconnection of Repository id: {id}")
    result = await db.execute(
        select(Repository).where(
            (Repository.id == id) & (Repository.user_id == current_user.id)
        )
    )
    repo = result.scalars().first()
    if not repo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found.")
        
    repo.is_connected = False
    db.add(repo)
    await db.commit()
    logger.info(f"[Audit Log] Successfully disconnected repository {repo.name} (history retained).")
    return {"success": True}

@router.post("/{id}/git-push")
async def push_to_github(
    id: uuid.UUID,
    push_req: GitPushRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """Push user-confirmed changes directly to GitHub as a commit."""
    logger.info(f"[Audit Log] User {current_user.id} requested git push for repo id: {id}")
    
    # Verify repository ownership
    result = await db.execute(
        select(Repository).where(
            (Repository.id == id) & (Repository.user_id == current_user.id)
        )
    )
    repo = result.scalars().first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found.")
    
    pat = encryptor.decrypt(current_user.github_pat_encrypted) if current_user.github_pat_encrypted else None
    if not pat:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub PAT not configured for your profile."
        )
    
    try:
        github_service = GitHubService(token=pat)
        gh_repo = github_service.client.get_repo(repo.name)
        
        # Get current file content and blob SHA
        try:
            contents = gh_repo.get_contents(push_req.file_path, ref=push_req.branch)
            original_sha = contents.sha
        except Exception:
            original_sha = None
        
        # Create or update file
        result = gh_repo.update_file(
            path=push_req.file_path,
            message=push_req.commit_message,
            content=push_req.file_content,
            sha=original_sha,
            branch=push_req.branch
        )
        
        logger.info(f"[Audit Log] Successfully pushed changes to {repo.name}:{push_req.file_path}")
        return {
            "success": True,
            "commit_sha": result["commit"].sha,
            "commit_url": result["commit"].html_url
        }
    except Exception as e:
        logger.error(f"Git push failed for {repo.name}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to push to GitHub: {str(e)}"
        )


@router.post("/{id}/automated-pr")
async def automated_pr(
    id: uuid.UUID,
    req: GitAutomationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Full GitHub automation workflow:
    1. Create a new branch from the default branch
    2. Push file changes to the new branch
    3. Open a pull request from the new branch to default
    """
    logger.info(f"[Audit Log] User {current_user.id} requested automated PR for repo id: {id}")

    # Verify repository ownership
    result = await db.execute(
        select(Repository).where(
            (Repository.id == id) & (Repository.user_id == current_user.id)
        )
    )
    repo = result.scalars().first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found.")

    pat = encryptor.decrypt(current_user.github_pat_encrypted) if current_user.github_pat_encrypted else None
    if not pat:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub PAT not configured for your profile."
        )

    github_service = GitHubService(token=pat)
    source_branch = repo.default_branch or "main"

    try:
        # Step 1: Create branch
        logger.info(f"Step 1: Creating branch '{req.branch_name}' from '{source_branch}'")
        github_service.create_branch(repo.name, req.branch_name, source_branch)

        # Step 2: Push file to the new branch
        logger.info(f"Step 2: Pushing {req.file_path} to branch '{req.branch_name}'")
        gh_repo = github_service.client.get_repo(repo.name)
        try:
            contents = gh_repo.get_contents(req.file_path, ref=source_branch)
            original_sha = contents.sha
        except Exception:
            original_sha = None

        push_result = gh_repo.update_file(
            path=req.file_path,
            message=req.commit_message,
            content=req.file_content,
            sha=original_sha,
            branch=req.branch_name
        )

        # Step 3: Create Pull Request
        logger.info(f"Step 3: Creating PR '{req.pr_title}' ({req.branch_name} -> {source_branch})")
        pr_result = github_service.create_pull_request(
            repo_name=repo.name,
            title=req.pr_title,
            body=req.pr_description,
            head=req.branch_name,
            base=source_branch
        )

        logger.info(f"[Audit Log] Automated PR completed for {repo.name}: branch={req.branch_name}, PR=#{pr_result['pr_number']}")
        return {
            "success": True,
            "branch": req.branch_name,
            "commit_sha": push_result["commit"].sha,
            "pr_number": pr_result["pr_number"],
            "pr_url": pr_result["pr_url"]
        }
    except Exception as e:
        logger.error(f"Automated PR workflow failed for {repo.name}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Automated PR workflow failed: {str(e)}"
        )


@router.get("/{id}/permissions")
async def get_repository_permissions(
    id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    result = await db.execute(
        select(Repository).where(
            (Repository.id == id) & (Repository.user_id == current_user.id)
        )
    )
    repo = result.scalars().first()
    if not repo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found.")
        
    pat = encryptor.decrypt(current_user.github_pat_encrypted) if current_user.github_pat_encrypted else settings.GITHUB_TOKEN
    perms = {"admin": False, "push": False, "pull": False}
    if not pat:
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="GitHub token is not configured.")
         
    try:
        github_service = GitHubService(token=pat)
        # Off-loop GitHub call with hard timeout (see list_repositories).
        gh_perms = await asyncio.wait_for(asyncio.to_thread(
            lambda: getattr(github_service.client.get_repo(repo.name), "permissions", None)
        ), timeout=20)
        if gh_perms:
            perms = {
                "admin": bool(getattr(gh_perms, "admin", False)),
                "push": bool(getattr(gh_perms, "push", False)),
                "pull": bool(getattr(gh_perms, "pull", True))
            }
        else:
            perms = {"admin": False, "push": False, "pull": True}
    except Exception as e:
        logger.error(f"Error checking repo permissions for {repo.name} in get_repository_permissions: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to check GitHub permissions: {str(e)}")
        
    return perms
