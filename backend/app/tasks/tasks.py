import os
import time
from celery import Celery
import redis
import json
import traceback
from datetime import datetime

from backend.app.config import settings
from backend.app.database.database import SessionLocal
from backend.app.models.models import (
    Analysis, Repository, PullRequest, User,
    SecurityFinding, CodeSmell, TestSuggestion, HealthScore, Report
)
from backend.app.auth.encryption import encryptor
from backend.app.services.github_service import GitHubService
from backend.app.services.reviewer import review_pull_request, review_entire_repository
from backend.app.services.llm_client import build_llm_client, get_model_name, build_groq_client
from backend.app.services.report_generator import (
    generate_markdown_report, generate_json_report, generate_csv_report, generate_pdf_report
)
from backend.app.utils.logger import get_logger

logger = get_logger("celery_worker")

celery_app = Celery(
    "tasks",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL
)
celery_app.conf.update(
    broker_connection_retry_on_startup=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_routes={
        "backend.app.tasks.tasks.run_analysis_task": {"queue": "celery"},
        "dead_letter": {"queue": "dead_letter"}
    }
)

redis_client = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=2, socket_connect_timeout=2)

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
    
    try:
        analysis = session.query(Analysis).filter(Analysis.id == analysis_id).first()
        if analysis:
            analysis.progress = progress
            if progress >= 100:
                if "failed" in status_message.lower():
                    analysis.status = "failed"
                else:
                    analysis.status = "completed"
            else:
                analysis.status = status
            session.commit()
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

@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3}
)
def run_analysis_task(self, analysis_id: str):
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
            analysis.insights = "Error: No LLM API Key is configured. Add a key in Settings."
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

        # 3. Execute scan
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
            update_progress(analysis_id, 30, "Fetching repository files recursively...", status="scanning", db=db)
            logger.info(f"Starting full repository scan on: {repo.name}")
            results = review_entire_repository(
                repo_name=repo.name,
                github_service=github_service,
                client=llm_client,
                progress_callback=progress_cb
            )
            
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
        
        # Save token stats & model name
        t_stats = results.get("token_stats") or {}
        analysis.model_name = t_stats.get("model_name") or model_name
        analysis.prompt_tokens = t_stats.get("prompt_tokens") or 0
        analysis.completion_tokens = t_stats.get("completion_tokens") or 0
        analysis.total_tokens = t_stats.get("total_tokens") or 0
        analysis.scan_duration_seconds = int(time.time() - start_time)
        
        analysis.timestamp = datetime.utcnow()
        
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
        # Save security findings
        for f in results.get("findings", []):
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
                    issue_explanation=f.get("why_it_matters")
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
                    issue_explanation=f.get("why_it_matters")
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
        
        # 5. Generate and save exports
        update_progress(analysis_id, 90, "Generating export reports...", db=db)
        
        # Format the data parameter correctly for report generators
        report_data = {
            "repo_name": repo.name,
            "pr_number": pr.number if analysis.pull_request_id else None,
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "risk_score": analysis.risk_score,
            "findings": results.get("findings", []),
            "test_suggestions": test_suggs,
            "repo_analysis": repo_an,
            "files_analyzed_log": results.get("files_analyzed_log", []),
            "scores": results.get("scores", {})
        }
        
        # Base storage path
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        storage_dir = os.path.join(base_dir, "storage")
        logger.info(f"Persisting reports to shared storage path: {storage_dir}")
        os.makedirs(storage_dir, exist_ok=True)
        
        # Generate Markdown
        md_content = generate_markdown_report(report_data)
        md_path = os.path.join(storage_dir, f"report_{analysis_id}.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        db.add(Report(analysis_id=analysis_id, user_id=user.id, type="Markdown", filepath=md_path))
        
        # Generate JSON
        json_content = generate_json_report(report_data)
        json_path = os.path.join(storage_dir, f"report_{analysis_id}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(json_content)
        db.add(Report(analysis_id=analysis_id, user_id=user.id, type="JSON", filepath=json_path))
 
        # Generate CSV
        csv_content = generate_csv_report(report_data)
        csv_path = os.path.join(storage_dir, f"report_{analysis_id}.csv")
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write(csv_content)
        db.add(Report(analysis_id=analysis_id, user_id=user.id, type="CSV", filepath=csv_path))
 
        # Generate PDF
        pdf_path = os.path.join(storage_dir, f"report_{analysis_id}.pdf")
        try:
            generate_pdf_report(report_data, pdf_path)
            db.add(Report(analysis_id=analysis_id, user_id=user.id, type="PDF", filepath=pdf_path))
            logger.info("Generated PDF report successfully.")
        except Exception as pdf_err:
            logger.error(f"Failed to generate PDF report: {pdf_err}", exc_info=True)
            
        db.commit()
        
        duration = time.time() - start_time
        logger.info(f"Celery analysis task completed successfully in {duration:.2f}s for analysis_id: {analysis_id}")
        update_progress(analysis_id, 100, "Analysis completed successfully!", db=db)
        
    except Exception as exc:
        # check if running in Celery mode (self is a real task) or background_tasks fallback (self is None)
        is_celery_mode = self is not None and hasattr(self, 'request') and self.request is not None
        
        if is_celery_mode and self.request.retries < self.max_retries and not os.getenv("TESTING") and not getattr(self.request, "called_directly", False):
            logger.info(f"Task run_analysis_task failed. Retrying (attempt {self.request.retries + 1}/{self.max_retries})...")
            db.close()
            raise self.retry(exc=exc, countdown=10 * (2 ** self.request.retries))
            
        duration = time.time() - start_time
        logger.error(f"Celery analysis task failed and exhausted all retries after {duration:.2f}s: {exc}", exc_info=True)
        
        # For background_tasks fallback mode, don't attempt retries - just log and clean up
        if not is_celery_mode:
            try:
                analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
                if analysis:
                    analysis.status = "failed"
                    analysis.progress = 100
                    analysis.insights = f"Job failed due to error: {str(exc)}\\n\\nStack trace:\\n{traceback.format_exc()}"
                    db.commit()
            except Exception:
                pass
            finally:
                db.close()
            return f"Failed: {str(exc)}"
        
        try:
            from backend.app.models.models import DeadLetterTask
            from backend.app.utils.audit import log_audit_event_sync
            
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
            analysis.insights = f"Job failed due to error: {str(exc)}\n\nStack trace:\n{traceback.format_exc()}"
            db.commit()
    finally:
        db.close()

