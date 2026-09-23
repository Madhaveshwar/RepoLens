from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, WebSocketDisconnect, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List
import uuid
import os
import ast
import time
import json
import re
from pydantic import BaseModel

from app.database.database import get_async_db
from app.models.models import (
    User, Repository, PullRequest, Analysis,
    Report, SecurityFinding, CodeSmell, TestSuggestion, HealthScore
)
from app.schemas.schemas import AnalysisTrigger, AnalysisOut, FixFindingRequest, FixFindingResponse
from app.auth.security import get_current_user
from app.tasks.tasks import enqueue_analysis_task
from app.websockets.websocket_manager import manager, listen_to_redis_channel
from app.services.reviewer import review_single_code_snippet
from app.services.llm_client import (
    PROVIDER_FALLBACK_MODELS,
    build_llm_client,
    get_model_name,
    friendly_llm_error,
    is_auth_error,
    is_model_not_found_error,
    is_rate_limit_error,
    create_chat_completion,
)
from app.auth.encryption import encryptor
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger("analysis_router")


def _raise_friendly_llm_error(provider: str, exc: Exception) -> HTTPException:
    """Wrap any LLM provider exception into a clear, user-facing HTTP error."""
    logger.error(f"LLM request failed (provider={provider}): {exc}", exc_info=True)
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=friendly_llm_error(provider, exc),
    )

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
        from app.services.github_service import GitHubService
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
    
    logger.info(f"Created analysis record with id: {new_analysis.id}. Queueing analysis task.")
    try:
        enqueue_analysis_task(background_tasks, str(new_analysis.id))
    except Exception as exc:
        logger.error(f"Failed to enqueue analysis task {new_analysis.id}: {exc}", exc_info=True)
        new_analysis.status = "failed"
        new_analysis.progress = 100
        new_analysis.insights = f"Failed to queue analysis task: {exc}"
        db.add(new_analysis)
        await db.commit()
        await db.refresh(new_analysis)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Analysis worker queue is unavailable: {str(exc)}"
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
    
    # Fetch associated health score from HealthScore table for data consistency
    health_res = await db.execute(
        select(HealthScore).where(HealthScore.analysis_id == id)
    )
    health_obj = health_res.scalars().first()
    if health_obj:
        analysis.health_score = health_obj.health_score
    
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
    analyses = list(result.scalars().all())
    
    # Fetch health scores for all analyses in a single query
    if analyses:
        analysis_ids = [a.id for a in analyses]
        health_res = await db.execute(
            select(HealthScore).where(HealthScore.analysis_id.in_(analysis_ids))
        )
        health_scores = health_res.scalars().all()
        health_map = {hs.analysis_id: hs.health_score for hs in health_scores}
        for a in analyses:
            if a.id in health_map:
                a.health_score = health_map[a.id]
    
    return analyses

def _resolve_llm_key(current_user: User) -> tuple[str, str]:
    """Resolve provider and API key for a user, falling back to env vars."""
    from app.auth.encryption import encryptor as _enc
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
    if not llm_api_key:
        provider = "groq"
        groq_enc = current_user.groq_api_key_encrypted
        llm_api_key = _enc.decrypt(groq_enc) if groq_enc else settings.GROQ_API_KEY
    return provider, llm_api_key


def validate_fix_syntax(code: str, file_path: str) -> tuple[bool, str]:
    """Validate that generated fix code is syntactically correct.
    Returns (is_valid, error_message)."""
    ext = os.path.splitext(file_path)[1].lower()

    # Python syntax check
    if ext in ('.py', ''):
        try:
            ast.parse(code)
            return True, "Syntax OK"
        except SyntaxError as e:
            return False, f"Python syntax error at line {e.lineno}: {e.msg}"

    # JavaScript/TypeScript basic check - balanced braces
    if ext in ('.js', '.ts', '.jsx', '.tsx'):
        brace_count = code.count('{') - code.count('}')
        paren_count = code.count('(') - code.count(')')
        if brace_count != 0:
            return False, f"Unbalanced braces: {brace_count} unmatched '{{' or '}}'"
        if paren_count != 0:
            return False, f"Unbalanced parentheses: {paren_count} unmatched '()' or ')'"
        return True, "Syntax OK (brace/paren balance)"

    # For other languages, do a basic sanity check
    if not code.strip():
        return False, "Empty code"

    return True, "Syntax OK (basic check)"


def validate_fix_imports(code: str) -> tuple[bool, str]:
    """Validate that imports in generated fix are valid Python.
    Returns (is_valid, warning_message)."""
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if not alias.name or not alias.name.replace('_', '').replace('.', '').isalnum():
                        return False, f"Suspicious import: {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                if node.module and not node.module.replace('_', '').replace('.', '').isalnum():
                    return False, f"Suspicious from-import: {node.module}"
        return True, "Imports OK"
    except SyntaxError:
        return True, "Cannot validate imports (syntax error)"


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

