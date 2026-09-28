import os
import time
import threading
from celery import Celery
import redis
import json
import traceback
from datetime import datetime, timezone

from app.config import settings
from app.database.database import SessionLocal
from app.models.models import (
    Analysis, Repository, PullRequest, User,
    SecurityFinding, CodeSmell, TestSuggestion, HealthScore, Report
)
from app.auth.encryption import encryptor
from app.services.github_service import GitHubService
from app.services.reviewer import review_pull_request, review_entire_repository
from app.services.llm_client import build_llm_client, get_model_name, build_groq_client, friendly_llm_error
from app.services.report_generator import (
    generate_markdown_report, generate_json_report, generate_csv_report, generate_pdf_report
)
from app.services.insights_orchestrator import run_all_insights
from app.utils.logger import get_logger

logger = get_logger("celery_worker")

# ── Progress DB-write throttle ────────────────────────────────────
# Redis publish happens on EVERY progress event (cheap), but the DB commit is
# throttled to at most one write per second per analysis (terminal events
# always commit). Previously every progress tick was a full DB commit.
PROGRESS_DB_COMMIT_INTERVAL = 1.0
_last_progress_commit: dict = {}

# ──────────────────────────────────────────────────────────────────
#  REDIS & CELERY INITIALIZATION  (graceful fallback)
#  If Redis is unavailable (e.g. no Redis service configured on
#  Render), the web server should still start without crashing.
#  Celery features will be disabled until Redis becomes available.
# ──────────────────────────────────────────────────────────────────
celery_app = None
redis_client = None

def _init_celery_and_redis():
    """Initialize Celery app and Redis client. Safe to call multiple times."""
    global celery_app, redis_client
    if celery_app is not None:
        return  # already initialized
    try:
        _celery = Celery(
            "tasks",
            broker=settings.REDIS_URL,
            backend=settings.REDIS_URL
        )
        _celery.conf.update(
            broker_connection_retry_on_startup=True,
            task_serializer="json",
            result_serializer="json",
            accept_content=["json"],
            timezone="UTC",
            enable_utc=True,
            task_routes={
                "app.tasks.tasks.run_analysis_task": {"queue": "celery"},
                "dead_letter": {"queue": "dead_letter"}
            }
        )
        _redis = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=2, socket_connect_timeout=2)
        _redis.ping()  # verify connection
        celery_app = _celery
        redis_client = _redis
        logger.info(f"Celery and Redis initialized successfully: {settings.REDIS_URL}")
    except Exception as exc:
        logger.warning(f"Redis not available at {settings.REDIS_URL}. Celery/WebSocket features disabled: {exc}")
        celery_app = None
        redis_client = None

# Attempt initialization at import time; failure is non-fatal
_init_celery_and_redis()


def update_progress(
    analysis_id: str,
    progress: int,
    status_message: str,
    status: str = "scanning",
    files_analyzed: int = 0,
    total_files: int = 0,
    current_file: str = "",
    db=None
):
    """Update analysis progress in DB and publish to Redis for WebSocket streaming.

    When `db` is provided (recommended), uses the caller's session so that
    the main Celery task and progress updates share a single session, avoiding
    StaleDataError from concurrent session writes.
    When `db` is None, creates and closes its own session (legacy mode).
    """
    import uuid as std_uuid
    analysis_id = std_uuid.UUID(analysis_id) if isinstance(analysis_id, str) else analysis_id

    should_close_db = False
    local_db = None
    session = db

    if session is None:
        local_db = SessionLocal()
        session = local_db
        should_close_db = True

    now_s = time.time()
    is_terminal = progress >= 100
    should_write = (
        is_terminal
        or (now_s - _last_progress_commit.get(analysis_id, 0.0)) >= PROGRESS_DB_COMMIT_INTERVAL
    )
    try:
        if should_write:
            analysis = session.query(Analysis).filter(Analysis.id == analysis_id).first()
            if analysis:
                analysis.progress = progress
                if files_analyzed > analysis.files_analyzed_count:
                    analysis.files_analyzed_count = files_analyzed
                if progress >= 100:
                    if "failed" in status_message.lower():
                        analysis.status = "failed"
                    else:
                        analysis.status = "completed"
                else:
                    analysis.status = status
                # Persist real progress details so polling clients (which read
                # the DB) see the same truth Redis subscribers see. previously
                # these columns did not exist, so the UI showed "Files Scanned:
                # 0" / generic stage names even while files were being analyzed.
                # total_files_count is never lowered — terminal events don't
                # reset the file totals discovered mid-scan.
                if total_files > (analysis.total_files_count or 0):
                    analysis.total_files_count = total_files
                analysis.status_message = str(status_message or "")[:500]
                analysis.current_file = str(current_file or "")[:300]
                session.commit()
            _last_progress_commit[analysis_id] = now_s
    finally:
        if should_close_db and local_db is not None:
            local_db.close()

    # Publish to Redis channel (always, regardless of which session was used)
    publish_status = "completed" if progress >= 100 and "failed" not in status_message.lower() else ("failed" if "failed" in status_message.lower() else status)
    payload = {
        "progress": progress,
        "status": publish_status,
        "message": status_message,
        "files_analyzed": files_analyzed,
        "total_files": total_files,
        "current_file": current_file
    }
    try:
        redis_client.publish(
            f"analysis_progress_{analysis_id}",
            json.dumps(payload)
        )
    except Exception as exc:
        logger.warning(f"Redis progress publish failed for analysis {analysis_id}: {exc}")

# ── Celery task registration ────────────────────────────────────
# The task function is always defined. If Celery is available (Redis
# configured), it is registered as a Celery task and gets .delay().
# If Celery is unavailable, a .delay() stub is attached so importing
# routers never crash on startup.

if celery_app is not None:
    # Register as a proper Celery task.
    # PERF FIX: NO autoretry. The previous autoretry_for=(Exception,) with
    # backoff re-ran the ENTIRE scan (clone, fetch, analysis, LLM) up to 3
    # more times on any transient error — the main cause of 5–15 minute
    # scans. A failed scan must fail once, quickly, with a clear message;
    # the user can retry manually if needed.
    @celery_app.task(bind=True, max_retries=0)
    def run_analysis_task(self, analysis_id: str):
        return _run_analysis_impl(self, analysis_id)
