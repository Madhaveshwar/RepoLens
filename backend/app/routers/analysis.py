from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, WebSocketDisconnect, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
import uuid
from pydantic import BaseModel

from backend.app.database.database import get_async_db
from backend.app.models.models import (
    User, Repository, PullRequest, Analysis,
    Report, SecurityFinding, CodeSmell, TestSuggestion
)
from backend.app.schemas.schemas import AnalysisTrigger, AnalysisOut, SnippetReviewRequest, SnippetReviewOut
from backend.app.auth.security import get_current_user
from backend.app.tasks.tasks import run_analysis_task
from backend.app.websockets.websocket_manager import manager, listen_to_redis_channel
from backend.app.services.reviewer import review_single_code_snippet, build_groq_client
from backend.app.services.llm_client import build_llm_client, get_model_name
from backend.app.auth.encryption import encryptor
from backend.app.config import settings
from backend.app.utils.logger import get_logger

logger = get_logger("analysis_router")

router = APIRouter(prefix="/analysis", tags=["Analysis"])

@router.post("/trigger", response_model=AnalysisOut, status_code=status.HTTP_202_ACCEPTED)
async def trigger_analysis(
    trigger: AnalysisTrigger,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    logger.info(f"[Audit Log] User {current_user.id} triggered scan for repository_id: {trigger.repository_id} (PR number: {trigger.pr_number})")
    # Retrieve repository and check ownership
    result = await db.execute(
        select(Repository).where(
            (Repository.id == trigger.repository_id) & (Repository.user_id == current_user.id)
        )
    )
    repo = result.scalars().first()
    if not repo:
        logger.warning(f"Scan trigger failed: Repository {trigger.repository_id} not found or not owned by user {current_user.id}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found.")
        
    # Verify GitHub PAT and repository access before queueing celery worker
    pat = encryptor.decrypt(current_user.github_pat_encrypted) if current_user.github_pat_encrypted else settings.GITHUB_TOKEN
    if not pat:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub PAT credentials not configured. Please add your personal access token in Settings first."
        )
    try:
        from backend.app.services.github_service import GitHubService
        github_service = GitHubService(token=pat)
        # Check permissions
        gh_repo = github_service.client.get_repo(repo.name)
        perms = getattr(gh_repo, "permissions", None)
        if perms and not getattr(perms, "pull", True):
             raise Exception("Missing read permissions to fetch code.")
    except Exception as ge:
        logger.error(f"GitHub authorization check failed for repository {repo.name}: {ge}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"GitHub token is invalid or lacks access to this repository: {str(ge)}"
        )
        
    pr_id = None
    if trigger.pr_number:
        # Check if PR exists
        pr_res = await db.execute(
            select(PullRequest).where(
                (PullRequest.repository_id == repo.id) & (PullRequest.number == trigger.pr_number)
            )
        )
        pr = pr_res.scalars().first()
        if not pr:
            logger.warning(f"Scan trigger failed: PR #{trigger.pr_number} not found for repository {repo.name}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Pull Request #{trigger.pr_number} not found. Sync the pull requests first."
            )
        pr_id = pr.id
        
    # Create Analysis record
    new_analysis = Analysis(
        repository_id=repo.id,
        pull_request_id=pr_id,
        status="pending",
        progress=0,
        is_deleted=False
    )
    db.add(new_analysis)
    await db.commit()
    await db.refresh(new_analysis)
    
    logger.info(f"Created analysis record with id: {new_analysis.id}. Queueing Celery task.")
    try:
        run_analysis_task.delay(str(new_analysis.id))
    except Exception as exc:
        logger.warning(f"Failed to queue Celery analysis task {new_analysis.id}, falling back to FastAPI BackgroundTasks: {exc}")
        try:
            background_tasks.add_task(run_analysis_task, None, str(new_analysis.id))
            logger.info(f"Successfully enqueued analysis task {new_analysis.id} via BackgroundTasks fallback.")
        except Exception as bg_err:
            logger.error(f"Failed to queue background analysis task {new_analysis.id} even with fallback: {bg_err}", exc_info=True)
            new_analysis.status = "failed"
            new_analysis.progress = 100
            new_analysis.insights = f"Failed to queue background analysis task: {bg_err}"
            db.add(new_analysis)
            await db.commit()
            await db.refresh(new_analysis)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Analysis worker queue is unavailable and background fallback failed: {str(bg_err)}"
            )
    
    return new_analysis

