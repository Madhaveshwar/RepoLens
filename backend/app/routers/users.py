from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Dict, Any
import datetime
import logging
import httpx

from app.database.database import get_async_db

logger = logging.getLogger(__name__)
from app.models.models import User, Repository, PullRequest, Analysis, SecurityFinding, HealthScore, Report
from app.schemas.schemas import UserOut, CredentialsUpdate, DashboardMetrics
from app.auth.security import get_current_user
from app.auth.encryption import encryptor
from app.config import settings
from app.services.llm_client import PROVIDER_MODELS

router = APIRouter(prefix="/users", tags=["Users"])

# ── Helper functions for credential verification ───────────────────────────

def check_key_configured(encrypted_val: str | None) -> bool:
    """Check if an encrypted credential is valid by attempting decryption."""
    if not encrypted_val:
        return False
    try:
        return bool(encryptor.decrypt(encrypted_val))
    except Exception:
        return False


def get_decrypted_key(encrypted_val: str | None) -> str | None:
    """Safely decrypt a credential. Returns None if decryption fails."""
    if not encrypted_val:
        return None
    try:
        val = encryptor.decrypt(encrypted_val)
        return val if val else None
    except Exception:
        return None


def get_user_credentials(user: User) -> dict[str, str | None]:
    """
    Get all decrypted credentials for a user.
    
    Returns a dict with:
      - github_pat: decrypted PAT or None
      - groq_api_key: decrypted Groq key or None
      - openai_api_key: decrypted OpenAI key or None
      - claude_api_key: decrypted Claude key or None
      - gemini_api_key: decrypted Gemini key or None
      - openrouter_api_key: decrypted OpenRouter key or None
      - llm_default_provider: user's preferred provider
      - llm_default_model: user's preferred model
    
    This function should be used by all scan services to ensure
    user-specific credentials are always preferred over env vars.
    """
    return {
        "github_pat": get_decrypted_key(user.github_pat_encrypted),
        "groq_api_key": get_decrypted_key(user.groq_api_key_encrypted),
        "openai_api_key": get_decrypted_key(user.openai_api_key_encrypted),
        "claude_api_key": get_decrypted_key(user.claude_api_key_encrypted),
        "gemini_api_key": get_decrypted_key(user.gemini_api_key_encrypted),
        "openrouter_api_key": get_decrypted_key(user.openrouter_api_key_encrypted),
        "llm_default_provider": user.llm_default_provider,
        "llm_default_model": user.llm_default_model,
    }


async def test_github_api(token: str) -> str:
    """Test a GitHub PAT by making a lightweight API call.
    
    Returns one of:
      - "Connected"       → API responded successfully
      - "Invalid Key"     → API returned 401/403 (unauthorized)
      - "Missing Key"     → No key provided
      - "Timeout"         → Request timed out
      - "Error: ..."      → Other error
    """
    if not token:
        return "Missing Key"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://api.github.com/zen",
                headers={"Authorization": f"token {token}", "User-Agent": "AI-Code-Reviewer"}
            )
            if resp.status_code == 200:
                return "Connected"
            elif resp.status_code in (401, 403):
                return "Invalid Key"
            else:
                return f"Error (HTTP {resp.status_code})"
    except httpx.TimeoutException:
        return "Timeout"
    except Exception as e:
        return f"Error: {str(e)}"


async def test_llm_api(provider: str, api_key: str) -> str:
    """Test an LLM provider API key by making a lightweight API call.
    
    Returns one of:
      - "Connected"       → API responded successfully
      - "Invalid Key"     → API returned 401/403 (unauthorized)
      - "Missing Key"     → No key provided (caller should use this)
      - "Timeout"         → Request timed out
      - "Error: ..."      → Other error
    """
    if not api_key:
        return "Missing Key"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            if provider == "groq":
                resp = await client.get(
                    "https://api.groq.com/openai/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"}
                )
                if resp.status_code == 200:
                    return "Connected"
                elif resp.status_code == 401:
                    return "Invalid Key"
                else:
                    return f"Error (HTTP {resp.status_code})"
            elif provider == "openai":
                resp = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"}
                )
                if resp.status_code == 200:
                    return "Connected"
                elif resp.status_code == 401:
                    return "Invalid Key"
                else:
                    return f"Error (HTTP {resp.status_code})"
            elif provider == "claude":
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    json={"model": "claude-sonnet-4-20250514", "max_tokens": 1, "messages": [{"role": "user", "content": "ping"}]}
                )
                if resp.status_code in (200, 201):
                    return "Connected"
                elif resp.status_code == 401:
                    return "Invalid Key"
                else:
                    return f"Error (HTTP {resp.status_code})"
            elif provider == "gemini":
                resp = await client.get(
                    f"https://generativelanguage.googleapis.com/v1/models?key={api_key}"
                )
                if resp.status_code == 200:
                    return "Connected"
                elif resp.status_code == 403:
                    return "Invalid Key"
                else:
                    return f"Error (HTTP {resp.status_code})"
            elif provider == "openrouter":
                resp = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"}
                )
                if resp.status_code == 200:
                    return "Connected"
                elif resp.status_code == 401:
                    return "Invalid Key"
                else:
                    return f"Error (HTTP {resp.status_code})"
            return "Unknown"
    except httpx.TimeoutException:
        return "Timeout"
    except Exception as e:
        return f"Error: {str(e)}"


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


