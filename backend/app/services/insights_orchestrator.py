"""
Insights Orchestrator — runs every deterministic insight analyzer against
the repository during a scan and persists the results.

Called from the scan pipeline (tasks.py) right after findings are saved.
Every analyzer is wrapped in try/except: a failure in any single insight
must never fail or block the main repository scan.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.models import (
    Analysis, Repository,
    SecurityFinding, CodeSmell, HealthScore,
    DependencyFinding, DuplicateCodeFinding, TechnicalDebtFinding,
    ArchitectureAnalysis, ComplexityFinding, RepositoryHealthSnapshot,
)
from app.services.source_fetcher import RepoSourceFetcher
from app.services.dependency_scanner import scan_dependencies
from app.services.duplicate_detector import detect_duplicates
from app.services.complexity_analyzer import analyze_files
from app.services.architecture_analyzer import analyze_architecture
from app.services.technical_debt_analyzer import build_technical_debt_report
from app.utils.logger import get_logger

logger = get_logger("insights_orchestrator")

# Duplicate detection parameter defaults (documented in API response).
DEFAULT_MIN_SIMILARITY = 70
DEFAULT_MIN_BLOCK_LINES = 6


def _severity_counts(findings: list) -> dict:
    counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0, "Info": 0}
    for f in findings:
        sev = getattr(f, "severity", None) or (f.get("severity") if isinstance(f, dict) else None)
        if sev in counts:
            counts[sev] += 1
    return counts


def compute_health_snapshot_values(db, analysis_id) -> dict | None:
    """Compute the health-snapshot metric values from data already persisted
    for this analysis. Deterministic — derived from stored rows only."""
    try:
        sec = db.query(SecurityFinding).filter(SecurityFinding.analysis_id == analysis_id).all()
        smells = db.query(CodeSmell).filter(CodeSmell.analysis_id == analysis_id).all()
        health = db.query(HealthScore).filter(HealthScore.analysis_id == analysis_id).first()

        counts = _severity_counts(sec)
        total = sum(counts.values())

        # Security score: 100 minus severity penalties (transparent formula)
        security_score = max(0, min(
            100,
            100 - 25 * counts["Critical"] - 15 * counts["High"] - 6 * counts["Medium"] - 1 * counts["Low"],
        ))
        # Code quality score: 100 minus smell penalties
        smell_counts = _severity_counts(smells)
        code_quality = max(0, min(
            100,
            100 - 8 * smell_counts["Critical"] - 5 * smell_counts["High"] - 2 * smell_counts["Medium"],
        ))

        return {
            "health_score": health.health_score if health else max(0, min(100, 100 - (total * 2))),
            "security_score": security_score,
            "code_quality_score": code_quality,
            "code_smell_count": len(smells),
            "critical_count": counts["Critical"],
            "high_count": counts["High"],
            "medium_count": counts["Medium"],
            "low_count": counts["Low"],
            "total_issue_count": total + len(smells),
        }
    except Exception as exc:
        logger.error(f"Failed to compute health snapshot values: {exc}", exc_info=True)
        return None


def persist_health_snapshot(db, analysis_id, repo_id, commit_sha: str | None) -> None:
    """Create a RepositoryHealthSnapshot for a completed repository scan."""
    try:
        existing = db.query(RepositoryHealthSnapshot).filter(
            RepositoryHealthSnapshot.analysis_id == analysis_id
        ).first()
        if existing:
            logger.info(f"Health snapshot already exists for analysis {analysis_id}; skipping duplicate.")
            return

        analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
        values = compute_health_snapshot_values(db, analysis_id)
        if values is None:
            return

        snapshot = RepositoryHealthSnapshot(
            repository_id=repo_id,
            analysis_id=analysis_id,
            branch=(analysis.repository.default_branch if analysis and analysis.repository else None),
            commit_sha=commit_sha,
            created_at=datetime.now(timezone.utc),
            **values,
        )
        db.add(snapshot)
        db.commit()
        logger.info(f"Health snapshot persisted for analysis {analysis_id} (score: {values['health_score']}).")
    except Exception as exc:
        logger.error(f"Failed to persist health snapshot: {exc}", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass


def run_all_insights(db, analysis_id, repository: Repository, github_service, commit_sha: str | None = None) -> dict:
    """Run all deterministic insight analyzers and persist their results.

    Returns a dict of per-insight status info (for logging/debugging).
    Individual failures are logged and skipped — the scan itself continues.
    """
    status: dict = {}

    fetcher = RepoSourceFetcher(github_service, repository.name)

    # ── 1. Dependencies ────────────────────────────────────────────
    try:
        dep_result = scan_dependencies(fetcher)
        for f in dep_result["findings"]:
            db.add(DependencyFinding(
                analysis_id=analysis_id,
                ecosystem=f["ecosystem"],
                manifest_file=f["manifest_file"],
                package_name=f["package_name"],
                version_spec=f.get("version_spec"),
                resolved_version=f.get("resolved_version"),
                status=f["status"],
                severity=f.get("severity"),
                advisory_id=f.get("advisory_id"),
                vulnerable_range=f.get("vulnerable_range"),
                recommended_version=f.get("recommended_version"),
                advisory_url=f.get("advisory_url"),
                evidence=f.get("evidence"),
            ))
        db.commit()
        status["dependencies"] = {
            "ok": True,
            "total": dep_result["summary"]["total"],
            "vulnerable": dep_result["summary"]["known_vulnerable"],
            "manifests": len(dep_result["manifests_scanned"]),
        }
    except Exception as exc:
        logger.error(f"Dependency insight failed (non-fatal): {exc}", exc_info=True)
        db.rollback()
        status["dependencies"] = {"ok": False, "error": str(exc)[:200]}

    # ── 2. Duplicates ──────────────────────────────────────────────
    try:
        source_files = fetcher.fetch_source_files()
        dup_result = detect_duplicates(
            source_files,
            min_lines=DEFAULT_MIN_BLOCK_LINES,
            min_similarity=DEFAULT_MIN_SIMILARITY,
        )
        for d in dup_result["findings"]:
            db.add(DuplicateCodeFinding(
                analysis_id=analysis_id,
                file_a=d["file_a"], start_line_a=d["start_line_a"], end_line_a=d["end_line_a"],
                file_b=d["file_b"], start_line_b=d["start_line_b"], end_line_b=d["end_line_b"],
                similarity=d["similarity"], duplicated_lines=d["duplicated_lines"],
                token_hash=d["token_hash"], snippet=d["snippet"],
            ))
        db.commit()
        status["duplicates"] = {"ok": True, "count": len(dup_result["findings"]), "files_analyzed": dup_result["files_analyzed"]}
    except Exception as exc:
        logger.error(f"Duplicate insight failed (non-fatal): {exc}", exc_info=True)
        db.rollback()
        status["duplicates"] = {"ok": False, "error": str(exc)[:200]}
        dup_result = {"findings": [], "parameters": {}}

    # ── 3. Complexity ──────────────────────────────────────────────
    try:
        if not source_files:
            source_files = fetcher.fetch_source_files()
        cx_result = analyze_files(source_files)
        for c in cx_result["findings"]:
            db.add(ComplexityFinding(
                analysis_id=analysis_id,
                file=c["file"], name=c["name"], kind=c["kind"],
                line_start=c["line_start"], line_end=c.get("line_end"),
                cyclomatic_complexity=c["cyclomatic_complexity"],
                nesting_depth=c.get("nesting_depth"),
                length_lines=c.get("length_lines"),
                language=c.get("language"),
                severity=c["severity"],
                explanation=c.get("explanation"),
                suggestion=c.get("suggestion"),
            ))
        db.commit()
        status["complexity"] = {"ok": True, "reported": cx_result["summary"]["reported"]}
    except Exception as exc:
        logger.error(f"Complexity insight failed (non-fatal): {exc}", exc_info=True)
        db.rollback()
        status["complexity"] = {"ok": False, "error": str(exc)[:200]}
        cx_result = {"findings": [], "summary": {}}

    # ── 4. Architecture ────────────────────────────────────────────
    try:
        arch_result = analyze_architecture(fetcher)
        db.add(ArchitectureAnalysis(analysis_id=analysis_id, result=arch_result))
        db.commit()
        status["architecture"] = {
            "ok": True,
            "frameworks": len(arch_result.get("frameworks", [])),
            "concerns": len(arch_result.get("concerns", [])),
        }
    except Exception as exc:
        logger.error(f"Architecture insight failed (non-fatal): {exc}", exc_info=True)
        db.rollback()
        status["architecture"] = {"ok": False, "error": str(exc)[:200]}
        arch_result = {}

    # ── 5. Technical debt (needs persisted findings from this scan) ─
    try:
        sec_rows = db.query(SecurityFinding).filter(SecurityFinding.analysis_id == analysis_id).all()
        smell_rows = db.query(CodeSmell).filter(CodeSmell.analysis_id == analysis_id).all()
        sec_dicts = [{
            "severity": s.severity, "issue": s.issue, "file": s.file, "line": s.line,
        } for s in sec_rows]
        smell_dicts = [{
            "severity": s.severity, "issue": s.issue, "file": s.file, "line": s.line,
        } for s in smell_rows]

        debt_result = build_technical_debt_report(
            security_findings=sec_dicts,
            code_smells=smell_dicts,
            duplicates=dup_result,
            complexity=cx_result,
            source_files=source_files,
            dependencies=dep_result,
        )
        for item in debt_result["items"]:
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
        status["technical_debt"] = {"ok": True, "items": len(debt_result["items"])}
    except Exception as exc:
        logger.error(f"Technical debt insight failed (non-fatal): {exc}", exc_info=True)
        db.rollback()
        status["technical_debt"] = {"ok": False, "error": str(exc)[:200]}

    # ── 6. Health snapshot ─────────────────────────────────────────
    try:
        persist_health_snapshot(db, analysis_id, repository.id, commit_sha)
        status["health_snapshot"] = {"ok": True}
    except Exception as exc:
        logger.error(f"Health snapshot insight failed (non-fatal): {exc}", exc_info=True)
        status["health_snapshot"] = {"ok": False, "error": str(exc)[:200]}

    return status
