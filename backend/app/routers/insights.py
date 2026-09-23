"""
Insights Router — authenticated API for the 8 repository insight features:

1. GET  /repositories/{id}/health-trend
2. GET  /repositories/{id}/dependencies
3. GET  /repositories/{id}/duplicates
4. GET  /repositories/{id}/technical-debt
5. GET  /repositories/{id}/architecture
6. GET  /repositories/{id}/complexity
7. GET  /repositories/{id}/pull-requests
        POST /repositories/{id}/pull-requests/{pr_number}/review
8. GET  /repositories/{id}/commits
        POST /repositories/{id}/commits/{sha}/analyze

All endpoints verify repository ownership via the authenticated user and
follow the existing router patterns (get_current_user + get_async_db).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
import uuid

from app.database.database import get_async_db
from app.models.models import (
    User, Repository, Analysis,
    DependencyFinding, DuplicateCodeFinding, TechnicalDebtFinding,
    ArchitectureAnalysis, ComplexityFinding, RepositoryHealthSnapshot,
    PullRequestReview, CommitAnalysis,
)
from app.auth.security import get_current_user
from app.auth.encryption import encryptor
from app.services.github_service import GitHubService
from app.services.commit_analyzer import analyze_commit, list_recent_commits, get_commit_details
from app.services.insights_orchestrator import DEFAULT_MIN_SIMILARITY, DEFAULT_MIN_BLOCK_LINES
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger("insights_router")

router = APIRouter(prefix="/repositories", tags=["Insights"])


# ── Helpers ───────────────────────────────────────────────────────────

async def _get_owned_repo(
    repo_id: uuid.UUID,
    current_user: User,
    db: AsyncSession,
) -> Repository:
    result = await db.execute(
        select(Repository).where(
            (Repository.id == repo_id) & (Repository.user_id == current_user.id)
        )
    )
    repo = result.scalars().first()
    if not repo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found.")
    return repo


async def _latest_completed_analysis(db: AsyncSession, repo_id: uuid.UUID) -> Optional[Analysis]:
    result = await db.execute(
        select(Analysis)
        .where(
            (Analysis.repository_id == repo_id)
            & (Analysis.status == "completed")
            & ((Analysis.is_deleted == False) | (Analysis.is_deleted.is_(None)))
        )
        .order_by(Analysis.timestamp.desc())
        .limit(1)
    )
    return result.scalars().first()


def _github_service_or_403(current_user: User) -> GitHubService:
    pat = encryptor.decrypt(current_user.github_pat_encrypted) if current_user.github_pat_encrypted else settings.GITHUB_TOKEN
    if not pat:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub Personal Access Token is not configured. Add one in Settings."
        )
    return GitHubService(token=pat)


# ══════════════════════════════════════════════════════════════════════
# 1. HEALTH TREND
# ══════════════════════════════════════════════════════════════════════

@router.get("/{id}/health-trend")
async def get_health_trend(
    id: uuid.UUID,
    range: str = Query("all", pattern="^(7|30|all)$", description="Last 7 scans, 30 scans, or all"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    repo = await _get_owned_repo(id, current_user, db)

    limit = None
    if range == "7":
        limit = 7
    elif range == "30":
        limit = 30

    query = (
        select(RepositoryHealthSnapshot)
        .where(RepositoryHealthSnapshot.repository_id == repo.id)
        .order_by(RepositoryHealthSnapshot.created_at.desc())
    )
    if limit:
        query = query.limit(limit)

    result = await db.execute(query)
    snapshots = list(result.scalars().all())
    snapshots.reverse()  # chronological order for chart display

    points = [
        {
            "analysis_id": str(s.analysis_id),
            "timestamp": s.created_at.isoformat() if s.created_at else None,
            "branch": s.branch,
            "commit_sha": s.commit_sha,
            "health_score": s.health_score,
            "security_score": s.security_score,
            "code_quality_score": s.code_quality_score,
            "code_smell_count": s.code_smell_count or 0,
            "critical_count": s.critical_count or 0,
            "high_count": s.high_count or 0,
            "medium_count": s.medium_count or 0,
            "low_count": s.low_count or 0,
            "total_issue_count": s.total_issue_count or 0,
        }
        for s in snapshots
    ]

    trend_status = None
    deltas = None
    if len(points) >= 2:
        first, last = points[0], points[-1]

        def delta(a, b, lower_is_better):
            if a is None or b is None or a == b:
                return 0
            if lower_is_better:
                return 1 if b < a else (-1 if b > a else 0)
            return 1 if b > a else -1

        deltas = {
            "health_score": {"from": first["health_score"], "to": last["health_score"],
                             "direction": delta(first["health_score"], last["health_score"], False)},
            "security_score": {"from": first["security_score"], "to": last["security_score"],
                               "direction": delta(first["security_score"], last["security_score"], False)},
            "code_quality_score": {"from": first["code_quality_score"], "to": last["code_quality_score"],
                                   "direction": delta(first["code_quality_score"], last["code_quality_score"], False)},
            "total_issue_count": {"from": first["total_issue_count"], "to": last["total_issue_count"],
                                  "direction": delta(first["total_issue_count"], last["total_issue_count"], True)},
        }
        if all(d["direction"] == 0 for d in deltas.values()):
            trend_status = "no_change"
        elif any(d["direction"] > 0 for d in deltas.values()) and not any(d["direction"] < 0 for d in deltas.values()):
            trend_status = "improved"
        elif any(d["direction"] < 0 for d in deltas.values()) and not any(d["direction"] > 0 for d in deltas.values()):
            trend_status = "declined"
        else:
            trend_status = "mixed"

    return {
        "repository_id": str(repo.id),
        "snapshot_count": len(points),
        "available_snapshots": len(points),
        "range": range,
        "sufficient_data": len(points) >= 2,
        "message": None if len(points) >= 2 else "Trend analysis requires multiple scans.",
        "trend_status": trend_status,
        "deltas": deltas,
        "points": points,
    }


# ══════════════════════════════════════════════════════════════════════
# 2. DEPENDENCIES
# ══════════════════════════════════════════════════════════════════════

@router.get("/{id}/dependencies")
async def get_dependencies(
    id: uuid.UUID,
    severity: Optional[str] = Query(None, description="Filter by severity: Critical|High|Medium|Low"),
    ecosystem: Optional[str] = Query(None, description="Filter by ecosystem: pip|npm|maven|..."),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    repo = await _get_owned_repo(id, current_user, db)
    analysis = await _latest_completed_analysis(db, repo.id)
    if not analysis:
        return {
            "analysis_id": None, "findings": [], "manifests": [], "ecosystems": [],
            "summary": {"total": 0, "known_vulnerable": 0, "outdated": 0, "unknown": 0},
            "message": "No completed scan available. Run a repository scan first.",
        }

    result = await db.execute(
        select(DependencyFinding).where(DependencyFinding.analysis_id == analysis.id)
    )
    rows = list(result.scalars().all())

    def serialize(r: DependencyFinding) -> dict:
        return {
            "id": str(r.id),
            "ecosystem": r.ecosystem,
            "manifest_file": r.manifest_file,
            "package_name": r.package_name,
            "version_spec": r.version_spec,
            "resolved_version": r.resolved_version,
            "status": r.status,
            "severity": r.severity,
            "advisory_id": r.advisory_id,
            "vulnerable_range": r.vulnerable_range,
            "recommended_version": r.recommended_version,
            "advisory_url": r.advisory_url,
            "evidence": r.evidence,
        }

    findings = [serialize(r) for r in rows]
    if severity:
        findings = [f for f in findings if (f["severity"] or "").lower() == severity.lower()]
    if ecosystem:
        findings = [f for f in findings if f["ecosystem"].lower() == ecosystem.lower()]

    all_rows = [serialize(r) for r in rows]
    return {
        "analysis_id": str(analysis.id),
        "generated_at": analysis.timestamp.isoformat() if analysis.timestamp else None,
        "findings": findings,
        "manifests": sorted({f["manifest_file"] for f in all_rows}),
        "ecosystems": sorted({f["ecosystem"] for f in all_rows}),
        "summary": {
            "total": len(all_rows),
            "known_vulnerable": sum(1 for f in all_rows if f["status"] == "known_vulnerable"),
            "outdated": sum(1 for f in all_rows if f["status"] == "outdated"),
            "unknown": sum(1 for f in all_rows if f["status"] == "unknown"),
            "filtered_count": len(findings),
        },
    }


# ══════════════════════════════════════════════════════════════════════
# 3. DUPLICATE CODE
# ══════════════════════════════════════════════════════════════════════

@router.get("/{id}/duplicates")
async def get_duplicates(
    id: uuid.UUID,
    min_similarity: int = Query(DEFAULT_MIN_SIMILARITY, ge=50, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    repo = await _get_owned_repo(id, current_user, db)
    analysis = await _latest_completed_analysis(db, repo.id)
    if not analysis:
        return {
            "analysis_id": None, "findings": [], "groups": 0,
            "parameters": {"min_similarity_pct": min_similarity, "min_block_lines": DEFAULT_MIN_BLOCK_LINES},
            "message": "No completed scan available. Run a repository scan first.",
        }

    result = await db.execute(
        select(DuplicateCodeFinding).where(DuplicateCodeFinding.analysis_id == analysis.id)
    )
    rows = list(result.scalars().all())

    findings = [
        {
            "id": str(r.id),
            "file_a": r.file_a, "start_line_a": r.start_line_a, "end_line_a": r.end_line_a,
            "file_b": r.file_b, "start_line_b": r.start_line_b, "end_line_b": r.end_line_b,
            "similarity": r.similarity,
            "duplicated_lines": r.duplicated_lines,
            "token_hash": r.token_hash,
            "snippet": r.snippet,
        }
        for r in rows if r.similarity >= min_similarity
    ]
    findings.sort(key=lambda f: (-f["duplicated_lines"], -f["similarity"]))

    return {
        "analysis_id": str(analysis.id),
        "findings": findings,
        "groups": len({f["token_hash"] for f in findings if f["token_hash"]}),
        "parameters": {
            "min_similarity_pct": min_similarity,
            "min_block_lines": DEFAULT_MIN_BLOCK_LINES,
            "scan_default_min_similarity": DEFAULT_MIN_SIMILARITY,
        },
        "message": None if findings else (
            "No duplicated code detected at the current threshold."
            if rows else "No duplicate analysis data for this scan."
        ),
    }


# ══════════════════════════════════════════════════════════════════════
# 4. TECHNICAL DEBT
# ══════════════════════════════════════════════════════════════════════

@router.get("/{id}/technical-debt")
async def get_technical_debt(
    id: uuid.UUID,
    category: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    repo = await _get_owned_repo(id, current_user, db)
    analysis = await _latest_completed_analysis(db, repo.id)
    if not analysis:
        return {
            "analysis_id": None, "items": [], "summary": None, "top_impact_areas": [],
            "message": "No completed scan available. Run a repository scan first.",
        }

    result = await db.execute(
        select(TechnicalDebtFinding).where(TechnicalDebtFinding.analysis_id == analysis.id)
    )
    rows = list(result.scalars().all())

    items = [
        {
            "id": str(r.id),
            "category": r.category,
            "severity": r.severity,
            "title": r.title,
            "evidence": r.evidence,
            "file": r.file,
            "line_start": r.line_start,
            "line_end": r.line_end,
            "estimated_effort_hours": r.estimated_effort_hours,
            "remediation": r.remediation,
        }
        for r in rows
    ]
    if category:
        items = [i for i in items if i["category"] == category]

    by_category = {}
    severity_counts = {}
    for i in items:
        by_category[i["category"]] = by_category.get(i["category"], 0) + 1
        severity_counts[i["severity"]] = severity_counts.get(i["severity"], 0) + 1

    return {
        "analysis_id": str(analysis.id),
        "items": items,
        "categories": sorted(by_category.keys()),
        "summary": {
            "item_count": len(items),
            "categories": by_category,
            "severity_counts": severity_counts,
            "total_estimated_effort_hours": round(
                sum(i["estimated_effort_hours"] or 0 for i in items), 1
            ),
            "effort_estimate_note": (
                "Effort figures are heuristic ESTIMATES derived from transparent weights; "
                "they are not measured actuals."
            ),
        },
        "top_impact_areas": [
            {"file": f, "estimated_effort_hours": round(h, 1)}
            for f, h in sorted(
                _file_hours(items).items(), key=lambda kv: -kv[1]
            )[:5]
        ],
        "message": None if items else (
            "No technical debt items detected by the deterministic analyzers for this scan."
        ),
    }


def _file_hours(items: list[dict]) -> dict:
    hours: dict = {}
    for i in items:
        if i.get("file"):
            hours[i["file"]] = hours.get(i["file"], 0) + (i.get("estimated_effort_hours") or 0)
    return hours


# ══════════════════════════════════════════════════════════════════════
# 5. ARCHITECTURE
# ══════════════════════════════════════════════════════════════════════

@router.get("/{id}/architecture")
async def get_architecture(
    id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    repo = await _get_owned_repo(id, current_user, db)
    analysis = await _latest_completed_analysis(db, repo.id)
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No completed scan available. Run a repository scan first."
        )

    result = await db.execute(
        select(ArchitectureAnalysis)
        .where(ArchitectureAnalysis.analysis_id == analysis.id)
        .order_by(ArchitectureAnalysis.created_at.desc())
        .limit(1)
    )
    arch = result.scalars().first()
    if not arch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No architecture analysis stored for the latest scan. Re-run the scan to generate it."
        )

    return {
        "analysis_id": str(analysis.id),
        "generated_at": arch.created_at.isoformat() if arch.created_at else None,
        "result": arch.result,
    }


# ══════════════════════════════════════════════════════════════════════
# 6. COMPLEXITY
# ══════════════════════════════════════════════════════════════════════

@router.get("/{id}/complexity")
async def get_complexity(
    id: uuid.UUID,
    severity: Optional[str] = Query(None, pattern="^(High|Medium|Low)$"),
    language: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    repo = await _get_owned_repo(id, current_user, db)
    analysis = await _latest_completed_analysis(db, repo.id)
    if not analysis:
        return {
            "analysis_id": None, "findings": [], "summary": None,
            "message": "No completed scan available. Run a repository scan first.",
        }

    result = await db.execute(
        select(ComplexityFinding).where(ComplexityFinding.analysis_id == analysis.id)
    )
    rows = list(result.scalars().all())

    all_findings = [
        {
            "id": str(r.id), "file": r.file, "name": r.name, "kind": r.kind,
            "line_start": r.line_start, "line_end": r.line_end,
            "cyclomatic_complexity": r.cyclomatic_complexity,
            "nesting_depth": r.nesting_depth, "length_lines": r.length_lines,
            "language": r.language, "severity": r.severity,
            "explanation": r.explanation, "suggestion": r.suggestion,
        }
        for r in rows
    ]
    findings = all_findings
    if severity:
        findings = [f for f in findings if f["severity"] == severity]
    if language:
        findings = [f for f in findings if (f["language"] or "").lower() == language.lower()]

    findings.sort(key=lambda f: (-f["cyclomatic_complexity"], -(f["length_lines"] or 0)))

    languages = sorted({f["language"] for f in all_findings if f["language"]})
    return {
        "analysis_id": str(analysis.id),
        "findings": findings,
        "languages": languages,
        "summary": {
            "total_reported": len(all_findings),
            "high": sum(1 for f in all_findings if f["severity"] == "High"),
            "medium": sum(1 for f in all_findings if f["severity"] == "Medium"),
            "average_complexity": (
                round(sum(f["cyclomatic_complexity"] for f in all_findings) / len(all_findings), 2)
                if all_findings else 0.0
            ),
            "filtered_count": len(findings),
        },
        "message": None if findings else "No complexity findings above the reporting threshold.",
    }


# ══════════════════════════════════════════════════════════════════════
# 7. PULL REQUEST REVIEWS
# ══════════════════════════════════════════════════════════════════════

@router.get("/{id}/pull-requests")
async def list_pull_requests_for_review(
    id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """List open PRs (via existing GitHub integration) + stored review status."""
    repo = await _get_owned_repo(id, current_user, db)
    github_service = _github_service_or_403(current_user)

    try:
        prs = github_service.get_open_pull_requests(repo.name)
    except Exception as exc:
        logger.error(f"Failed to list PRs for {repo.name}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch pull requests from GitHub: {str(exc)}"
        )

    reviews_res = await db.execute(
        select(PullRequestReview)
        .where(PullRequestReview.repository_id == repo.id)
        .order_by(PullRequestReview.created_at.desc())
    )
    reviews = reviews_res.scalars().all()
    review_by_pr: dict[int, PullRequestReview] = {}
    for r in reviews:
        if r.pr_number not in review_by_pr:
            review_by_pr[r.pr_number] = r

    pr_list = []
    for pr in prs:
        review = review_by_pr.get(pr["number"])
        pr_list.append({
            "number": pr["number"],
            "title": pr["title"],
            "author": pr["author"],
            "state": pr["state"],
            "additions": pr.get("additions", 0),
            "deletions": pr.get("deletions", 0),
            "head_sha": pr.get("head_sha", ""),
            "base_sha": pr.get("base_sha", ""),
            "review": {
                "id": str(review.id),
                "risk_score": review.risk_score,
                "status": review.status,
                "findings_count": len(review.findings_json or []),
                "reviewed_at": review.created_at.isoformat() if review.created_at else None,
            } if review else None,
        })

    return {"repository_id": str(repo.id), "pull_requests": pr_list}


@router.get("/{id}/pull-requests/{pr_number}/review")
async def get_pr_review(
    id: uuid.UUID,
    pr_number: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    repo = await _get_owned_repo(id, current_user, db)
    result = await db.execute(
        select(PullRequestReview)
        .where(
            (PullRequestReview.repository_id == repo.id)
            & (PullRequestReview.pr_number == pr_number)
        )
        .order_by(PullRequestReview.created_at.desc())
        .limit(1)
    )
    review = result.scalars().first()
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No review stored for this PR yet. Trigger a PR review first."
        )
    return {
        "id": str(review.id),
        "repository_id": str(repo.id),
        "pr_number": review.pr_number,
        "title": review.title,
        "description": review.description,
        "author": review.author,
        "base_branch": review.base_branch,
        "head_branch": review.head_branch,
        "head_sha": review.head_sha,
        "risk_score": review.risk_score,
        "summary": review.summary,
        "findings": review.findings_json or [],
        "files_changed": review.files_changed,
        "additions": review.additions,
        "deletions": review.deletions,
        "status": review.status,
        "reviewed_at": review.created_at.isoformat() if review.created_at else None,
    }


@router.post("/{id}/pull-requests/{pr_number}/review")
async def review_pull_request_endpoint(
    id: uuid.UUID,
    pr_number: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Analyze a PR's ACTUAL changes: fetch title/body/branches/files/patches,
    run the deterministic scanners on the diff, then a grounded AI summary.

    Read/analyze-only: nothing is posted to GitHub by this endpoint.
    """
    repo = await _get_owned_repo(id, current_user, db)
    github_service = _github_service_or_403(current_user)

    # ── Fetch real PR data ─────────────────────────────────────────
    try:
        pr_details = github_service.get_pr_details(repo.name, pr_number)
    except Exception as exc:
        logger.error(f"Failed to fetch PR #{pr_number} on {repo.name}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch PR #{pr_number}: {str(exc)}"
        )

    try:
        pr_files = github_service.get_pr_files(repo.name, pr_number)
    except Exception as exc:
        logger.error(f"Failed to fetch PR files for #{pr_number}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch PR changed files: {str(exc)}"
        )

    # PR description via raw API (get_pr_details doesn't include body)
    pr_body = None
    pr_base_branch = pr_head_branch = None
    try:
        client = github_service.get_client_for_repo(repo.name)
        gh_repo = client.get_repo(repo.name)
        pr_obj = gh_repo.get_pull(pr_number)
        pr_body = pr_obj.body or ""
        pr_base_branch = pr_obj.base.ref if pr_obj.base else None
        pr_head_branch = pr_obj.head.ref if pr_obj.head else None
    except Exception as exc:
        logger.warning(f"Could not fetch PR body/branches: {exc}")

    # ── Run deterministic scanners on the real patches ─────────────
    from app.services.static_security_scanner import StaticSecurityAnalyzer
    from app.services.static_code_smell_detector import StaticCodeSmellDetector
    from app.services.github_service import GitHubService as _GS  # for get_modified_lines

    findings: list[dict] = []
    scanned_files = 0
    for f in pr_files:
        filename = f["filename"]
        patch = f.get("patch") or ""
        ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
        lang = {
            ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript",
            ".ts": "TypeScript", ".tsx": "TypeScript", ".java": "Java",
            ".go": "Go", ".rb": "Ruby",
        }.get(ext)
        if not lang or not patch or f.get("status") == "removed":
            continue
        scanned_files += 1
        modified_lines = github_service.get_modified_lines(patch)

        static_sec = StaticSecurityAnalyzer.scan(code=patch, filename=filename, language=lang)
        static_smells = StaticCodeSmellDetector.scan(code=patch, filename=filename, language=lang)

        for sf in static_sec:
            findings.append({
                "file": filename,
                "line": sf.get("line"),
                "severity": sf.get("severity"),
                "issue": sf.get("issue"),
                "explanation": sf.get("why_it_matters"),
                "suggestion": sf.get("suggestion"),
                "source": "deterministic",
                "category": "Security",
            })
        for sm in static_smells:
            findings.append({
                "file": filename,
                "line": sm.get("line"),
                "severity": sm.get("severity"),
                "issue": sm.get("issue"),
                "explanation": sm.get("why_it_matters"),
                "suggestion": sm.get("suggestion"),
                "source": "deterministic",
                "category": "Code Smell",
            })

    counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0, "Info": 0}
    for f in findings:
        sev = f.get("severity")
        if sev in counts:
            counts[sev] += 1
    risk_score = min(100, 25 * counts["Critical"] + 15 * counts["High"] + 6 * counts["Medium"] + counts["Low"])

    # ── Grounded AI summary (optional; deterministic fallback) ─────
    ai_summary = None
    try:
        provider = (current_user.llm_default_provider or "groq").lower().strip()
        _key_map = {
            "groq": current_user.groq_api_key_encrypted,
            "openai": current_user.openai_api_key_encrypted,
            "anthropic": current_user.claude_api_key_encrypted,
            "claude": current_user.claude_api_key_encrypted,
            "gemini": current_user.gemini_api_key_encrypted,
            "openrouter": current_user.openrouter_api_key_encrypted,
        }
        _env_map = {
            "groq": settings.GROQ_API_KEY,
            "openai": settings.OPENAI_API_KEY,
            "anthropic": settings.ANTHROPIC_API_KEY,
            "claude": settings.ANTHROPIC_API_KEY,
            "gemini": settings.GEMINI_API_KEY,
            "openrouter": settings.OPENROUTER_API_KEY,
        }
        enc = _key_map.get(provider)
        llm_key = encryptor.decrypt(enc) if enc else _env_map.get(provider, "")
        if llm_key:
            from app.services.llm_client import build_llm_client, get_model_name, create_chat_completion
            client = build_llm_client(provider, llm_key)
            model = get_model_name(provider, current_user.llm_default_model)

            # Ground the prompt in REAL data only: file names, patch stats,
            # and the deterministic findings actually detected above.
            file_list = "\n".join(
                f"- {f['filename']} ({f.get('status')}, +{f.get('additions', 0)}/-{f.get('deletions', 0)})"
                for f in pr_files[:20]
            )
            finding_lines = "\n".join(
                f"- [{fd['severity']}] {fd['file']}:{fd['line']} — {fd['issue']}"
                for fd in findings[:25]
            ) or "None detected by deterministic scanners."
            diff_stats = ", ".join(f"{f['filename']}" for f in pr_files[:10])

            system_prompt = (
                "You are a senior code reviewer. Summarize a pull request review.\n"
                "STRICT GROUNDING RULES:\n"
                "- Base your summary ONLY on the provided file list, diff statistics and findings.\n"
                "- Do NOT invent files, functions, line numbers, or issues not listed.\n"
                "- If evidence is insufficient for a conclusion, say 'Insufficient repository evidence to determine this.'\n"
                "- Keep it under 250 words, markdown format."
            )
            user_prompt = (
                f"PR #{pr_number}: {pr_details['title']}\n"
                f"Branches: {pr_base_branch} <- {pr_head_branch}\n"
                f"Author: {pr_details['author']}\n"
                f"Files changed ({len(pr_files)}):\n{file_list}\n\n"
                f"Deterministic findings:\n{finding_lines}\n\n"
                f"Risk score: {risk_score}/100 (computed as 25*Critical + 15*High + 6*Medium + 1*Low).\n"
                f"Files: {diff_stats}\n\n"
                "Write: 1) what this PR changes (from the file list), 2) the review "
                "verdict based on the deterministic findings, 3) priority actions."
            )
            completion = create_chat_completion(
                client=client, provider=provider,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model=model,
                temperature=current_user.llm_temperature or 0.3,
            )
            ai_summary = completion.choices[0].message.content
            ai_summary = f"{ai_summary}\n\n*Summary generated by AI ({model}) from the deterministic findings and real PR metadata above.*"
    except Exception as exc:
        logger.warning(f"AI PR summary failed (non-fatal): {exc}")
        ai_summary = (
            f"AI summary unavailable ({str(exc)[:120]}). Deterministic analysis found "
            f"{len(findings)} finding(s) across {scanned_files} changed source file(s). "
            f"Risk score {risk_score}/100."
        )

    # ── Persist the review ─────────────────────────────────────────
    review = PullRequestReview(
        repository_id=repo.id,
        pr_number=pr_number,
        head_sha=pr_details.get("head_sha"),
        base_branch=pr_base_branch,
        head_branch=pr_head_branch,
        author=pr_details.get("author"),
        title=pr_details.get("title"),
        description=pr_body,
        risk_score=risk_score,
        summary=ai_summary,
        findings_json=findings,
        files_changed=len(pr_files),
        additions=pr_details.get("additions", 0),
        deletions=pr_details.get("deletions", 0),
        status="completed",
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)

    logger.info(f"PR review persisted for {repo.name}#{pr_number}: {len(findings)} findings, risk {risk_score}")

    return {
        "id": str(review.id),
        "repository_id": str(repo.id),
        "pr_number": pr_number,
        "title": pr_details.get("title"),
        "description": pr_body,
        "author": pr_details.get("author"),
        "base_branch": pr_base_branch,
        "head_branch": pr_head_branch,
        "head_sha": pr_details.get("head_sha"),
        "risk_score": risk_score,
        "summary": ai_summary,
        "findings": findings,
        "files_changed": len(pr_files),
        "additions": pr_details.get("additions", 0),
        "deletions": pr_details.get("deletions", 0),
        "status": "completed",
        "scanned_source_files": scanned_files,
        "severity_counts": counts,
    }


