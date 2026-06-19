from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Dict, Any
import datetime

from backend.app.database.database import get_async_db
from backend.app.models.models import User, Repository, PullRequest, Analysis, SecurityFinding, HealthScore, Report
from backend.app.schemas.schemas import UserOut, CredentialsUpdate, DashboardMetrics
from backend.app.auth.security import get_current_user
from backend.app.auth.encryption import encryptor
from backend.app.config import settings

router = APIRouter(prefix="/users", tags=["Users"])

@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserOut(
        id=current_user.id,
        email=current_user.email,
        created_at=current_user.created_at,
        has_github_pat=bool(current_user.github_pat_encrypted),
        has_groq_api_key=bool(current_user.groq_api_key_encrypted),
        has_openai_api_key=bool(current_user.openai_api_key_encrypted),
        has_claude_api_key=bool(current_user.claude_api_key_encrypted),
        has_gemini_api_key=bool(current_user.gemini_api_key_encrypted),
        has_openrouter_api_key=bool(current_user.openrouter_api_key_encrypted),
        llm_default_provider=current_user.llm_default_provider,
        llm_default_model=current_user.llm_default_model,
        llm_temperature=current_user.llm_temperature,
        llm_max_tokens=current_user.llm_max_tokens
    )

@router.post("/keys", response_model=UserOut)
async def update_credentials(
    creds: CredentialsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    if creds.github_pat is not None and creds.github_pat.strip():
        current_user.github_pat_encrypted = encryptor.encrypt(creds.github_pat.strip())
    if creds.groq_api_key is not None and creds.groq_api_key.strip():
        current_user.groq_api_key_encrypted = encryptor.encrypt(creds.groq_api_key.strip())
    if creds.openai_api_key is not None and creds.openai_api_key.strip():
        current_user.openai_api_key_encrypted = encryptor.encrypt(creds.openai_api_key.strip())
    if creds.claude_api_key is not None and creds.claude_api_key.strip():
        current_user.claude_api_key_encrypted = encryptor.encrypt(creds.claude_api_key.strip())
    if creds.gemini_api_key is not None and creds.gemini_api_key.strip():
        current_user.gemini_api_key_encrypted = encryptor.encrypt(creds.gemini_api_key.strip())
    if creds.openrouter_api_key is not None and creds.openrouter_api_key.strip():
        current_user.openrouter_api_key_encrypted = encryptor.encrypt(creds.openrouter_api_key.strip())
    if creds.llm_default_provider is not None:
        current_user.llm_default_provider = creds.llm_default_provider
    if creds.llm_default_model is not None:
        current_user.llm_default_model = creds.llm_default_model
    if creds.llm_temperature is not None:
        current_user.llm_temperature = creds.llm_temperature
    if creds.llm_max_tokens is not None:
        current_user.llm_max_tokens = creds.llm_max_tokens
        
    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)
    
    return UserOut(
        id=current_user.id,
        email=current_user.email,
        created_at=current_user.created_at,
        has_github_pat=bool(current_user.github_pat_encrypted),
        has_groq_api_key=bool(current_user.groq_api_key_encrypted),
        has_openai_api_key=bool(current_user.openai_api_key_encrypted),
        has_claude_api_key=bool(current_user.claude_api_key_encrypted),
        has_gemini_api_key=bool(current_user.gemini_api_key_encrypted),
        has_openrouter_api_key=bool(current_user.openrouter_api_key_encrypted),
        llm_default_provider=current_user.llm_default_provider,
        llm_default_model=current_user.llm_default_model,
        llm_temperature=current_user.llm_temperature,
        llm_max_tokens=current_user.llm_max_tokens
    )

