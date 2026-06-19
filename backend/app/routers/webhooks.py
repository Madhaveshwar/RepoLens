import hmac
import hashlib
import json
from fastapi import APIRouter, Request, Header, HTTPException, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.app.config import settings
from backend.app.database.database import get_async_db
from backend.app.models.models import Repository, PullRequest, Analysis
from backend.app.tasks.tasks import run_analysis_task
from backend.app.utils.audit import log_audit_event
from backend.app.utils.logger import get_logger

logger = get_logger("webhooks_router")
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

@router.post("/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(...),
    x_hub_signature_256: str = Header(None),
    db: AsyncSession = Depends(get_async_db)
):
    body = await request.body()
    
    # Signature Verification
    if settings.GITHUB_WEBHOOK_SECRET:
        if not x_hub_signature_256:
            logger.warning("Webhook verification failed: missing X-Hub-Signature-256 header.")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Signature missing.")
        
        expected_sig = "sha256=" + hmac.new(
            settings.GITHUB_WEBHOOK_SECRET.encode("utf-8"),
            body,
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(x_hub_signature_256, expected_sig):
            logger.warning("Webhook verification failed: signature mismatch.")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Signature mismatch.")
            
    payload = {}
    if body:
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception as parse_err:
            logger.error(f"Failed to parse webhook JSON body: {parse_err}")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body.")
            
    logger.info(f"Received GitHub webhook event: {x_github_event}")
    
    if x_github_event == "ping":
        return {"message": "pong"}
        
    elif x_github_event == "pull_request":
        action = payload.get("action")
        # Trigger review on opened, synchronized (push to PR branch), or reopened
        if action in ["opened", "synchronize", "reopened"]:
            pr_data = payload.get("pull_request", {})
            repo_data = payload.get("repository", {})
            repo_full_name = repo_data.get("full_name")
            pr_number = pr_data.get("number")
            pr_title = pr_data.get("title", f"PR #{pr_number}")
            pr_author = pr_data.get("user", {}).get("login", "unknown")
            head_sha = pr_data.get("head", {}).get("sha")
            base_sha = pr_data.get("base", {}).get("sha")
            
            if not repo_full_name or not pr_number:
                return {"message": "Incomplete payload, skipping scan trigger."}
                
            # Find matching connected repository in our DB
            repo_res = await db.execute(
                select(Repository).where(
                    (Repository.name == repo_full_name) & 
                    ((Repository.is_connected == True) | (Repository.is_connected.is_(None)))
                )
            )
            repo = repo_res.scalars().first()
            if not repo:
                logger.info(f"Repository {repo_full_name} is not connected to AI Code Reviewer. Skipping webhook trigger.")
                return {"message": f"Repository {repo_full_name} not connected."}
                
            # Create or update PullRequest record
            pr_res = await db.execute(
                select(PullRequest).where(
                    (PullRequest.repository_id == repo.id) & 
                    (PullRequest.number == pr_number)
                )
            )
            pr_record = pr_res.scalars().first()
            if not pr_record:
                pr_record = PullRequest(
                    repository_id=repo.id,
                    number=pr_number,
                    title=pr_title,
                    author=pr_author,
                    head_sha=head_sha or "",
                    base_sha=base_sha or ""
                )
                db.add(pr_record)
                await db.commit()
                await db.refresh(pr_record)
            else:
                # Update SHAs in case of synchronized commit additions
                if head_sha: pr_record.head_sha = head_sha
                if base_sha: pr_record.base_sha = base_sha
                await db.commit()
                await db.refresh(pr_record)
                
            # Create Analysis task record
            analysis = Analysis(
                repository_id=repo.id,
                pull_request_id=pr_record.id,
                status="pending",
                progress=0
            )
            db.add(analysis)
            await db.commit()
            await db.refresh(analysis)
            
            # Trigger celery review
            run_analysis_task.delay(str(analysis.id))
            
            await log_audit_event(
                db=db,
                action="WEBHOOK_PR_REVIEW_TRIGGERED",
                user_id=repo.user_id,
                details={
                    "repository": repo_full_name,
                    "pr_number": pr_number,
                    "action": action,
                    "analysis_id": str(analysis.id)
                }
            )
            return {"message": f"Scan triggered for PR #{pr_number}", "analysis_id": str(analysis.id)}
            
    elif x_github_event == "push":
        ref = payload.get("ref", "")
        repo_data = payload.get("repository", {})
        repo_full_name = repo_data.get("full_name")
        
        if not repo_full_name or not ref:
            return {"message": "Incomplete payload, skipping."}
            
        repo_res = await db.execute(
            select(Repository).where(
                (Repository.name == repo_full_name) & 
                ((Repository.is_connected == True) | (Repository.is_connected.is_(None)))
            )
        )
        repo = repo_res.scalars().first()
        if not repo:
            return {"message": f"Repository {repo_full_name} not connected."}
            
        # Trigger scan if the push is to the default branch
        if ref == f"refs/heads/{repo.default_branch}":
            analysis = Analysis(
                repository_id=repo.id,
                pull_request_id=None,
                status="pending",
                progress=0
            )
            db.add(analysis)
            await db.commit()
            await db.refresh(analysis)
            
            run_analysis_task.delay(str(analysis.id))
            
            await log_audit_event(
                db=db,
                action="WEBHOOK_PUSH_SCAN_TRIGGERED",
                user_id=repo.user_id,
                details={
                    "repository": repo_full_name,
                    "ref": ref,
                    "analysis_id": str(analysis.id)
                }
            )
            return {"message": f"Scan triggered for branch {repo.default_branch}", "analysis_id": str(analysis.id)}
            
    return {"message": f"Event {x_github_event} ignored."}