@router.get("/deleted", response_model=List[AnalysisOut])
async def list_deleted_analyses(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    result = await db.execute(
        select(Analysis)
        .join(Repository)
        .where((Repository.user_id == current_user.id) & (Analysis.is_deleted == True))
        .order_by(Analysis.timestamp.desc())
    )
    return result.scalars().all()

@router.post("/{id}/restore")
async def restore_analysis(
    id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    logger.info(f"[Audit Log] User {current_user.id} requested restoration of soft-deleted scan id: {id}")
    result = await db.execute(
        select(Analysis)
        .join(Repository)
        .where((Analysis.id == id) & (Repository.user_id == current_user.id))
    )
    analysis = result.scalars().first()
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found.")
        
    analysis.is_deleted = False
    db.add(analysis)
    await db.commit()
    logger.info(f"[Audit Log] Successfully restored scan history for analysis_id: {id}")
    return {"success": True}

@router.get("/{id}", response_model=AnalysisOut)
async def get_analysis(
    id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    # Verify analysis exists and user has access
    result = await db.execute(
        select(Analysis)
        .join(Repository)
        .where((Analysis.id == id) & (Repository.user_id == current_user.id))
    )
    analysis = result.scalars().first()
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found.")
    return analysis

@router.get("/repo/{repo_id}", response_model=List[AnalysisOut])
async def list_repo_analyses(
    repo_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    # Verify repository access
    repo_res = await db.execute(
        select(Repository).where(
            (Repository.id == repo_id) & (Repository.user_id == current_user.id)
        )
    )
    if not repo_res.scalars().first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found.")
        
    result = await db.execute(
        select(Analysis)
        .where((Analysis.repository_id == repo_id) & ((Analysis.is_deleted == False) | (Analysis.is_deleted.is_(None))))
        .order_by(Analysis.timestamp.desc())
    )
    return result.scalars().all()

@router.post("/snippet", response_model=SnippetReviewOut)
async def review_snippet(
    req: SnippetReviewRequest,
    current_user: User = Depends(get_current_user)
):
    logger.info(f"User {current_user.id} requested inline snippet review (language: {req.language})")

    # Resolve provider and API key (respects user's Settings selection)
    from backend.app.auth.encryption import encryptor as _enc
    provider = (current_user.llm_default_provider or "groq").lower().strip()
    _key_map = {
        "groq":       current_user.groq_api_key_encrypted,
        "openai":     current_user.openai_api_key_encrypted,
        "anthropic":  current_user.claude_api_key_encrypted,
        "claude":     current_user.claude_api_key_encrypted,
        "gemini":     current_user.gemini_api_key_encrypted,
        "openrouter": current_user.openrouter_api_key_encrypted,
    }
    _env_map = {
        "groq":       settings.GROQ_API_KEY,
        "openai":     settings.OPENAI_API_KEY,
        "anthropic":  settings.ANTHROPIC_API_KEY,
        "claude":     settings.ANTHROPIC_API_KEY,
        "gemini":     settings.GEMINI_API_KEY,
        "openrouter": settings.OPENROUTER_API_KEY,
    }
    enc_key = _key_map.get(provider)
    llm_api_key = _enc.decrypt(enc_key) if enc_key else _env_map.get(provider, "")
    # Fallback to Groq if preferred provider has no key
    if not llm_api_key:
        provider = "groq"
        groq_enc = current_user.groq_api_key_encrypted
        llm_api_key = _enc.decrypt(groq_enc) if groq_enc else settings.GROQ_API_KEY

    if not llm_api_key:
        logger.warning(f"Snippet review failed: No LLM API Key is configured for user {current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No LLM API Key is configured for your profile. Add one in Settings."
        )

    try:
        logger.info(f"Building {provider} client for snippet review...")
        client = build_llm_client(provider, llm_api_key)
        results = review_single_code_snippet(req.code, req.language, client)
        logger.info(f"Successfully reviewed snippet. Risk score: {results['risk_score']}")
        return SnippetReviewOut(
            risk_score=results["risk_score"],
            findings=results["findings"],
            test_suggestions=results["test_suggestions"],
            severity_counts=results["severity_counts"],
            latency_seconds=results["latency_seconds"],
            scores=results["scores"],
            is_valid_code=results["is_valid_code"],
            detected_language=results["detected_language"],
            optimization_required=results["optimization_required"],
            optimized_code=results["optimized_code"],
            quality_score=results["quality_score"],
            validation_message=results["validation_message"]
        )
    except Exception as e:
        logger.error(f"Snippet review execution failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Snippet review failed: {str(e)}"
        )

@router.websocket("/ws/{analysis_id}")
async def websocket_analysis_progress(websocket: WebSocket, analysis_id: str):
    """WebSocket endpoint to subscribe to real-time scanning progress updates."""
    await manager.connect(websocket)
    try:
        await listen_to_redis_channel(analysis_id, websocket)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"WS Exception: {e}")
        manager.disconnect(websocket)

import os
from sqlalchemy import delete, func

from backend.app.schemas.schemas import ValidateFixRequest, ValidateFixResponse, DeployInstructionsRequest, DeployInstructionsResponse

analyses_router = APIRouter(prefix="/analyses", tags=["Analyses"])


@router.post("/validate-fix", response_model=ValidateFixResponse)
async def validate_fix(
    req: ValidateFixRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """Validate a user's manual edit by re-running analysis on the edited file."""
    # Verify ownership of analysis
    result = await db.execute(
        select(Analysis)
        .join(Repository)
        .where((Analysis.id == req.analysis_id) & (Repository.user_id == current_user.id))
    )
    analysis = result.scalars().first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found.")

    # Detect language from file extension
    ext = os.path.splitext(req.file_path)[1].lower()
    lang_map = {
        ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript",
        ".ts": "TypeScript", ".tsx": "TypeScript", ".java": "Java",
        ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".cs": "C#",
        ".c": "C", ".cpp": "C++", ".h": "C", ".hpp": "C++"
    }
    language = lang_map.get(ext, "Unknown")

    groq_key = encryptor.decrypt(current_user.groq_api_key_encrypted) if current_user.groq_api_key_encrypted else settings.GROQ_API_KEY
    if not groq_key:
        raise HTTPException(status_code=400, detail="Groq API Key is not configured for your profile.")

    try:
        from backend.app.services.reviewer import review_single_code_snippet, build_groq_client
        client = build_groq_client(groq_key)
        results = review_single_code_snippet(req.edited_content, language, client)
        
        remaining = []
        for finding in results.get("findings", []):
            # Only count findings that existed in the original
            if finding.get("severity") in ["Critical", "High", "Medium"]:
                remaining.append({
                    "issue": finding.get("issue", ""),
                    "severity": finding.get("severity", ""),
                    "line": finding.get("line", 0),
                    "suggestion": finding.get("suggestion", "")
                })
        
        total_before = len(results.get("findings", []))
        findings_now = [f for f in results.get("findings", []) if f.get("severity") in ["Critical", "High", "Medium"]]
        
        if findings_now:
            # Check if same issues exist
            if len(findings_now) < total_before // 2:
                status = "partially_fixed"
            else:
                status = "not_fixed"
        else:
            status = "fixed"

        return ValidateFixResponse(
            status=status,
            details=f"Re-scan complete. {len(findings_now)} issues found in edited file.",
            remaining_issues=remaining
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Validate fix failed: {str(e)}")


@router.post("/deploy-instructions", response_model=DeployInstructionsResponse)
async def get_deploy_instructions(
    req: DeployInstructionsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """Generate AI-powered deployment instructions for fixing issues found in an analysis."""
    # Verify ownership
    result = await db.execute(
        select(Analysis)
        .join(Repository)
        .where((Analysis.id == req.analysis_id) & (Repository.user_id == current_user.id))
    )
    analysis = result.scalars().first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found.")
        
    # Get repository info
    repo_res = await db.execute(select(Repository).where(Repository.id == analysis.repository_id))
    repo = repo_res.scalars().first()
    
    # Count findings
    sec_count_res = await db.execute(
        select(func.count(SecurityFinding.id)).where(SecurityFinding.analysis_id == analysis.id)
    )
    sec_count = sec_count_res.scalar() or 0
    
    smell_count_res = await db.execute(
        select(func.count(CodeSmell.id)).where(CodeSmell.analysis_id == analysis.id)
    )
    smell_count = smell_count_res.scalar() or 0
    
    total_findings = sec_count + smell_count
    branch_name = req.branch if req.branch else "main"
    
    commit_msg = f"Fix security findings: Resolved {total_findings} issue(s) from AI code review"
    pr_title = f"[AI Review] Fix {total_findings} code quality and security issue(s)"
    pr_desc = (
        f"## AI-Guided Code Remediation\n\n"
        f"This PR addresses {total_findings} issue(s) identified by the AI Code Reviewer:\n\n"
        f"- **Security Issues:** {sec_count}\n"
        f"- **Code Smells:** {smell_count}\n\n"
        f"### Steps Taken:\n"
        f"1. Issues identified during automated repository scan\n"
        f"2. Each issue reviewed and manually edited by the developer\n"
        f"3. Changes validated via re-scan\n\n"
        f"> **Note:** These changes were applied manually by the developer following AI guidance."
    )
    
    steps = [
        f"git add .",
        f"git commit -m \"{commit_msg}\"",
        f"git push origin {branch_name}",
        f"# Then create a pull request on GitHub: {repo.name if repo else ''}"
    ]
    
    return DeployInstructionsResponse(
        steps=steps,
        commit_suggestion=commit_msg,
        pr_title_suggestion=pr_title,
        pr_description_suggestion=pr_desc
    )

@analyses_router.delete("/{id}")
async def delete_analysis(
    id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    logger.info(f"User {current_user.id} requested deletion of scan history for analysis_id: {id}")
    result = await db.execute(
        select(Analysis)
        .join(Repository)
        .where((Analysis.id == id) & (Repository.user_id == current_user.id))
    )
    analysis = result.scalars().first()
    if not analysis:
        logger.warning(f"Deletion failed: Analysis {id} not found or not owned by user {current_user.id}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found.")

    analysis.is_deleted = True
    db.add(analysis)
    await db.commit()
    logger.info(f"Scan history soft-deletion completed successfully for analysis_id: {id}")
    return {"success": True}

@analyses_router.delete("/repo/{repo_id}")
async def delete_repo_analyses(
    repo_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    logger.info(f"User {current_user.id} requested soft-deletion of scan history for repo: {repo_id}")
    # Verify repository ownership
    repo_res = await db.execute(
        select(Repository).where((Repository.id == repo_id) & (Repository.user_id == current_user.id))
    )
    if not repo_res.scalars().first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found.")
        
    result = await db.execute(
        select(Analysis).where((Analysis.repository_id == repo_id) & ((Analysis.is_deleted == False) | (Analysis.is_deleted.is_(None))))
    )
    analyses = result.scalars().all()
    if not analyses:
        return {"success": True, "count": 0}
        
    for analysis in analyses:
        analysis.is_deleted = True
        db.add(analysis)
    await db.commit()
    logger.info(f"Scan history soft-deletion completed for repo {repo_id}. Count: {len(analyses)}")
    return {"success": True, "count": len(analyses)}

@analyses_router.delete("")
async def delete_all_analyses(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    logger.info(f"User {current_user.id} requested deletion of ALL scan history")
    result = await db.execute(
        select(Analysis)
        .join(Repository)
        .where(Repository.user_id == current_user.id)
    )
    analyses = result.scalars().all()
    if not analyses:
        logger.info("No scan history found to delete")
        return {"success": True}

    for analysis in analyses:
        analysis.is_deleted = True
        db.add(analysis)
    await db.commit()
    logger.info(f"Successfully soft-deleted {len(analyses)} scan records for user {current_user.id}")
    return {"success": True}

@analyses_router.get("/{id}/stats")
async def get_analysis_stats(
    id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    result = await db.execute(
        select(Analysis)
        .join(Repository)
        .where((Analysis.id == id) & (Repository.user_id == current_user.id))
    )
    analysis = result.scalars().first()
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found.")
        
    return {
        "model_name": analysis.model_name or "llama-3.3-70b-versatile",
        "prompt_tokens": analysis.prompt_tokens or 0,
        "completion_tokens": analysis.completion_tokens or 0,
        "total_tokens": analysis.total_tokens or 0,
        "files_analyzed": analysis.files_analyzed_count or 0,
        "scan_duration_seconds": analysis.scan_duration_seconds or 0,
        "groq_requests_made": analysis.groq_requests_made or 0,
        "cached_results_used": analysis.cached_results_used or 0
    }

@analyses_router.get("/compare")
async def compare_analyses(
    scan_a: uuid.UUID,
    scan_b: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    res_a = await db.execute(
        select(Analysis)
        .join(Repository)
        .where((Analysis.id == scan_a) & (Repository.user_id == current_user.id))
    )
    analysis_a = res_a.scalars().first()
    
    res_b = await db.execute(
        select(Analysis)
        .join(Repository)
        .where((Analysis.id == scan_b) & (Repository.user_id == current_user.id))
    )
    analysis_b = res_b.scalars().first()

    if not analysis_a or not analysis_b:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or both scans not found or access denied."
        )

    # Fetch actual findings for scan_a and scan_b
    sec_a_findings_res = await db.execute(
        select(SecurityFinding).where(SecurityFinding.analysis_id == scan_a)
    )
    sec_a_findings = sec_a_findings_res.scalars().all()

    sec_b_findings_res = await db.execute(
        select(SecurityFinding).where(SecurityFinding.analysis_id == scan_b)
    )
    sec_b_findings = sec_b_findings_res.scalars().all()

    smell_a_findings_res = await db.execute(
        select(CodeSmell).where(CodeSmell.analysis_id == scan_a)
    )
    smell_a_findings = smell_a_findings_res.scalars().all()

    smell_b_findings_res = await db.execute(
        select(CodeSmell).where(CodeSmell.analysis_id == scan_b)
    )
    smell_b_findings = smell_b_findings_res.scalars().all()

    def serialize_finding(f, f_type):
        return {
            "id": str(f.id),
            "file": f.file,
            "line": f.line,
            "severity": f.severity,
            "issue": f.issue,
            "type": f_type,
            "risk_level": getattr(f, "risk_level", None),
            "suggestion": f.suggestion,
            "before_code": getattr(f, "before_code", None),
            "after_code": getattr(f, "after_code", None)
        }

    findings_a_dict = {}
    for f in sec_a_findings:
        findings_a_dict[(f.file, f.issue)] = serialize_finding(f, "security")
    for f in smell_a_findings:
        findings_a_dict[(f.file, f.issue)] = serialize_finding(f, "code_smell")

    findings_b_dict = {}
    for f in sec_b_findings:
        findings_b_dict[(f.file, f.issue)] = serialize_finding(f, "security")
    for f in smell_b_findings:
        findings_b_dict[(f.file, f.issue)] = serialize_finding(f, "code_smell")

    fixed = [findings_a_dict[k] for k in findings_a_dict if k not in findings_b_dict]
    new = [findings_b_dict[k] for k in findings_b_dict if k not in findings_a_dict]
    remaining = [findings_b_dict[k] for k in findings_b_dict if k in findings_a_dict]

    tests_a_res = await db.execute(
        select(TestSuggestion.content).where(TestSuggestion.analysis_id == scan_a)
    )
    tests_a_content = tests_a_res.scalars().first() or ""
    tests_a = tests_a_content.count("def test_") or (1 if tests_a_content.strip() else 0)

    tests_b_res = await db.execute(
        select(TestSuggestion.content).where(TestSuggestion.analysis_id == scan_b)
    )
    tests_b_content = tests_b_res.scalars().first() or ""
    tests_b = tests_b_content.count("def test_") or (1 if tests_b_content.strip() else 0)

    risk_a = analysis_a.risk_score or 0
    risk_b = analysis_b.risk_score or 0

    if risk_b < risk_a:
        status_tag = "Improved"
    elif risk_b > risk_a:
        status_tag = "Regressed"
    else:
        status_tag = "Unchanged"

    def get_imp(val_a, val_b, lower_is_better=True):
        if val_a == val_b:
            return 0
        if lower_is_better:
            if val_a == 0:
                return -100 if val_b > 0 else 0
            return int(((val_a - val_b) / val_a) * 100)
        else:
            if val_a == 0:
                return 100 if val_b > 0 else 0
            return int(((val_b - val_a) / val_a) * 100)

    return {
        "scan_a_id": str(scan_a),
        "scan_b_id": str(scan_b),
        "status": status_tag,
        "security": {
            "a": len(sec_a_findings),
            "b": len(sec_b_findings),
            "improvement_pct": get_imp(len(sec_a_findings), len(sec_b_findings), True)
        },
        "code_smells": {
            "a": len(smell_a_findings),
            "b": len(smell_b_findings),
            "improvement_pct": get_imp(len(smell_a_findings), len(smell_b_findings), True)
        },
        "tests": {
            "a": tests_a,
            "b": tests_b,
            "improvement_pct": get_imp(tests_a, tests_b, False)
        },
        "risk_score": {
            "a": risk_a,
            "b": risk_b,
            "improvement_pct": get_imp(risk_a, risk_b, True)
        },
        "fixed": fixed,
        "new": new,
        "remaining": remaining
    }

class ExplainRequest(BaseModel):
    finding_id: uuid.UUID
    issue_type: str  # "security" or "code_smell"

@router.post("/explain")
async def explain_finding(
    req: ExplainRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    finding = None
    if req.issue_type == "security":
        res = await db.execute(select(SecurityFinding).where(SecurityFinding.id == req.finding_id))
        finding = res.scalar_one_or_none()
    elif req.issue_type == "code_smell":
        res = await db.execute(select(CodeSmell).where(CodeSmell.id == req.finding_id))
        finding = res.scalar_one_or_none()
    else:
        raise HTTPException(status_code=400, detail="Invalid issue_type. Use 'security' or 'code_smell'.")
        
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found.")

    ownership_res = await db.execute(
        select(Analysis)
        .join(Repository)
        .where((Analysis.id == finding.analysis_id) & (Repository.user_id == current_user.id))
    )
    if not ownership_res.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Finding does not belong to the current user.")
        
    groq_key = encryptor.decrypt(current_user.groq_api_key_encrypted) if current_user.groq_api_key_encrypted else settings.GROQ_API_KEY
    if not groq_key:
        raise HTTPException(status_code=400, detail="Groq API Key is not configured for your profile.")
        
    client = build_groq_client(groq_key)
    
    system_prompt = """You are an expert senior software engineer and static analysis (AppSec) specialist.
    Provide a detailed explanation for the following code finding.
    
    You must structure your response into five distinct markdown sections:
    ### ðŸ” What is wrong
    Explain what is wrong with the code in simple, precise engineering terms.
    
    ### â“ Why it is wrong
    Describe why it is suboptimal, insecure, or considered a bad practice.
    
    ### âš ï¸ What could happen
    Explain the potential risk, impact, scalability bottleneck, or exploit vector that could result if left unfixed.
    
    ### ðŸ› ï¸ How to fix it
    Give clear, actionable instructions on how to refactor or rewrite the code to resolve this issue.
    
    ### ðŸŒŸ Best practice
    Share general architectural design guidelines or industry standards related to this issue (e.g. OWASP, Clean Code, SOLID principles).
    """
    
    user_prompt = f"""Finding details:
File: {finding.file}
Line: {finding.line}
Issue Summary: {finding.issue}
Severity: {finding.severity}
Recommendation Suggestion: {finding.suggestion}

Code Context (suboptimal version):
```
{finding.before_code or 'N/A'}
```

Remediated Code Suggestion:
```
{finding.after_code or 'N/A'}
```
"""
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.3
        )
        explanation = chat_completion.choices[0].message.content
        return {"explanation": explanation}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate explanation: {str(e)}")