from app.schemas.schemas import ValidateFixRequest, ValidateFixResponse, ValidateFixCodeRequest, ValidateFixCodeResponse, RescanVerifyRequest, RescanVerifyResponse

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

    provider, llm_api_key = _resolve_llm_key(current_user)
    if not llm_api_key:
        raise HTTPException(
            status_code=400,
            detail="No LLM API Key is configured for your profile. Add one in Settings."
        )

    try:
        from app.services.reviewer import review_single_code_snippet
        from app.services.llm_client import build_llm_client
        client = build_llm_client(provider, llm_api_key)
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


@router.post("/validate-fix-code", response_model=ValidateFixCodeResponse)
async def validate_fix_code(
    req: ValidateFixCodeRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Validate generated fix code for syntax errors and import issues.
    This is a fast static check (no LLM call).
    """
    syntax_ok, syntax_error = validate_fix_syntax(req.code, req.file_path)
    imports_ok, imports_error = validate_fix_imports(req.code)
    
    overall_valid = syntax_ok and imports_ok
    
    return ValidateFixCodeResponse(
        syntax_ok=syntax_ok,
        syntax_error=syntax_error if not syntax_ok else "",
        imports_ok=imports_ok,
        imports_error=imports_error if not imports_ok else "",
        overall_valid=overall_valid
    )


@router.post("/compare-and-resolve", response_model=RescanVerifyResponse)
async def compare_and_resolve(
    req: RescanVerifyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Compare two analyses (original scan vs rescan) and optionally mark resolved findings.
    This is used after fixes are applied to verify which findings were resolved.
    """
    # Verify ownership of both analyses
    res_a = await db.execute(
        select(Analysis)
        .join(Repository)
        .where((Analysis.id == req.original_analysis_id) & (Repository.user_id == current_user.id))
    )
    analysis_a = res_a.scalars().first()
    
    res_b = await db.execute(
        select(Analysis)
        .join(Repository)
        .where((Analysis.id == req.rescan_analysis_id) & (Repository.user_id == current_user.id))
    )
    analysis_b = res_b.scalars().first()

    if not analysis_a or not analysis_b:
        raise HTTPException(status_code=404, detail="One or both scans not found or access denied.")

    # Fetch findings for both scans
    sec_a = (await db.execute(select(SecurityFinding).where(SecurityFinding.analysis_id == req.original_analysis_id))).scalars().all()
    sec_b = (await db.execute(select(SecurityFinding).where(SecurityFinding.analysis_id == req.rescan_analysis_id))).scalars().all()
    smell_a = (await db.execute(select(CodeSmell).where(CodeSmell.analysis_id == req.original_analysis_id))).scalars().all()
    smell_b = (await db.execute(select(CodeSmell).where(CodeSmell.analysis_id == req.rescan_analysis_id))).scalars().all()

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
        }

    # Build lookup dicts by (file, issue)
    a_dict = {}
    for f in sec_a:
        a_dict[(f.file, f.issue)] = serialize_finding(f, "security")
    for f in smell_a:
        a_dict[(f.file, f.issue)] = serialize_finding(f, "code_smell")

    b_dict = {}
    for f in sec_b:
        b_dict[(f.file, f.issue)] = serialize_finding(f, "security")
    for f in smell_b:
        b_dict[(f.file, f.issue)] = serialize_finding(f, "code_smell")

    fixed = [a_dict[k] for k in a_dict if k not in b_dict]
    new = [b_dict[k] for k in b_dict if k not in a_dict]
    remaining = [b_dict[k] for k in b_dict if k in a_dict]

    risk_a = analysis_a.risk_score or 0
    risk_b = analysis_b.risk_score or 0

    if risk_b < risk_a:
        status = "improved"
    elif risk_b > risk_a:
        status = "regressed"
    else:
        status = "no_change"

    # Optionally mark resolved findings by soft-deleting from original analysis
    resolved_count = 0
    if req.mark_resolved and fixed:
        for f in sec_a:
            key = (f.file, f.issue)
            if key not in b_dict:
                # Delete the finding so it no longer appears in queries
                await db.delete(f)
                resolved_count += 1
        for f in smell_a:
            key = (f.file, f.issue)
            if key not in b_dict:
                await db.delete(f)
                resolved_count += 1
        await db.commit()
        logger.info(f"Resolved {resolved_count} findings from original scan {req.original_analysis_id}")

    return RescanVerifyResponse(
        original_analysis_id=str(req.original_analysis_id),
        rescan_analysis_id=str(req.rescan_analysis_id),
        status=status,
        fixed_findings=fixed,
        remaining_findings=remaining,
        new_findings=new,
        risk_score_before=risk_a,
        risk_score_after=risk_b,
        resolved_count=resolved_count,
        unresolved_count=len(remaining)
    )