else:
    # Celery unavailable ─ define a plain sync function with .delay() stub
    def run_analysis_task(self=None, analysis_id: str = None):
        # Support both calling conventions:
        #   run_analysis_task(analysis_id="some-id")  ← keyword arg (preferred)
        #   run_analysis_task("some-id")               ← positional arg (used by tests)
        if self is not None and analysis_id is None:
            # First positional arg is actually the analysis_id
            analysis_id = self
            self = None
        if not analysis_id:
            raise ValueError("analysis_id is required")
        return _run_analysis_impl(self, analysis_id)
    # Attach .delay() so callers (routers) don't break
    run_analysis_task.delay = lambda analysis_id=None: run_analysis_task(analysis_id=analysis_id)


# Bump when the scan pipeline/prompts change in a way that should invalidate
# previously stored results (same commit + same version ⇒ reuse stored result).
ANALYSIS_VERSION = "v4-fast-scan"

# ── Duplicate-scan guard ─────────────────────────────────────────
# Prevents two workers from running the SAME expensive scan (same repository +
# same commit) concurrently. The second request attaches to the first instead
# of repeating clone/fetch/analysis/LLM work.
_active_scan_locks = threading.Lock()
_active_scans: set = set()


def build_scan_cache_key(repository_id, commit_sha: str, provider: str, model_name: str) -> str:
    import hashlib
    raw = f"{repository_id}|{commit_sha}|{ANALYSIS_VERSION}|{provider}|{model_name}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _store_result_cache(db, repo, commit_sha, provider: str, model_name: str, results: dict):
    """Persist a completed full-scan result for deterministic future reuse.

    Stored in PostgreSQL (analysis_result_cache) — the durable source of truth
    that survives Render restarts/redeploys, unlike the local JSON cache.
    """
    from app.models.models import AnalysisResultCache
    if not commit_sha:
        logger.warning("Result cache store skipped: no commit SHA resolved for this scan.")
        return
    cache_key = build_scan_cache_key(repo.id, commit_sha, provider, model_name)
    existing = db.query(AnalysisResultCache).filter(AnalysisResultCache.cache_key == cache_key).first()
    if existing:
        return  # already stored
    db.add(AnalysisResultCache(
        repository_id=repo.id,
        commit_sha=commit_sha,
        analysis_version=ANALYSIS_VERSION,
        cache_key=cache_key,
        provider=provider,
        model_name=model_name,
        result_json=results,
        hit_count=0,
    ))
    db.commit()
    logger.info(f"Result cache stored for commit {commit_sha[:8]} (provider={provider}, model={model_name}).")


def _materialize_cached_result(db, analysis, payload: dict, provider: str, model_name: str):
    """Create a completed Analysis from a stored (cached) scan result.

    Rebuilds persisted findings, health score, test suggestions and metrics
    from the stored payload WITHOUT calling the LLM.
    """
    import uuid as std_uuid
    analysis_id = analysis.id
    results = payload

    analysis.risk_score = results.get("risk_score", 0)
    analysis.latency_seconds = int(results.get("latency_seconds", 0) or 0)
    analysis.estimated_token_usage = results.get("estimated_token_usage", 0)
    analysis.files_analyzed_count = results.get("files_analyzed_count", 0)
    analysis.characters_analyzed_count = results.get("characters_analyzed_count", 0)
    analysis.groq_requests_made = 0  # no LLM calls were made
    analysis.cached_results_used = results.get("cached_results_used", 0) or 1
    analysis.model_name = (results.get("token_stats") or {}).get("model_name") or model_name
    analysis.analysis_version = ANALYSIS_VERSION
    if results.get("head_sha"):
        analysis.commit_sha = results.get("head_sha")
    if results.get("branch"):
        analysis.branch = results.get("branch")

    t_stats = results.get("token_stats") or {}
    analysis.prompt_tokens = t_stats.get("prompt_tokens") or 0
    analysis.completion_tokens = t_stats.get("completion_tokens") or 0
    analysis.total_tokens = t_stats.get("total_tokens") or 0
    analysis.timestamp = datetime.now(timezone.utc)

    persisted_findings = sorted(
        results.get("findings", []),
        key=lambda f: (str(f.get("file", "")), int(f.get("line", 0) or 0), str(f.get("issue", "")))
    )
    for f in persisted_findings:
        if f.get("category") == "Security":
            db.add(SecurityFinding(
                analysis_id=analysis_id,
                file=f.get("file"), line=f.get("line"), severity=f.get("severity"),
                issue=f.get("issue"), why_it_matters=f.get("why_it_matters"),
                risk_level=f.get("risk_level"), suggestion=f.get("suggestion"),
                before_code=f.get("before_code"), after_code=f.get("after_code"),
                start_line=f.get("start_line", f.get("line")),
                end_line=f.get("end_line", f.get("line")),
                code_snippet=f.get("before_code"),
                issue_explanation=f.get("why_it_matters"),
                source=f.get("source"),
            ))
        elif f.get("category") == "Code Smell":
            db.add(CodeSmell(
                analysis_id=analysis_id,
                file=f.get("file"), line=f.get("line"), severity=f.get("severity"),
                issue=f.get("issue"), why_it_matters=f.get("why_it_matters"),
                risk_level=f.get("risk_level"), suggestion=f.get("suggestion"),
                before_code=f.get("before_code"), after_code=f.get("after_code"),
                start_line=f.get("start_line", f.get("line")),
                end_line=f.get("end_line", f.get("line")),
                code_snippet=f.get("before_code"),
                issue_explanation=f.get("why_it_matters"),
                source=f.get("source"),
            ))

    test_suggs = results.get("test_suggestions", "")
    if test_suggs:
        db.add(TestSuggestion(analysis_id=analysis_id, file="combined_suggestions", content=test_suggs))

    repo_an = results.get("repo_analysis")
    if repo_an:
        db.add(HealthScore(
            analysis_id=analysis_id,
            health_score=repo_an.get("health_score", 100),
            deductions=repo_an.get("deductions", []),
            readme_exists=repo_an.get("readme_exists", False),
            large_files=repo_an.get("large_files", []),
            security_hotspots=repo_an.get("security_hotspots", []),
            missing_tests=repo_an.get("missing_tests", []),
            test_files_count=repo_an.get("test_files_count", 0),
            source_files_count=repo_an.get("source_files_count", 0),
            docstring_coverage=repo_an.get("docstring_coverage", 0),
        ))
        analysis.insights = repo_an.get("analysis_report")
    else:
        analysis.insights = "Stored analysis for this exact commit was reused (no LLM calls were made)."

    db.commit()
    logger.info(f"Materialized cached analysis {analysis_id} from stored result (commit {analysis.commit_sha}).")