@router.get("/me/diagnostics")
async def get_diagnostics(current_user: User = Depends(get_current_user)):
    """Return only configured/not-configured status for each provider. Never show server env values."""
    # Check GitHub PAT
    github_pat_configured = False
    if current_user.github_pat_encrypted:
        try:
            if encryptor.decrypt(current_user.github_pat_encrypted):
                github_pat_configured = True
        except Exception:
            pass

    github_api_status = "Offline"
    if github_pat_configured:
        import httpx
        try:
            token = encryptor.decrypt(current_user.github_pat_encrypted)
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(
                    "https://api.github.com/zen",
                    headers={"Authorization": f"token {token}"} if token else {}
                )
                if response.status_code == 200:
                    github_api_status = "Online"
                else:
                    github_api_status = f"Offline (HTTP {response.status_code})"
        except Exception as e:
            github_api_status = f"Offline ({str(e)})"
    else:
        github_api_status = "Unavailable"

    def check_key_configured(encrypted_val: str | None) -> bool:
        if not encrypted_val:
            return False
        try:
            return bool(encryptor.decrypt(encrypted_val))
        except Exception:
            return False

    providers_status = {
        "github": {
            "configured": github_pat_configured,
            "status": "Configured" if github_pat_configured else "Not Configured",
            "api_status": github_api_status
        },
        "groq": {
            "configured": check_key_configured(current_user.groq_api_key_encrypted),
            "status": "Configured" if check_key_configured(current_user.groq_api_key_encrypted) else "Not Configured"
        },
        "openai": {
            "configured": check_key_configured(current_user.openai_api_key_encrypted),
            "status": "Configured" if check_key_configured(current_user.openai_api_key_encrypted) else "Not Configured"
        },
        "claude": {
            "configured": check_key_configured(current_user.claude_api_key_encrypted),
            "status": "Configured" if check_key_configured(current_user.claude_api_key_encrypted) else "Not Configured"
        },
        "gemini": {
            "configured": check_key_configured(current_user.gemini_api_key_encrypted),
            "status": "Configured" if check_key_configured(current_user.gemini_api_key_encrypted) else "Not Configured"
        },
        "openrouter": {
            "configured": check_key_configured(current_user.openrouter_api_key_encrypted),
            "status": "Configured" if check_key_configured(current_user.openrouter_api_key_encrypted) else "Not Configured"
        }
    }

    # Check database connectivity
    db_status = "Unknown"
    try:
        from sqlalchemy import text as sa_text
        await db.execute(sa_text("SELECT 1"))
        db_status = "Connected"
    except Exception as e:
        db_status = f"Error: {str(e)}"

    # Check Redis connectivity
    redis_status = "Unknown"
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL)
        await r.ping()
        await r.close()
        redis_status = "Connected"
    except Exception as e:
        redis_status = f"Error: {str(e)}"

    # JWT status
    jwt_status = "Active" if settings.SECRET_KEY else "Inactive"

    # Encryption status
    encryption_status = "Active (AES-256)" if settings.ENCRYPTION_KEY else "Inactive"

    return {
        "providers": providers_status,
        "encryption_status": encryption_status,
        "database_status": db_status,
        "redis_status": redis_status,
        "jwt_status": jwt_status
    }