# ══════════════════════════════════════════════════════════════════════
# 8. COMMIT ANALYSIS
# ══════════════════════════════════════════════════════════════════════

@router.get("/{id}/commits")
async def list_commits(
    id: uuid.UUID,
    branch: Optional[str] = Query(None),
    limit: int = Query(30, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """List real recent commits from GitHub (for selection)."""
    repo = await _get_owned_repo(id, current_user, db)
    github_service = _github_service_or_403(current_user)
    branch = branch or repo.default_branch

    try:
        commits = list_recent_commits(github_service, repo.name, branch, limit=limit)
    except Exception as exc:
        logger.error(f"Failed to list commits for {repo.name}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch commits from GitHub: {str(exc)}"
        )

    # Attach stored-analysis flags
    stored_res = await db.execute(
        select(CommitAnalysis).where(CommitAnalysis.repository_id == repo.id)
    )
    analyzed_shas = {c.commit_sha for c in stored_res.scalars().all()}
    for c in commits:
        c["analyzed"] = c["sha"] in analyzed_shas

    return {
        "repository_id": str(repo.id),
        "branch": branch,
        "commits": commits,
        "message": None if commits else "No commits found on this branch.",
    }


@router.get("/{id}/commits/{sha}/analysis")
async def get_commit_analysis(
    id: uuid.UUID,
    sha: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    repo = await _get_owned_repo(id, current_user, db)
    result = await db.execute(
        select(CommitAnalysis)
        .where(
            (CommitAnalysis.repository_id == repo.id)
            & (CommitAnalysis.commit_sha == sha)
        )
        .order_by(CommitAnalysis.created_at.desc())
        .limit(1)
    )
    stored = result.scalars().first()
    if not stored:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No analysis stored for this commit. Trigger a commit analysis first."
        )
    return {
        "id": str(stored.id),
        "repository_id": str(repo.id),
        "commit_sha": stored.commit_sha,
        "parent_sha": stored.parent_sha,
        "author": stored.author,
        "message": stored.message,
        "committed_at": stored.committed_at.isoformat() if stored.committed_at else None,
        "files_changed": stored.files_changed,
        "additions": stored.additions,
        "deletions": stored.deletions,
        "security_impact": stored.security_impact,
        "quality_impact": stored.quality_impact,
        "code_smells": stored.code_smells_json or [],
        "complexity_findings": stored.complexity_json or [],
        "ai_summary": stored.ai_summary,
        "findings": stored.findings_json or [],
    }


@router.post("/{id}/commits/{sha}/analyze")
async def analyze_commit_endpoint(
    id: uuid.UUID,
    sha: str,
    with_ai_summary: bool = Query(True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Analyze a real commit against its parent: changed files, +/- lines,
    deterministic security/quality findings, measurable complexity changes,
    and an optional grounded AI summary."""
    repo = await _get_owned_repo(id, current_user, db)
    github_service = _github_service_or_403(current_user)

    if len(sha) < 6 or not all(c in "0123456789abcdefABCDEF" for c in sha):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid commit SHA format.")

    try:
        result = analyze_commit(github_service, repo.name, sha)
    except Exception as exc:
        logger.error(f"Commit analysis failed for {repo.name}@{sha}: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to analyze commit: {str(exc)}"
        )

    # ── Optional grounded AI summary ───────────────────────────────
    ai_summary = None
    if with_ai_summary:
        try:
            provider = (current_user.llm_default_provider or "groq").lower().strip()
            _key_map = {
                "groq": current_user.groq_api_key_encrypted,
                "openai": current_user.openai_api_key_encrypted,
                "anthropic": current_user.claude_api_key_encrypted,
                "claude": current_user.claude_api_key_encrypted,
                "gemini": current_user.gemini_api_key_encrypted,
                "openrouter": current_user.openrouter_api_key_encrypted,
            }
            _env_map = {
                "groq": settings.GROQ_API_KEY,
                "openai": settings.OPENAI_API_KEY,
                "anthropic": settings.ANTHROPIC_API_KEY,
                "claude": settings.ANTHROPIC_API_KEY,
                "gemini": settings.GEMINI_API_KEY,
                "openrouter": settings.OPENROUTER_API_KEY,
            }
            enc = _key_map.get(provider)
            llm_key = encryptor.decrypt(enc) if enc else _env_map.get(provider, "")
            if llm_key:
                from app.services.llm_client import build_llm_client, get_model_name, create_chat_completion
                client = build_llm_client(provider, llm_key)
                model = get_model_name(provider, current_user.llm_default_model)

                file_summary = "\n".join(
                    f"- {f['filename']} ({f['status']}, +{f['additions']}/-{f['deletions']})"
                    for f in result["files"][:20]
                )
                finding_lines = "\n".join(
                    f"- [{s['severity']}] {s['file']}:{s['line']} — {s['issue']}"
                    for s in (result["security_findings"] + result["code_smells"])[:25]
                ) or "None detected by deterministic scanners."

                system_prompt = (
                    "You are a senior engineer explaining a single commit's changes.\n"
                    "STRICT GROUNDING RULES:\n"
                    "- Base your summary ONLY on the provided commit metadata, file list, statistics and findings.\n"
                    "- Do NOT invent files, functions, or issues not listed.\n"
                    "- If evidence is insufficient, say 'Insufficient repository evidence to determine this.'\n"
                    "- Keep it under 200 words, markdown format."
                )
                user_prompt = (
                    f"Commit {result['sha'][:10]} by {result['author']}\n"
                    f"Message: {result['message'][:300]}\n"
                    f"Stats: +{result['additions']}/-{result['deletions']} across {result['files_changed']} file(s)\n"
                    f"Files:\n{file_summary}\n\n"
                    f"Deterministic findings on the added code:\n{finding_lines}\n\n"
                    f"Security impact: {result['security_impact']}\n"
                    f"Quality impact: {result['quality_impact']}\n\n"
                    "Explain what this commit does and its risk."
                )
                completion = create_chat_completion(
                    client=client, provider=provider,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    model=model,
                    temperature=current_user.llm_temperature or 0.3,
                )
                ai_summary = completion.choices[0].message.content
                ai_summary = f"{ai_summary}\n\n*AI summary ({model}) grounded in the commit metadata and deterministic findings above.*"
        except Exception as exc:
            logger.warning(f"AI commit summary failed (non-fatal): {exc}")
            ai_summary = None

    if not ai_summary:
        ai_summary = (
            f"Commit {result['sha'][:10]} changes {result['files_changed']} file(s) "
            f"(+{result['additions']}/-{result['deletions']}). {result['security_impact']} "
            f"{result['quality_impact']}"
        )

    # ── Persist (upsert by latest) ─────────────────────────────────
    existing_res = await db.execute(
        select(CommitAnalysis)
        .where(
            (CommitAnalysis.repository_id == repo.id)
            & (CommitAnalysis.commit_sha == result["sha"])
        )
        .order_by(CommitAnalysis.created_at.desc())
        .limit(1)
    )
    stored = existing_res.scalars().first()
    if not stored:
        stored = CommitAnalysis(repository_id=repo.id, commit_sha=result["sha"])
        db.add(stored)

    stored.parent_sha = result["parent_sha"]
    stored.author = result["author"]
    stored.message = result["message"]
    stored.files_changed = result["files_changed"]
    stored.additions = result["additions"]
    stored.deletions = result["deletions"]
    stored.security_impact = result["security_impact"]
    stored.quality_impact = result["quality_impact"]
    stored.code_smells_json = result["code_smells"]
    stored.complexity_json = result["complexity_findings"]
    stored.ai_summary = ai_summary
    stored.findings_json = result["security_findings"]

    from datetime import datetime as _dt
    if result.get("committed_at"):
        try:
            stored.committed_at = _dt.fromisoformat(result["committed_at"])
        except ValueError:
            pass

    await db.commit()

    return {
        "repository_id": str(repo.id),
        **{k: result[k] for k in (
            "sha", "parent_sha", "author", "message", "committed_at",
            "files_changed", "additions", "deletions",
            "security_impact", "quality_impact", "scanned_files_count",
        )},
        "files": result["files"],
        "security_findings": result["security_findings"],
        "code_smells": result["code_smells"],
        "complexity_findings": result["complexity_findings"],
        "ai_summary": ai_summary,
    }