# [REMOVED] apply-fix endpoint — this project does not modify repositories


# [REMOVED] deploy-instructions endpoint — this project does not modify repositories

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
        "model_name": analysis.model_name or "openai/gpt-oss-120b",
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

@router.post("/fix-finding", response_model=FixFindingResponse)
async def fix_finding(
    req: FixFindingRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Generate an AI-powered code fix for a specific finding.
    Validates ownership, then uses finding details and file content to produce a targeted fix.
    """
    start = time.time()
    logger.info(f"User {current_user.id} requested AI fix for finding: {req.finding_type}/{req.issue[:60]}")

    # ── Ownership validation ────────────────────────────────────────
    # Verify the finding belongs to an analysis owned by the current user
    finding_record = None
    try:
        finding_uuid = uuid.UUID(req.finding_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid finding ID format.")
    if req.finding_type == "security":
        res = await db.execute(
            select(SecurityFinding).where(SecurityFinding.id == finding_uuid)
        )
        finding_record = res.scalar_one_or_none()
    elif req.finding_type == "code_smell":
        res = await db.execute(
            select(CodeSmell).where(CodeSmell.id == finding_uuid)
        )
        finding_record = res.scalar_one_or_none()

    if finding_record is not None:
        ownership_res = await db.execute(
            select(Analysis)
            .join(Repository)
            .where((Analysis.id == finding_record.analysis_id) & (Repository.user_id == current_user.id))
        )
        if not ownership_res.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="Finding does not belong to the current user.")

    provider, llm_api_key = _resolve_llm_key(current_user)
    if not llm_api_key:
        raise HTTPException(
            status_code=400,
            detail="No LLM API Key is configured for your profile. Add one in Settings."
        )

    from app.utils.prompts import SYSTEM_GENERATE_FIX_PROMPT

    user_prompt = f"""Generate a precise fix for the following code finding.

Finding Type: {req.finding_type}
Severity: {req.severity}
Issue: {req.issue}
Suggestion: {req.suggestion or 'N/A'}

Original/Snippet (before fix):
```
{req.before_code or req.after_code or 'N/A'}
```

Full file path: {req.file_path}

Full file content:
```
{req.file_content}
```

Generate the exact code change needed to fix this issue.
"""

    try:
        client = build_llm_client(provider, llm_api_key)
        model = get_model_name(provider, current_user.llm_default_model)

        chat_completion = create_chat_completion(
            client=client,
            provider=provider,
            messages=[
                {"role": "system", "content": SYSTEM_GENERATE_FIX_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            model=model,
            temperature=0.2,
        )
        result_text = chat_completion.choices[0].message.content

        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", result_text)
        if json_match:
            result_text = json_match.group(1).strip()
        try:
            result_data = json.loads(result_text)
        except json.JSONDecodeError:
            object_match = re.search(r"\{[\s\S]*\}", result_text)
            if object_match:
                try:
                    result_data = json.loads(object_match.group(0))
                except json.JSONDecodeError:
                    result_data = {"explanation": result_text, "fixed_code_snippet": "", "fixed_full_file": ""}
            else:
                result_data = {"explanation": result_text, "fixed_code_snippet": "", "fixed_full_file": ""}

        # ── Fallback: resolve alternative field names the LLM might return ──
        has_fixed_code = bool(result_data.get("fixed_code_snippet"))
        has_fixed_full = bool(result_data.get("fixed_full_file"))

        if not has_fixed_code and not has_fixed_full:
            logger.info(f"LLM response missing fixed_code_snippet/fixed_full_file. Keys: {list(result_data.keys())}")
            for alt_key in ["fix", "code", "patched_code", "fixed_code", "replacement_code", "patched", "replacement", "fixed", "patch", "fixed_code_snippet"]:
                alt_val = result_data.get(alt_key)
                if alt_val and isinstance(alt_val, str) and alt_val.strip():
                    logger.info(f"LLM returned fix under alternative field '{alt_key}' (len={len(alt_val)})")
                    result_data["fixed_code_snippet"] = alt_val
                    has_fixed_code = True
                    break

        if not has_fixed_code and not has_fixed_full:
            # Try extracting code from a fenced code block inside the explanation or raw text
            expl = result_data.get("explanation", "") or result_text
            # First try: ```language\n...``` pattern (actual newlines)
            cb_match = re.search(r"```(?:\w+)?\n(.+?)```", expl, re.DOTALL)
            if cb_match:
                extracted = cb_match.group(1).strip()
                if extracted:
                    logger.info(f"Extracted fix code from explanation code block (len={len(extracted)})")
                    result_data["fixed_code_snippet"] = extracted
                    has_fixed_code = True
            if not has_fixed_code:
                # Second try: look for any code block in the raw response
                cb_match = re.search(r"```(?:\w+)?\n(.+?)```", result_text, re.DOTALL)
                if cb_match:
                    extracted = cb_match.group(1).strip()
                    if extracted:
                        logger.info(f"Extracted fix code from raw response code block (len={len(extracted)})")
                        result_data["fixed_code_snippet"] = extracted
                        has_fixed_code = True

        latency = round(time.time() - start, 2)
        logger.info(f"Fix generated in {latency}s for {req.finding_type} finding | "
                     f"has_fixed_code={has_fixed_code} | "
                     f"has_fixed_full={has_fixed_full} | "
                     f"has_explanation={bool(result_data.get('explanation'))} | "
                     f"llm_keys={list(result_data.keys())}")
        return FixFindingResponse(
            fix_type=result_data.get("fix_type", req.finding_type),
            original_code_snippet=result_data.get("original_code_snippet", ""),
            fixed_code_snippet=result_data.get("fixed_code_snippet", ""),
            fixed_full_file=result_data.get("fixed_full_file", ""),
            explanation=result_data.get("explanation", "Fix generated."),
            start_line=result_data.get("start_line", 1),
            end_line=result_data.get("end_line", 1),
            latency_seconds=latency
        )
    except HTTPException:
        raise
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Fix finding failed: {e}", exc_info=True)
        raise _raise_friendly_llm_error(provider, e)


# [REMOVED] _generate_single_fix — helper was only used by the removed fix-all endpoint
# This project does not modify repositories


# [REMOVED] fix-all endpoint — this project does not modify repositories


# [REMOVED] fix-all-and-pr endpoint — this project does not modify repositories


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
        
    provider, llm_api_key = _resolve_llm_key(current_user)
    if not llm_api_key:
        raise HTTPException(
            status_code=400,
            detail="No LLM API Key is configured for your profile. Add one in Settings."
        )

    client = build_llm_client(provider, llm_api_key)
    model = get_model_name(provider, current_user.llm_default_model)

    system_prompt = """You are an expert senior software engineer and static analysis (AppSec) specialist.
    Explain the ONE specific code finding given below. Stay strictly grounded in the evidence provided.

    MANDATORY structure (markdown headings, exactly these five):

    ## What is the issue?
    Simple, precise explanation of the detected problem.

    ## Why was it detected?
    Point at what in the ACTUAL code caused the finding (quote the relevant line/snippet).

    ## What could happen?
    ONLY realistic consequences supported by this finding and this code. If a consequence
    depends on backend behaviour, caller behaviour, or configuration that is NOT shown in
    the provided context, explicitly say: "This depends on the backend implementation,
    which is not visible in the provided context."

    ## How to fix it
    A practical fix for THIS code (reference the actual file/line).

    ## Example
    A short before/after code example when useful; otherwise a one-line note saying the fix
    is fully described above.

    HARD RULES:
    - Do NOT claim the issue is definitely exploitable; the scanner identified a possible risk.
    - Do NOT assume command injection, SQL injection, path traversal, or file disclosure
      unless the shown code actually demonstrates it.
    - Do NOT invent backend behaviour, APIs, routes, or application features.
    - Do NOT mention security tools or scanners that were not used.
    - Keep it concise (under 300 words) and specific to this finding.
    """
    
    user_prompt = f"""Finding details (the ONLY evidence you may use):
File: {finding.file}
Line: {finding.line}
Issue Summary: {finding.issue}
Severity: {finding.severity}
Recommendation Suggestion: {finding.suggestion}

Code Context (suboptimal version):
```
{finding.before_code or '(not captured by the scanner)'}
```

Remediated Code Suggestion:
```
{finding.after_code or '(not captured by the scanner)'}
```

If the code context above is '(not captured by the scanner)', base the explanation on the
issue summary and suggestion only, and say so explicitly instead of guessing about the code.
"""
    try:
        chat_completion = create_chat_completion(
            client=client,
            provider=provider,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            model=model,
            temperature=current_user.llm_temperature or 0.3,
        )
        explanation = chat_completion.choices[0].message.content
        return {"explanation": explanation}
    except Exception as e:
        raise _raise_friendly_llm_error(provider, e)