@router.get("/me/dashboard", response_model=DashboardMetrics)
async def get_dashboard_metrics(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    # Get user repository IDs
    repo_ids_res = await db.execute(
        select(Repository.id).where(
            (Repository.user_id == current_user.id) &
            ((Repository.is_connected == True) | (Repository.is_connected.is_(None)))
        )
    )
    repo_ids = [r for r in repo_ids_res.scalars().all()]
    
    # 1. Total connected repositories
    repositories_count = len(repo_ids)
    
    if not repo_ids:
        return DashboardMetrics(
            repositories_count=0,
            prs_count=0,
            vulnerabilities_count=0,
            avg_health_score=100.0,
            security_score=100.0,
            security_score_history=[],
            severity_distribution={"Critical": 0, "High": 0, "Medium": 0, "Low": 0, "Info": 0},
            vulnerability_trends=[],
            health_history=[],
            recent_activity=[],
            top_risky_repositories=[],
            average_scan_duration=0.0,
            token_consumption={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            model_usage={}
        )
        
    # 2. Pull requests reviewed count
    pr_count_res = await db.execute(
        select(func.count(Analysis.id)).where(
            (Analysis.repository_id.in_(repo_ids)) &
            (Analysis.pull_request_id.isnot(None)) &
            (Analysis.status == "completed") &
            ((Analysis.is_deleted == False) | (Analysis.is_deleted.is_(None)))
        )
    )
    prs_count = pr_count_res.scalar() or 0
    
    # 3. Total vulnerabilities detected
    vuln_count_res = await db.execute(
        select(func.count(SecurityFinding.id))
        .join(Analysis)
        .where(
            (Analysis.repository_id.in_(repo_ids)) &
            (Analysis.status == "completed") &
            ((Analysis.is_deleted == False) | (Analysis.is_deleted.is_(None)))
        )
    )
    vulnerabilities_count = vuln_count_res.scalar() or 0
    
    # 4. Avg health score
    health_avg_res = await db.execute(
        select(func.avg(HealthScore.health_score))
        .join(Analysis)
        .where(
            (Analysis.repository_id.in_(repo_ids)) &
            (Analysis.status == "completed") &
            ((Analysis.is_deleted == False) | (Analysis.is_deleted.is_(None)))
        )
    )
    avg_health_score_value = health_avg_res.scalar()
    avg_health_score = float(avg_health_score_value) if avg_health_score_value is not None else 0.0
    
    # 5. Severity distribution
    sev_dist = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0, "Info": 0}
    severity_res = await db.execute(
        select(SecurityFinding.severity, func.count(SecurityFinding.id))
        .join(Analysis)
        .where(
            (Analysis.repository_id.in_(repo_ids)) &
            (Analysis.status == "completed") &
            ((Analysis.is_deleted == False) | (Analysis.is_deleted.is_(None)))
        )
        .group_by(SecurityFinding.severity)
    )
    for row in severity_res.all():
        if row[0] in sev_dist:
            sev_dist[row[0]] = row[1]
            
    # 6. Vulnerability trends (past 30 days)
    today = datetime.date.today()
    thirty_days_ago = today - datetime.timedelta(days=30)
    trends_res = await db.execute(
        select(func.date(Analysis.timestamp), func.count(SecurityFinding.id))
        .join(SecurityFinding, SecurityFinding.analysis_id == Analysis.id)
        .where(
            (Analysis.repository_id.in_(repo_ids)) &
            (Analysis.status == "completed") &
            (Analysis.timestamp >= thirty_days_ago) &
            ((Analysis.is_deleted == False) | (Analysis.is_deleted.is_(None)))
        )
        .group_by(func.date(Analysis.timestamp))
        .order_by(func.date(Analysis.timestamp))
    )
    vulnerability_trends = [{"date": str(row[0]), "count": row[1]} for row in trends_res.all()]
    
    # 7. Repository health history
    health_history_res = await db.execute(
        select(Repository.name, Analysis.timestamp, HealthScore.health_score)
        .join(Analysis, Analysis.repository_id == Repository.id)
        .join(HealthScore, HealthScore.analysis_id == Analysis.id)
        .where(
            (Repository.user_id == current_user.id) &
            (Analysis.status == "completed") &
            ((Repository.is_connected == True) | (Repository.is_connected.is_(None))) &
            ((Analysis.is_deleted == False) | (Analysis.is_deleted.is_(None)))
        )
        .order_by(Analysis.timestamp.asc())
        .limit(20)
    )
    health_history = [
        {"repo": row[0], "date": row[1].strftime("%Y-%m-%d %H:%M"), "score": row[2]}
        for row in health_history_res.all()
    ]
    
    # Calculate security score history (100 - risk_score)
    security_score_history_res = await db.execute(
        select(Repository.name, Analysis.timestamp, Analysis.risk_score)
        .join(Analysis, Analysis.repository_id == Repository.id)
        .where(
            (Repository.user_id == current_user.id) &
            (Analysis.status == "completed") &
            ((Repository.is_connected == True) | (Repository.is_connected.is_(None))) &
            ((Analysis.is_deleted == False) | (Analysis.is_deleted.is_(None)))
        )
        .order_by(Analysis.timestamp.asc())
        .limit(20)
    )
    security_score_history = [
        {"repo": row[0], "date": row[1].strftime("%Y-%m-%d %H:%M"), "score": max(0, 100 - (row[2] or 0))}
        for row in security_score_history_res.all()
    ]
    
    # Calculate current average security score
    avg_risk_res = await db.execute(
        select(func.avg(Analysis.risk_score))
        .join(Repository, Analysis.repository_id == Repository.id)
        .where(
            (Repository.user_id == current_user.id) &
            (Analysis.status == "completed") &
            ((Repository.is_connected == True) | (Repository.is_connected.is_(None))) &
            ((Analysis.is_deleted == False) | (Analysis.is_deleted.is_(None)))
        )
    )
    avg_risk = avg_risk_res.scalar()
    security_score = float(max(0, 100 - avg_risk) if avg_risk is not None else 0.0)
    
    # 8. Recent activity
    recent_analyses_res = await db.execute(
        select(Repository.name, Analysis.status, Analysis.timestamp, Analysis.id)
        .join(Repository, Analysis.repository_id == Repository.id)
        .where(
            (Repository.user_id == current_user.id) &
            (Analysis.status == "completed") &
            ((Repository.is_connected == True) | (Repository.is_connected.is_(None))) &
            ((Analysis.is_deleted == False) | (Analysis.is_deleted.is_(None)))
        )
        .order_by(Analysis.timestamp.desc())
        .limit(10)
    )
    recent_activity = [
        {
            "repo": row[0],
            "status": row[1],
            "timestamp": row[2].strftime("%Y-%m-%d %H:%M"),
            "analysis_id": str(row[3])
        }
        for row in recent_analyses_res.all()
    ]
    
    # 9. Average scan duration
    avg_dur_res = await db.execute(
        select(func.avg(Analysis.scan_duration_seconds)).where(
            (Analysis.repository_id.in_(repo_ids)) &
            (Analysis.status == "completed") &
            ((Analysis.is_deleted == False) | (Analysis.is_deleted.is_(None)))
        )
    )
    average_scan_duration = float(avg_dur_res.scalar() or 0.0)

    # 10. Token consumption
    tokens_res = await db.execute(
        select(
            func.sum(Analysis.prompt_tokens),
            func.sum(Analysis.completion_tokens),
            func.sum(Analysis.total_tokens)
        ).where(
            (Analysis.repository_id.in_(repo_ids)) &
            (Analysis.status == "completed") &
            ((Analysis.is_deleted == False) | (Analysis.is_deleted.is_(None)))
        )
    )
    tokens_row = tokens_res.first()
    token_consumption = {
        "prompt_tokens": int(tokens_row[0] or 0) if tokens_row else 0,
        "completion_tokens": int(tokens_row[1] or 0) if tokens_row else 0,
        "total_tokens": int(tokens_row[2] or 0) if tokens_row else 0
    }

    # 11. Model usage counts
    model_usage_res = await db.execute(
        select(Analysis.model_name, func.count(Analysis.id)).where(
            (Analysis.repository_id.in_(repo_ids)) &
            (Analysis.status == "completed") &
            ((Analysis.is_deleted == False) | (Analysis.is_deleted.is_(None)))
        ).group_by(Analysis.model_name)
    )
    model_usage = {row[0] or "unknown": row[1] for row in model_usage_res.all()}

    # 12. Top risky repositories
    top_risky_repositories = []
    for r_id in repo_ids:
        repo_obj_res = await db.execute(select(Repository).where(Repository.id == r_id))
        repo_obj = repo_obj_res.scalars().first()
        if not repo_obj:
            continue
        latest_scan_res = await db.execute(
            select(Analysis.risk_score)
            .where(
                (Analysis.repository_id == r_id) &
                (Analysis.status == "completed") &
                ((Analysis.is_deleted == False) | (Analysis.is_deleted.is_(None)))
            )
            .order_by(Analysis.timestamp.desc())
            .limit(1)
        )
        latest_risk = latest_scan_res.scalar()
        if latest_risk is not None:
            top_risky_repositories.append({
                "repo_id": str(r_id),
                "name": repo_obj.name,
                "risk_score": latest_risk
            })
    top_risky_repositories.sort(key=lambda x: x["risk_score"], reverse=True)
    top_risky_repositories = top_risky_repositories[:5]

    return DashboardMetrics(
        repositories_count=repositories_count,
        prs_count=prs_count,
        vulnerabilities_count=vulnerabilities_count,
        avg_health_score=avg_health_score,
        security_score=security_score,
        security_score_history=security_score_history,
        severity_distribution=sev_dist,
        vulnerability_trends=vulnerability_trends,
        health_history=health_history,
        recent_activity=recent_activity,
        top_risky_repositories=top_risky_repositories,
        average_scan_duration=average_scan_duration,
        token_consumption=token_consumption,
        model_usage=model_usage
    )