@router.get("/me/llm-models")
async def get_llm_models(current_user: User = Depends(get_current_user)):
    """Return the selectable model list per LLM provider for the Settings UI."""
    return {"models": PROVIDER_MODELS}

@router.post("/keys", response_model=UserOut)
async def update_credentials(
    creds: CredentialsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    logger.info(f"update_credentials called for user_id={current_user.id}")
    
    # ── Validate each submitted key against its provider API before saving ──
    key_validations = []  # (field_name, provider, raw_key)
    if creds.github_pat is not None and creds.github_pat.strip():
        key_validations.append(("github_pat", "github", creds.github_pat.strip()))
    if creds.groq_api_key is not None and creds.groq_api_key.strip():
        key_validations.append(("groq_api_key", "groq", creds.groq_api_key.strip()))
    if creds.openai_api_key is not None and creds.openai_api_key.strip():
        key_validations.append(("openai_api_key", "openai", creds.openai_api_key.strip()))
    if creds.claude_api_key is not None and creds.claude_api_key.strip():
        key_validations.append(("claude_api_key", "claude", creds.claude_api_key.strip()))
    if creds.gemini_api_key is not None and creds.gemini_api_key.strip():
        key_validations.append(("gemini_api_key", "gemini", creds.gemini_api_key.strip()))
    if creds.openrouter_api_key is not None and creds.openrouter_api_key.strip():
        key_validations.append(("openrouter_api_key", "openrouter", creds.openrouter_api_key.strip()))

    validation_errors = []
    for field_name, provider_name, raw_key in key_validations:
        if provider_name == "github":
            api_result = await test_github_api(raw_key)
        else:
            api_result = await test_llm_api(provider_name, raw_key)
        if api_result != "Connected":
            friendly_name = {
                "github_pat": "GitHub PAT",
                "groq_api_key": "Groq API Key",
                "openai_api_key": "OpenAI API Key",
                "claude_api_key": "Claude API Key",
                "gemini_api_key": "Gemini API Key",
                "openrouter_api_key": "OpenRouter API Key",
            }.get(field_name, field_name)
            validation_errors.append(f"{friendly_name}: {api_result}")

    if validation_errors:
        error_detail = "The following API keys failed validation:\n" + "\n".join(validation_errors)
        logger.warning(f"Key validation failed for user_id={current_user.id}: {validation_errors}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail
        )

    # ── All keys passed validation — save them ──
    for field_name, provider_name, raw_key in key_validations:
        encrypted = encryptor.encrypt(raw_key)
        setattr(current_user, f"{field_name}_encrypted", encrypted)
        logger.info(f"Saved {field_name}_encrypted (length={len(encrypted)})")
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
    
    logger.info(f"Credentials committed for user_id={current_user.id}")
    
    # Log which fields are now set
    logger.info(f"Post-save — github_pat: {bool(current_user.github_pat_encrypted)}, groq: {bool(current_user.groq_api_key_encrypted)}, openai: {bool(current_user.openai_api_key_encrypted)}")
    
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
async def get_diagnostics(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """Return only configured/not-configured status for each provider. Never show server env values."""
    logger.info(f"get_diagnostics called for user_id={current_user.id}")
    logger.info(f"Raw encrypted fields — github: {bool(current_user.github_pat_encrypted)}, groq: {bool(current_user.groq_api_key_encrypted)}, openai: {bool(current_user.openai_api_key_encrypted)}")
    
    # Check GitHub PAT — 3-state: Configured / Invalid / Missing
    github_pat_configured = check_key_configured(current_user.github_pat_encrypted)
    github_api_status = "Missing Key"
    if github_pat_configured:
        token = get_decrypted_key(current_user.github_pat_encrypted)
        if token:
            github_api_status = await test_github_api(token)
    else:
        github_api_status = "Missing Key"

    # Build providers_status with actual API testing
    providers_status = {}
    
    # GitHub — 3-state: Configured / Invalid / Missing
    if not github_pat_configured:
        github_status_label = "Missing"
    elif github_api_status == "Connected":
        github_status_label = "Configured"
    else:
        github_status_label = "Invalid"
    providers_status["github"] = {
        "configured": github_pat_configured and (github_api_status == "Connected"),
        "status": github_status_label,
        "api_status": github_api_status
    }
    
    # LLM providers — test with actual API calls, 3-state status
    llm_providers = ["groq", "openai", "claude", "gemini", "openrouter"]
    encrypted_fields = {
        "groq": current_user.groq_api_key_encrypted,
        "openai": current_user.openai_api_key_encrypted,
        "claude": current_user.claude_api_key_encrypted,
        "gemini": current_user.gemini_api_key_encrypted,
        "openrouter": current_user.openrouter_api_key_encrypted,
    }
    
    for provider in llm_providers:
        encrypted = encrypted_fields[provider]
        configured = check_key_configured(encrypted)
        api_status = "Missing Key"
        if configured:
            api_key = get_decrypted_key(encrypted)
            if api_key:
                api_status = await test_llm_api(provider, api_key)
        # Determine 3-state status
        if not configured:
            status_label = "Missing"
        elif api_status == "Connected":
            status_label = "Configured"
        else:
            status_label = "Invalid"
        providers_status[provider] = {
            "configured": configured and (api_status == "Connected"),
            "status": status_label,
            "api_status": api_status
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
    r = None
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL, socket_timeout=3, socket_connect_timeout=3)
        await r.ping()
        redis_status = "Connected"
    except Exception as e:
        redis_status = f"Error: {str(e)}"
    finally:
        if r is not None:
            try:
                await r.aclose()
            except Exception:
                pass

    # JWT status
    jwt_status = "Active" if settings.SECRET_KEY else "Inactive"

    # Encryption status
    encryption_status = "Active (AES-256)" if settings.ENCRYPTION_KEY else "Inactive"

    # Include last_tested timestamps from user model
    verified_at = current_user.credentials_verified_at or {}
    for provider_key in providers_status:
        providers_status[provider_key]["last_tested"] = verified_at.get(provider_key)

    return {
        "providers": providers_status,
        "encryption_status": encryption_status,
        "database_status": db_status,
        "redis_status": redis_status,
        "jwt_status": jwt_status
    }

@router.delete("/keys/{provider}", response_model=UserOut)
async def delete_credential(
    provider: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """Delete an encrypted credential by provider name.
    
    Valid providers: github, groq, openai, claude, gemini, openrouter
    """
    provider = provider.lower()
    field_map = {
        "github": "github_pat_encrypted",
        "groq": "groq_api_key_encrypted",
        "openai": "openai_api_key_encrypted",
        "claude": "claude_api_key_encrypted",
        "gemini": "gemini_api_key_encrypted",
        "openrouter": "openrouter_api_key_encrypted",
    }
    column_name = field_map.get(provider)
    if not column_name:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
    
    if not getattr(current_user, column_name):
        raise HTTPException(status_code=404, detail=f"No credential stored for provider: {provider}")
    
    # Wipe the encrypted credential
    setattr(current_user, column_name, None)
    
    # Also remove from verified_at tracking
    verified = current_user.credentials_verified_at or {}
    if provider in verified:
        del verified[provider]
        current_user.credentials_verified_at = verified
    
    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)
    
    logger.info(f"Deleted credential for provider={provider}, user_id={current_user.id}")
    
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


@router.post("/keys/test/{provider}")
async def test_credential(
    provider: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """Test a stored credential against its provider API.
    
    Returns validation status and updates last_tested timestamp.
    """
    provider = provider.lower()
    
    if provider == "github":
        encrypted = current_user.github_pat_encrypted
        if not encrypted:
            raise HTTPException(status_code=404, detail="No GitHub PAT stored")
        raw_key = get_decrypted_key(encrypted)
        if not raw_key:
            raise HTTPException(status_code=400, detail="Failed to decrypt stored credential")
        api_status = await test_github_api(raw_key)
    else:
        field_map = {
            "groq": current_user.groq_api_key_encrypted,
            "openai": current_user.openai_api_key_encrypted,
            "claude": current_user.claude_api_key_encrypted,
            "gemini": current_user.gemini_api_key_encrypted,
            "openrouter": current_user.openrouter_api_key_encrypted,
        }
        encrypted = field_map.get(provider)
        if not encrypted:
            raise HTTPException(status_code=404, detail=f"No credential stored for provider: {provider}")
        raw_key = get_decrypted_key(encrypted)
        if not raw_key:
            raise HTTPException(status_code=400, detail="Failed to decrypt stored credential")
        api_status = await test_llm_api(provider, raw_key)
    
    # Determine status label
    if api_status == "Connected":
        status_label = "Validated"
    else:
        status_label = "Invalid"
    
    # Update last_tested timestamp
    now_iso = datetime.datetime.utcnow().isoformat()
    verified = current_user.credentials_verified_at or {}
    verified[provider] = now_iso
    current_user.credentials_verified_at = verified
    
    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)
    
    return {
        "provider": provider,
        "status": status_label,
        "api_status": api_status,
        "last_tested": now_iso
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
            avg_health_score=0.0,
            security_score=0.0,
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
        .order_by(Analysis.timestamp.desc())
        .limit(20)
    )
    health_history = [
        {"repo": row[0], "date": row[1].strftime("%Y-%m-%d %H:%M"), "score": row[2]}
        for row in health_history_res.all()
    ]
    # Reverse to chronological order for chart display (oldest → newest)
    health_history.reverse()
    
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
        .order_by(Analysis.timestamp.desc())
        .limit(20)
    )
    security_score_history = [
        {"repo": row[0], "date": row[1].strftime("%Y-%m-%d %H:%M"), "score": max(0, 100 - (row[2] or 0))}
        for row in security_score_history_res.all()
    ]
    # Reverse to chronological order for chart display (oldest → newest)
    security_score_history.reverse()
    
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