def _persist_precomputed_insights(db, analysis_id, repo, precomputed: dict, commit_sha: str | None) -> dict:
    """Persist pre-computed insight results from the fast scan pipeline.

    The fast_scan_pipeline already ran dependency, duplicate, complexity,
    architecture, and technical debt analyses in parallel. This function
    writes those results directly to the DB instead of re-running them
    through the insights_orchestrator (which would fetch files again and
    repeat all the analysis).

    Returns a dict of per-insight status info (same format as run_all_insights).
    """
    import uuid as std_uuid
    from app.models.models import (
        DependencyFinding, DuplicateCodeFinding, TechnicalDebtFinding,
        ArchitectureAnalysis, ComplexityFinding, SecurityFinding, CodeSmell,
    )
    from app.services.technical_debt_analyzer import build_technical_debt_report
    from app.services.insights_orchestrator import persist_health_snapshot

    status: dict = {}

    # ── 1. Dependencies ────────────────────────────────────────────
    try:
        dep_result = precomputed.get("dependency_result", {})
        dep_findings = dep_result.get("findings", [])
        for f in dep_findings:
            db.add(DependencyFinding(
                analysis_id=analysis_id,
                ecosystem=f.get("ecosystem", "unknown"),
                manifest_file=f.get("manifest_file", ""),
                package_name=f.get("package_name", ""),
                version_spec=f.get("version_spec"),
                resolved_version=f.get("resolved_version"),
                status=f.get("status", "unknown"),
                severity=f.get("severity"),
                advisory_id=f.get("advisory_id"),
                vulnerable_range=f.get("vulnerable_range"),
                recommended_version=f.get("recommended_version"),
                advisory_url=f.get("advisory_url"),
                evidence=f.get("evidence"),
            ))
        db.commit()
        dep_summary = dep_result.get("summary", {})
        status["dependencies"] = {
            "ok": True,
            "total": dep_summary.get("total", len(dep_findings)),
            "vulnerable": dep_summary.get("known_vulnerable", 0),
            "manifests": len(dep_result.get("manifests_scanned", [])),
        }
    except Exception as exc:
        logger.error(f"Precomputed dependency persist failed (non-fatal): {exc}", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        status["dependencies"] = {"ok": False, "error": str(exc)[:200]}

    # ── 2. Duplicates ──────────────────────────────────────────────
    try:
        dup_result = precomputed.get("duplicate_result", {})
        dup_findings = dup_result.get("findings", [])
        for d in dup_findings:
            db.add(DuplicateCodeFinding(
                analysis_id=analysis_id,
                file_a=d.get("file_a", ""), start_line_a=d.get("start_line_a", 0),
                end_line_a=d.get("end_line_a", 0),
                file_b=d.get("file_b", ""), start_line_b=d.get("start_line_b", 0),
                end_line_b=d.get("end_line_b", 0),
                similarity=d.get("similarity", 0), duplicated_lines=d.get("duplicated_lines", 0),
                token_hash=d.get("token_hash", ""), snippet=d.get("snippet", ""),
            ))
        db.commit()
        status["duplicates"] = {
            "ok": True, "count": len(dup_findings),
            "files_analyzed": dup_result.get("files_analyzed", 0),
        }
    except Exception as exc:
        logger.error(f"Precomputed duplicate persist failed (non-fatal): {exc}", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        status["duplicates"] = {"ok": False, "error": str(exc)[:200]}

    # ── 3. Complexity ──────────────────────────────────────────────
    try:
        cx_result = precomputed.get("complexity_result", {})
        cx_findings = cx_result.get("findings", [])
        for c in cx_findings:
            db.add(ComplexityFinding(
                analysis_id=analysis_id,
                file=c.get("file", ""), name=c.get("name", ""), kind=c.get("kind", "function"),
                line_start=c.get("line_start", 0), line_end=c.get("line_end"),
                cyclomatic_complexity=c.get("cyclomatic_complexity", 0),
                nesting_depth=c.get("nesting_depth"),
                length_lines=c.get("length_lines"),
                language=c.get("language"),
                severity=c.get("severity", "Info"),
                explanation=c.get("explanation"),
                suggestion=c.get("suggestion"),
            ))
        db.commit()
        cx_summary = cx_result.get("summary", {})
        status["complexity"] = {"ok": True, "reported": cx_summary.get("reported", len(cx_findings))}
    except Exception as exc:
        logger.error(f"Precomputed complexity persist failed (non-fatal): {exc}", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        status["complexity"] = {"ok": False, "error": str(exc)[:200]}

    # ── 4. Architecture ────────────────────────────────────────────
    try:
        arch_result = precomputed.get("architecture_result", {})
        if arch_result:
            db.add(ArchitectureAnalysis(analysis_id=analysis_id, result=arch_result))
            db.commit()
        status["architecture"] = {
            "ok": True,
            "frameworks": len(arch_result.get("frameworks", [])),
            "concerns": len(arch_result.get("concerns", [])),
        }
    except Exception as exc:
        logger.error(f"Precomputed architecture persist failed (non-fatal): {exc}", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        status["architecture"] = {"ok": False, "error": str(exc)[:200]}

    # ── 5. Technical debt ──────────────────────────────────────────
    try:
        # PERF: the debt report may already have been computed during the fresh
        # scan and stored in the cache payload — reuse it instead of rebuilding.
        debt_result = precomputed.get("technical_debt_result")
        if not debt_result:
            sec_rows = db.query(SecurityFinding).filter(SecurityFinding.analysis_id == analysis_id).all()
            smell_rows = db.query(CodeSmell).filter(CodeSmell.analysis_id == analysis_id).all()
            sec_dicts = [{"severity": s.severity, "issue": s.issue, "file": s.file, "line": s.line} for s in sec_rows]
            smell_dicts = [{"severity": s.severity, "issue": s.issue, "file": s.file, "line": s.line} for s in smell_rows]

            dup_result_for_debt = precomputed.get("duplicate_result", {"findings": [], "parameters": {}})
            cx_result_for_debt = precomputed.get("complexity_result", {"findings": [], "summary": {}})
            dep_result_for_debt = precomputed.get("dependency_result", {})
            source_files = precomputed.get("source_files", [])

            debt_result = build_technical_debt_report(
                security_findings=sec_dicts,
                code_smells=smell_dicts,
                duplicates=dup_result_for_debt,
                complexity=cx_result_for_debt,
                source_files=source_files,
                dependencies=dep_result_for_debt,
            )
            # Store the built report back into the precomputed dict so the
            # caller can persist it in the result cache (cache hits then skip
            # the rebuild entirely and no file contents need to be cached).
            try:
                precomputed["technical_debt_result"] = debt_result
            except Exception:
                pass
        for item in debt_result.get("items", []):
            db.add(TechnicalDebtFinding(
                analysis_id=analysis_id,
                category=item["category"],
                severity=item["severity"],
                title=item["title"],
                evidence=item["evidence"],
                file=item.get("file"),
                line_start=item.get("line_start"),
                line_end=item.get("line_end"),
                estimated_effort_hours=item.get("estimated_effort_hours"),
                remediation=item.get("remediation"),
            ))
        db.commit()
        status["technical_debt"] = {"ok": True, "items": len(debt_result.get("items", []))}
    except Exception as exc:
        logger.error(f"Precomputed technical debt persist failed (non-fatal): {exc}", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        status["technical_debt"] = {"ok": False, "error": str(exc)[:200]}

    # ── 6. Health snapshot ─────────────────────────────────────────
    try:
        persist_health_snapshot(db, analysis_id, repo.id, commit_sha)
        status["health_snapshot"] = {"ok": True}
    except Exception as exc:
        logger.error(f"Precomputed health snapshot failed (non-fatal): {exc}", exc_info=True)
        status["health_snapshot"] = {"ok": False, "error": str(exc)[:200]}

    return status


def enqueue_analysis_task(background_tasks, analysis_id: str):
    """
    Enqueue an analysis task for asynchronous execution.

    When Celery is available (Redis running), dispatches via Celery workers.
    When Celery is unavailable, uses FastAPI BackgroundTasks so the HTTP
    response returns immediately instead of blocking on the synchronous
    .delay() stub (which would run the entire scan inside the request).

    Parameters
    ----------
    background_tasks : BackgroundTasks
        FastAPI BackgroundTasks instance from the route handler.
    analysis_id : str
        The UUID of the Analysis record to scan.
    """
    if celery_app is not None:
        try:
            run_analysis_task.delay(analysis_id)
            logger.info(f"Analysis task {analysis_id} dispatched via Celery.")
            return
        except Exception as exc:
            logger.warning(
                f"Failed to dispatch Celery analysis task {analysis_id}, "
                f"falling back to BackgroundTasks: {exc}"
            )

    # Celery unavailable or dispatch failed → use BackgroundTasks
    background_tasks.add_task(run_analysis_task, None, analysis_id)
    logger.info(f"Analysis task {analysis_id} enqueued via BackgroundTasks.")



def _generate_scan_reports(db, analysis_id, user_id, repo_name, results: dict, repo_an: dict | None, test_suggs: str, pr_number=None):
    """Generate MD/JSON/CSV/PDF exports and persist Report rows.

    Extracted so BOTH the fresh-scan path and the cached-reuse path produce
    identical downloadable reports for the scan (the cached path previously
    created no reports at all).
    """
    report_data = {
        "repo_name": repo_name,
        "pr_number": pr_number,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "risk_score": results.get("risk_score", 0),
        "findings": results.get("findings", []),
        "test_suggestions": test_suggs,
        "repo_analysis": repo_an,
        "files_analyzed_log": results.get("files_analyzed_log", []),
        "scores": results.get("scores", {}),
    }

    # Include deterministic insight data in reports when available
    try:
        from app.models.models import (
            DependencyFinding, DuplicateCodeFinding, TechnicalDebtFinding,
            ArchitectureAnalysis, ComplexityFinding,
        )
        dep_rows = db.query(DependencyFinding).filter(DependencyFinding.analysis_id == analysis_id).all()
        if dep_rows:
            report_data["dependencies"] = {
                "findings": [{
                    "package_name": d.package_name, "ecosystem": d.ecosystem,
                    "resolved_version": d.resolved_version, "version_spec": d.version_spec,
                    "status": d.status, "severity": d.severity,
                    "advisory_id": d.advisory_id, "recommended_version": d.recommended_version,
                } for d in dep_rows],
                "summary": {
                    "total": len(dep_rows),
                    "known_vulnerable": sum(1 for d in dep_rows if d.status == "known_vulnerable"),
                    "outdated": sum(1 for d in dep_rows if d.status == "outdated"),
                    "unknown": sum(1 for d in dep_rows if d.status == "unknown"),
                },
            }
        dup_rows = db.query(DuplicateCodeFinding).filter(DuplicateCodeFinding.analysis_id == analysis_id).all()
        if dup_rows:
            report_data["duplicates"] = {
                "findings": [{
                    "file_a": d.file_a, "start_line_a": d.start_line_a, "end_line_a": d.end_line_a,
                    "file_b": d.file_b, "start_line_b": d.start_line_b, "end_line_b": d.end_line_b,
                    "similarity": d.similarity, "duplicated_lines": d.duplicated_lines,
                } for d in dup_rows],
            }
        debt_rows = db.query(TechnicalDebtFinding).filter(TechnicalDebtFinding.analysis_id == analysis_id).all()
        if debt_rows:
            report_data["technical_debt"] = {
                "items": [{
                    "category": t.category, "severity": t.severity, "title": t.title,
                    "evidence": t.evidence, "file": t.file, "line_start": t.line_start,
                    "estimated_effort_hours": t.estimated_effort_hours,
                } for t in debt_rows],
                "summary": {
                    "total_estimated_effort_hours": round(sum(t.estimated_effort_hours or 0 for t in debt_rows), 1),
                },
            }
        arch_row = db.query(ArchitectureAnalysis).filter(
            ArchitectureAnalysis.analysis_id == analysis_id
        ).order_by(ArchitectureAnalysis.created_at.desc()).first()
        if arch_row and isinstance(arch_row.result, dict):
            report_data["architecture"] = arch_row.result
        cx_rows = db.query(ComplexityFinding).filter(ComplexityFinding.analysis_id == analysis_id).all()
        if cx_rows:
            report_data["complexity"] = {
                "findings": [{
                    "file": c.file, "name": c.name, "line_start": c.line_start,
                    "cyclomatic_complexity": c.cyclomatic_complexity,
                    "length_lines": c.length_lines, "severity": c.severity,
                } for c in cx_rows],
                "summary": {
                    "total_functions_measured": len(cx_rows),
                    "reported": len(cx_rows),
                    "average_complexity": (
                        round(sum(c.cyclomatic_complexity for c in cx_rows) / len(cx_rows), 2)
                        if cx_rows else 0.0
                    ),
                },
            }
    except Exception as insights_report_err:
        logger.warning(f"Could not include insights in report data: {insights_report_err}")

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    storage_dir = os.path.join(base_dir, "storage")
    os.makedirs(storage_dir, exist_ok=True)

    md_path = os.path.join(storage_dir, f"report_{analysis_id}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(generate_markdown_report(report_data))
    db.add(Report(analysis_id=analysis_id, user_id=user_id, type="Markdown", filepath=md_path))

    json_path = os.path.join(storage_dir, f"report_{analysis_id}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(generate_json_report(report_data))
    db.add(Report(analysis_id=analysis_id, user_id=user_id, type="JSON", filepath=json_path))

    csv_path = os.path.join(storage_dir, f"report_{analysis_id}.csv")
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write(generate_csv_report(report_data))
    db.add(Report(analysis_id=analysis_id, user_id=user_id, type="CSV", filepath=csv_path))

    pdf_path = os.path.join(storage_dir, f"report_{analysis_id}.pdf")
    try:
        generate_pdf_report(report_data, pdf_path)
        db.add(Report(analysis_id=analysis_id, user_id=user_id, type="PDF", filepath=pdf_path))
        logger.info("Generated PDF report successfully.")
    except Exception as pdf_err:
        logger.error(f"Failed to generate PDF report: {pdf_err}", exc_info=True)

    db.commit()
    logger.info("[SCAN-TIMER] reports persisted for analysis_id=%s", analysis_id)


def _run_analysis_impl(self, analysis_id: str):
    """Core implementation of the analysis pipeline.

    Executes a PR review or repository scan, persists findings,
    and generates export reports.
    """
    import uuid as std_uuid
    analysis_id = std_uuid.UUID(analysis_id) if isinstance(analysis_id, str) else analysis_id
    db = SessionLocal()
    start_time = time.time()
    logger.info(f"Starting Celery analysis task for analysis_id: {analysis_id}")

    try:
        analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
        if not analysis:
            logger.error(f"Analysis record not found for id: {analysis_id}")
            return "Analysis record not found"

        repo = db.query(Repository).filter(Repository.id == analysis.repository_id).first()
        if not repo:
            update_progress(analysis_id, 100, "failed: Repository record missing", status="failed", db=db)
            return "Failed: Repository record missing"
        user = db.query(User).filter(User.id == repo.user_id).first()
        if not user:
            update_progress(analysis_id, 100, "failed: Repository owner missing", status="failed", db=db)
            return "Failed: Repository owner missing"

        # 1. Decrypt credentials
        logger.info(f"Resolving integration credentials for user_id: {user.id}")
        pat_source = "database" if user.github_pat_encrypted else "env"
        pat = encryptor.decrypt(user.github_pat_encrypted) if user.github_pat_encrypted else settings.GITHUB_TOKEN

        # Determine preferred provider and resolve its API key
        provider = (user.llm_default_provider or "groq").lower().strip()
        logger.info(f"User preferred LLM provider: {provider}")

        # Map provider → encrypted key column
        _provider_key_map = {
            "groq":       user.groq_api_key_encrypted,
            "openai":     user.openai_api_key_encrypted,
            "anthropic":  user.claude_api_key_encrypted,
            "claude":     user.claude_api_key_encrypted,
            "gemini":     user.gemini_api_key_encrypted,
            "openrouter": user.openrouter_api_key_encrypted,
        }
        _provider_env_map = {
            "groq":       getattr(settings, "GROQ_API_KEY", ""),
            "openai":     getattr(settings, "OPENAI_API_KEY", ""),
            "anthropic":  getattr(settings, "ANTHROPIC_API_KEY", ""),
            "claude":     getattr(settings, "ANTHROPIC_API_KEY", ""),
            "gemini":     getattr(settings, "GEMINI_API_KEY", ""),
            "openrouter": getattr(settings, "OPENROUTER_API_KEY", ""),
        }

        user_enc_key = _provider_key_map.get(provider)
        llm_api_key = encryptor.decrypt(user_enc_key) if user_enc_key else _provider_env_map.get(provider, "")

        # Fallback: if preferred provider key is missing, try Groq
        if not llm_api_key:
            logger.warning(f"API key for provider '{provider}' not found. Falling back to Groq.")
            provider = "groq"
            groq_enc = user.groq_api_key_encrypted
            llm_api_key = encryptor.decrypt(groq_enc) if groq_enc else settings.GROQ_API_KEY

        if not llm_api_key:
            logger.error("Scan failure: No LLM API Key is configured for any provider.")
            update_progress(analysis_id, 100, "failed: No LLM API Key configured", status="failed", db=db)
            analysis.status = "failed"
            analysis.insights = "The configured LLM API key is invalid or expired. Please update it in Settings."
            db.commit()
            return "Failed: No LLM API Key configured"

        # Resolve model name and generation parameters
        model_name = get_model_name(provider, user.llm_default_model)
        temperature = float(user.llm_temperature) if user.llm_temperature is not None else 0.3
        max_tokens = int(user.llm_max_tokens) if user.llm_max_tokens else 4096

        logger.info(
            f"LLM resolved: provider={provider}, model={model_name}, "
            f"temperature={temperature}, max_tokens={max_tokens}, "
            f"GitHub PAT from {pat_source}"
        )

        # 2. Setup Services
        update_progress(analysis_id, 10, "Initializing services...", status="cloning", db=db)
        github_service = GitHubService(token=pat)
        llm_client = build_llm_client(provider, llm_api_key)

        # ── DETERMINISTIC RESULT REUSE (PostgreSQL-backed) ─────────────
        # Same repository + same commit + same analysis version (+ model and
        # provider) ⇒ return the STORED result instead of re-running the LLM.
        # This is the production source of truth — the local JSON reviewer
        # cache is not durable across Render restarts/redeploys.
        from app.models.models import AnalysisResultCache
        full_scan = analysis.pull_request_id is None
        cached_payload = None
        cache_key = None
        # Test runs use isolated mocked repositories and must exercise the
        # fresh pipeline rather than reusing a cache row from a prior test.
        if full_scan and os.getenv("TESTING") != "1":
            try:
                head = github_service.get_repo_object(repo.name).get_branch(repo.default_branch).commit
                scan_commit_sha = head.sha
                analysis.branch = repo.default_branch
                analysis.commit_sha = scan_commit_sha
                analysis.analysis_version = ANALYSIS_VERSION
                db.commit()
                cache_key = build_scan_cache_key(repo.id, scan_commit_sha, provider, model_name)
                existing = db.query(AnalysisResultCache).filter(AnalysisResultCache.cache_key == cache_key).first()
                if existing and existing.result_json:
                    cached_payload = existing.result_json
                    existing.hit_count = (existing.hit_count or 0) + 1
                    existing.last_hit_at = datetime.now(timezone.utc)
                    db.commit()
                    logger.info(f"Result reuse: stored analysis found for commit {scan_commit_sha[:8]} (hits={existing.hit_count}). Reusing without LLM calls.")
            except Exception as cache_err:
                logger.warning(f"Result-reuse lookup failed (proceeding with a fresh scan): {cache_err}")
                cached_payload = None

        if cached_payload is not None:
            # Materialize the completed analysis from the stored result.
            reused_commit = analysis.commit_sha
            _materialize_cached_result(db, analysis, cached_payload, provider, model_name)
            db.expire(analysis)  # re-bind attributes to the session before further use
            analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
            # PERF FIX: rebuild this scan's insight rows from the analyzer
            # outputs stored IN the cache payload. The old code called
            # run_all_insights() here, which re-fetched every file from GitHub
            # and re-ran all analyzers — an entire second repository analysis
            # on every cache hit. Persisting from cached results is pure DB
            # inserts (milliseconds, zero GitHub calls) and gives this scan
            # its own complete insight rows for the UI.
            insights_status = None
            try:
                update_progress(analysis_id, 85, "Restoring repository insights from stored analysis...", status="generating_insights", db=db)
                insights_started = time.time()
                insights_status = _persist_precomputed_insights(
                    db, analysis_id, repo, cached_payload.get("_fast_scan_precomputed") or {}, reused_commit,
                )
                logger.info("[SCAN-TIMER] insights_cached=%.2fs", time.time() - insights_started)
                try:
                    existing.result_json = {**cached_payload, "_insights_status": insights_status}
                    db.commit()
                except Exception:
                    db.rollback()
            except Exception as insights_exc:
                logger.error(f"Insights stage on cached scan failed (non-fatal): {insights_exc}", exc_info=True)

            # Generate downloadable reports for the cached scan too (from the
            # stored result + the insight rows just persisted).
            try:
                update_progress(analysis_id, 90, "Generating export reports...", db=db)
                _generate_scan_reports(
                    db, analysis_id, user.id,
                    repo.name, cached_payload, cached_payload.get("repo_analysis"),
                    cached_payload.get("test_suggestions", ""),
                )
            except Exception as report_exc:
                logger.error(f"Cached-scan report generation failed (non-fatal): {report_exc}", exc_info=True)
            duration = time.time() - start_time
            logger.info(f"[SCAN-TIMER] cached_reuse TOTAL={duration:.2f}s for analysis_id: {analysis_id}")
            update_progress(analysis_id, 100, "Analysis completed (stored result for this exact commit was reused).", db=db)
            db.close()
            return f"Reused stored analysis for commit {reused_commit}"


        # ── DUPLICATE-SCAN GUARD ────────────────────────────────────
        # If the same repository+commit is already being scanned by another
        # worker, do NOT repeat the expensive work. Wait briefly for the
        # first scan to persist its cache entry, then reuse it.
        scan_guard_key = f"{repo.id}:{analysis.commit_sha}"
        guard_acquired = False
        if full_scan:
            with _active_scan_locks:
                if scan_guard_key in _active_scans:
                    guard_acquired = False
                else:
                    _active_scans.add(scan_guard_key)
                    guard_acquired = True
            if not guard_acquired:
                logger.warning(f"[PERFORMANCE-REGRESSION] duplicate_scan_blocked=true repo={repo.name} commit={str(analysis.commit_sha)[:8]}; attaching to in-flight scan.")
                # Wait up to 60s for the in-flight scan to finish and store its
                # result, then try to reuse it instead of re-scanning.
                for _ in range(12):
                    time.sleep(5)
                    try:
                        db.expire_all()
                        head = github_service.get_repo_object(repo.name).get_branch(repo.default_branch).commit
                        ck = build_scan_cache_key(repo.id, head.sha, provider, model_name)
                        row = db.query(AnalysisResultCache).filter(AnalysisResultCache.cache_key == ck).first()
                        if row and row.result_json:
                            _materialize_cached_result(db, analysis, row.result_json, provider, model_name)
                            update_progress(analysis_id, 100, "Analysis completed (attached to an identical in-flight scan).", db=db)
                            db.close()
                            return f"Reused in-flight scan result for commit {head.sha}"
                    except Exception:
                        continue
                # In-flight scan did not finish in time; run a full scan anyway
                # rather than failing the user's request.
                logger.warning("Duplicate-scan guard wait elapsed; proceeding with a fresh scan.")

        # Setup progress callback helper
        def progress_cb(prog, stat, msg, files_an=0, total_an=0, curr_file=""):
            update_progress(
                analysis_id=analysis_id,
                progress=prog,
                status_message=msg,
                status=stat,
                files_analyzed=files_an,
                total_files=total_an,
                current_file=curr_file,
                db=db
            )

        # 3. Execute scan (guard always released in finally, even on failure)
        try:
            review_started = time.time()
            results = None
            if analysis.pull_request_id:
                pr = db.query(PullRequest).filter(PullRequest.id == analysis.pull_request_id).first()
                update_progress(analysis_id, 30, f"Fetching PR #{pr.number} diff content...", status="scanning", db=db)
                logger.info(f"Starting Pull Request scan on repository: {repo.name}, PR: #{pr.number}")
                results = review_pull_request(
                    repo_name=repo.name,
                    pr_number=pr.number,
                    github_service=github_service,
                    client=llm_client,
                    progress_callback=progress_cb
                )
            else:
                update_progress(analysis_id, 30, "Fetching repository files...", status="scanning", db=db)
                logger.info(f"Starting full repository scan on: {repo.name}")
                results = review_entire_repository(
                    repo_name=repo.name,
                    github_service=github_service,
                    client=llm_client,
                    progress_callback=progress_cb
                )
        finally:
            if full_scan and guard_acquired:
                with _active_scan_locks:
                    _active_scans.discard(scan_guard_key)
        logger.info(
            "Scan stage completed: review duration=%.2fs files=%d requests=%d cache_hits=%d",
            time.time() - review_started,
            results.get("files_analyzed_count", 0),
            results.get("groq_requests_made", 0),
            results.get("cached_results_used", 0),
        )
            # The exact commit analyzed is resolved inside review_entire_repository
            # and returned as `head_sha`; the insights stage re-uses it so the
            # health snapshot records the true snapshot SHA (no second GitHub
            # call that could race with a new push).
            # Persist the snapshot identity on the scan row itself so every
            # feature (explorer, reports, chat) can consistently target the
            # same analyzed snapshot.

        # 4. Save results to Database
        update_progress(analysis_id, 70, "Persisting code review results...", status="generating_tests", db=db)
        logger.info(f"Scan complete. Persisting findings to DB for analysis_id: {analysis_id}")

        # Save metrics
        analysis.risk_score = results.get("risk_score", 0)
        analysis.latency_seconds = int(results.get("latency_seconds", 0))
        analysis.estimated_token_usage = results.get("estimated_token_usage", 0)
        analysis.files_analyzed_count = results.get("files_analyzed_count", 0)
        analysis.characters_analyzed_count = results.get("characters_analyzed_count", 0)
        analysis.groq_requests_made = results.get("groq_requests_made", 0)
        analysis.cached_results_used = results.get("cached_results_used", 0)

        # Snapshot identity on the scan row (authoritative single source of truth)
        if results.get("head_sha"):
            analysis.commit_sha = results.get("head_sha")
            analysis.branch = results.get("branch") or analysis.branch
            analysis.analysis_version = ANALYSIS_VERSION

        # Save token stats & model name
        t_stats = results.get("token_stats") or {}
        analysis.model_name = t_stats.get("model_name") or model_name
        analysis.prompt_tokens = t_stats.get("prompt_tokens") or 0
        analysis.completion_tokens = t_stats.get("completion_tokens") or 0
        analysis.total_tokens = t_stats.get("total_tokens") or 0
        analysis.scan_duration_seconds = int(time.time() - start_time)

        analysis.timestamp = datetime.now(timezone.utc)

        logger.info(
            f"Metrics saved: risk_score={analysis.risk_score}, "
            f"latency={analysis.latency_seconds}s, "
            f"files_analyzed={analysis.files_analyzed_count}, "
            f"characters={analysis.characters_analyzed_count}, "
            f"requests={analysis.groq_requests_made}, "
            f"cached={analysis.cached_results_used}, "
            f"model_name={analysis.model_name}, "
            f"total_tokens={analysis.total_tokens}, "
            f"scan_duration={analysis.scan_duration_seconds}s"
        )

        security_count = 0
        smell_count = 0
        # DETERMINISTIC PERSISTENCE ORDER: sort findings by (file, line, issue)
        # so database row order is stable for the same commit — display order,
        # comparison results and report content do not depend on dict
        # iteration order of the LLM/static scanner output.
        persisted_findings = sorted(
            results.get("findings", []),
            key=lambda f: (str(f.get("file", "")), int(f.get("line", 0) or 0), str(f.get("issue", "")))
        )
        # Save security findings
        for f in persisted_findings:
            if f.get("category") == "Security":
                security_count += 1
                db.add(SecurityFinding(
                    analysis_id=analysis_id,
                    file=f.get("file"),
                    line=f.get("line"),
                    severity=f.get("severity"),
                    issue=f.get("issue"),
                    why_it_matters=f.get("why_it_matters"),
                    risk_level=f.get("risk_level"),
                    suggestion=f.get("suggestion"),
                    before_code=f.get("before_code"),
                    after_code=f.get("after_code"),
                    start_line=f.get("start_line", f.get("line")),
                    end_line=f.get("end_line", f.get("line")),
                    code_snippet=f.get("before_code"),
                    issue_explanation=f.get("why_it_matters"),
                    source=f.get("source"),
                ))
            elif f.get("category") == "Code Smell":
                smell_count += 1
                db.add(CodeSmell(
                    analysis_id=analysis_id,
                    file=f.get("file"),
                    line=f.get("line"),
                    severity=f.get("severity"),
                    issue=f.get("issue"),
                    why_it_matters=f.get("why_it_matters"),
                    risk_level=f.get("risk_level"),
                    suggestion=f.get("suggestion"),
                    before_code=f.get("before_code"),
                    after_code=f.get("after_code"),
                    start_line=f.get("start_line", f.get("line")),
                    end_line=f.get("end_line", f.get("line")),
                    code_snippet=f.get("before_code"),
                    issue_explanation=f.get("why_it_matters"),
                    source=f.get("source"),
                ))

        logger.info(f"Saved {security_count} Security Findings and {smell_count} Code Smells.")

        # Save test suggestions
        test_suggs = results.get("test_suggestions", "")
        if test_suggs:
            logger.info("Saving test suggestions...")
            db.add(TestSuggestion(
                analysis_id=analysis_id,
                file="combined_suggestions",
                content=test_suggs
            ))

        # Save health scores
        repo_an = results.get("repo_analysis")
        if repo_an:
            # ── DETERMINISTIC health score ────────────────────────────
            # Always use repository_analyzer.py's deterministic formula.
            # Never derive score from LLM output (risk_score varies between runs).
            health_val = repo_an.get("health_score", 100)
            logger.info(f"Saving repository health score (deterministic): {health_val}")
            db.add(HealthScore(
                analysis_id=analysis_id,
                health_score=health_val,
                deductions=repo_an.get("deductions", []),
                readme_exists=repo_an.get("readme_exists", False),
                large_files=repo_an.get("large_files", []),
                security_hotspots=repo_an.get("security_hotspots", []),
                missing_tests=repo_an.get("missing_tests", []),
                test_files_count=repo_an.get("test_files_count", 0),
                source_files_count=repo_an.get("source_files_count", 0),
                docstring_coverage=repo_an.get("docstring_coverage", 0)
            ))
            analysis.insights = repo_an.get("analysis_report")
        elif "scores" in results:
            # ── PR scan: deterministic score from finding counts ───────
            # Formula: start at 100, deduct for security + smell findings
            sec_count = sum(1 for f in results.get("findings", []) if f.get("category") == "Security")
            smell_count = sum(1 for f in results.get("findings", []) if f.get("category") == "Code Smell")
            crit_sec = sum(1 for f in results.get("findings", []) if f.get("severity") == "Critical")
            high_sec = sum(1 for f in results.get("findings", []) if f.get("severity") == "High")
            med_sec = sum(1 for f in results.get("findings", []) if f.get("severity") == "Medium")
            major_smells = sum(1 for f in results.get("findings", []) if f.get("severity") in ["Critical", "High"] and f.get("category") == "Code Smell")
            minor_smells = sum(1 for f in results.get("findings", []) if f.get("severity") == "Low" and f.get("category") == "Code Smell")

            pr_health = 100
            pr_health -= crit_sec * 15
            pr_health -= high_sec * 10
            pr_health -= med_sec * 5
            pr_health -= major_smells * 3
            pr_health -= minor_smells * 1
            pr_health = max(0, min(100, pr_health))

            logger.info(f"Saving PR deterministic health score: {pr_health} (crit_sec={crit_sec}, high_sec={high_sec}, med_sec={med_sec}, major_smells={major_smells}, minor_smells={minor_smells})")
            db.add(HealthScore(
                analysis_id=analysis_id,
                health_score=pr_health,
                readme_exists=True,
                test_files_count=results.get("files_analyzed_count", 0),
                source_files_count=results.get("files_analyzed_count", 0),
                docstring_coverage=100
            ))
            analysis.insights = "Pull request scan complete. See tabs for specific findings."

        # Save metadata to DB
        db.commit()

        # 4.5 Deterministic repository insights (dependencies, duplicates,
        # complexity, architecture, technical debt, health snapshot).
        # Runs ONLY for full repository scans. Each insight is non-fatal:
        # a failure in any insight never fails the scan itself.
        insights_status = None
        insights_started = time.time()
        if not analysis.pull_request_id:
            try:
                update_progress(analysis_id, 85, "Computing repository insights...", status="generating_insights", db=db)
                # Reuse the commit SHA the scan actually analyzed (pinned at
                # scan start) — re-resolving here could race with a new push
                # and record a snapshot SHA that was never scanned.
                scan_head_sha = results.get("head_sha") or analysis.commit_sha

                # ── FAST SCAN OPTIMIZATION ──────────────────────────────────
                # If the fast scan pipeline pre-computed all insights (security,
                # complexity, duplicates, dependencies, architecture), persist
                # them directly instead of re-running the full insights pipeline.
                precomputed = results.get("_fast_scan_precomputed")
                if precomputed:
                    insights_status = _persist_precomputed_insights(
                        db, analysis_id, repo, precomputed, scan_head_sha,
                    )
                else:
                    insights_status = run_all_insights(db, analysis_id, repo, github_service, commit_sha=scan_head_sha)
            except Exception as insights_exc:
                logger.error(f"Repository insights failed (non-fatal): {insights_exc}", exc_info=True)
            logger.info("[SCAN-TIMER] insights=%.2fs", time.time() - insights_started)

            # ── STORE the fresh result for future deterministic reuse ──
            try:
                # Keep the precomputed analyzer outputs and per-insight status in
                # the cache payload so a cache hit can restore insights WITHOUT
                # re-fetching/re-analyzing anything (see cached path above).
                cache_results = dict(results)
                cache_results["_insights_status"] = insights_status
                _store_result_cache(
                    db, repo, analysis.commit_sha or results.get("head_sha"),
                    provider, model_name, cache_results,
                )
            except Exception as store_err:
                logger.warning(f"Failed to store result cache entry (non-fatal): {store_err}")

        # 5. Generate and save exports
        update_progress(analysis_id, 90, "Generating export reports...", db=db)
        _generate_scan_reports(
            db, analysis_id, user.id, repo.name, results, repo_an, test_suggs,
            pr_number=(pr.number if analysis.pull_request_id else None),
        )

        duration = time.time() - start_time
        logger.info(f"[SCAN-TIMER] TOTAL={duration:.2f}s (task complete) analysis_id={analysis_id}")
        logger.info(f"Celery analysis task completed successfully in {duration:.2f}s for analysis_id: {analysis_id}")
        update_progress(analysis_id, 100, "Analysis completed successfully!", db=db)

    except Exception as exc:
        # PERF FIX: no Celery-level retries. Previously autoretry re-ran the
        # ENTIRE scan (clone + fetch + analysis + LLM) up to 3 extra times with
        # 10–40s backoffs — the single biggest cause of 5–15 minute scans.
        # A failed scan now fails exactly once, quickly, with a clear message.
        is_celery_mode = self is not None and hasattr(self, 'request') and self.request is not None

        duration = time.time() - start_time
        logger.error(f"[SCAN-TIMER] failed_after={duration:.2f}s error={exc}")
        logger.error(f"Analysis task failed after {duration:.2f}s: {exc}", exc_info=True)

        # Convert common errors to user-friendly messages
        def _friendly_scan_error(err_msg: str) -> str:
            if "401" in err_msg or "invalid" in err_msg.lower() or "api_key" in err_msg.lower():
                return "The configured LLM API key is invalid or expired. Please update it in Settings."
            if "429" in err_msg or "rate_limit" in err_msg or "quota" in err_msg:
                return "LLM API rate limit exceeded. Please wait a moment and try again."
            if "timeout" in err_msg.lower() or "timed out" in err_msg.lower():
                return "The analysis timed out. Your repository may be too large. Try scanning fewer files."
            if "model" in err_msg.lower() and ("not found" in err_msg.lower() or "unavailable" in err_msg.lower() or "does not exist" in err_msg.lower()):
                return "The selected AI model is currently unavailable. Try a different model in Settings."
            if "github" in err_msg.lower() or "bad credentials" in err_msg.lower():
                return "GitHub token is invalid or lacks access to this repository. Please update your PAT in Settings."
            return f"Analysis failed: {err_msg[:200]}"

        duration = time.time() - start_time
        if not is_celery_mode:
            try:
                analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
                if analysis:
                    analysis.status = "failed"
                    analysis.progress = 100
                    analysis.insights = _friendly_scan_error(str(exc))
                    db.commit()
            except Exception:
                pass
            finally:
                db.close()
            return f"Failed: {str(exc)}"

        try:
            from app.models.models import DeadLetterTask
            from app.utils.audit import log_audit_event_sync

            dlq_task = DeadLetterTask(
                task_id=str(self.request.id),
                task_name="run_analysis_task",
                arguments={"analysis_id": str(analysis_id)},
                error_message=str(exc),
                stack_trace=traceback.format_exc()
            )
            db.add(dlq_task)
            db.commit()

            log_audit_event_sync(
                action="DLQ_TASK_CREATED",
                details={"task_id": str(self.request.id), "error": str(exc)}
            )
        except Exception as dlq_err:
            logger.error(f"Failed to save failed task to DeadLetterTask database table: {dlq_err}")

        try:
            redis_client.lpush(
                "acr_dead_letter_queue",
                json.dumps({
                    "task_id": str(self.request.id),
                    "task_name": "run_analysis_task",
                    "arguments": {"analysis_id": str(analysis_id)},
                    "error": str(exc),
                    "failed_at": datetime.utcnow().isoformat()
                })
            )
        except Exception as redis_err:
            logger.error(f"Failed to push task to Redis DLQ: {redis_err}")

        update_progress(analysis_id, 100, f"failed: {str(exc)}", db=db)
        # Re-query to get a fresh object from the session
        analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
        if analysis:
            analysis.status = "failed"
            analysis.insights = _friendly_scan_error(str(exc))
            db.commit()
    finally:
        db.close()

