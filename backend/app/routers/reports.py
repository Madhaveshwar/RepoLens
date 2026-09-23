from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
import uuid
import os

from app.database.database import get_async_db
from app.models.models import (
    User, Report, Analysis, Repository, SecurityFinding, CodeSmell, TestSuggestion, HealthScore,
    DependencyFinding, DuplicateCodeFinding, TechnicalDebtFinding, ArchitectureAnalysis,
    ComplexityFinding, RepositoryHealthSnapshot,
)
from app.schemas.schemas import ReportOut
from app.auth.security import get_current_user
from app.services.report_generator import (
    generate_markdown_report, generate_json_report, generate_csv_report, generate_pdf_report
)
from app.utils.logger import get_logger

logger = get_logger("reports_router")
router = APIRouter(prefix="/reports", tags=["Reports"])

@router.get("", response_model=List[ReportOut])
async def list_user_reports(
    analysis_id: Optional[uuid.UUID] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    query = select(Report).where(Report.user_id == current_user.id)
    if analysis_id:
        query = query.where(Report.analysis_id == analysis_id)
        
    result = await db.execute(query.order_by(Report.created_at.desc()))
    reports = list(result.scalars().all())
    
    # On-demand report regeneration if files are missing or didn't get created
    if analysis_id:
        an_res = await db.execute(
            select(Analysis)
            .join(Repository)
            .where((Analysis.id == analysis_id) & (Repository.user_id == current_user.id))
        )
        analysis = an_res.scalars().first()
        if analysis and analysis.status == "completed":
            repo_res = await db.execute(select(Repository).where(Repository.id == analysis.repository_id))
            repo = repo_res.scalars().first()
            
            existing_types = {r.type: r for r in reports if os.path.exists(r.filepath)}
            missing_types = [t for t in ["PDF", "Markdown", "JSON", "CSV"] if t not in existing_types]
            
            if missing_types:
                logger.info(f"Dynamically generating missing reports for analysis {analysis_id}: {missing_types}")
                sec_res = await db.execute(select(SecurityFinding).where(SecurityFinding.analysis_id == analysis_id))
                sec_findings = sec_res.scalars().all()
                
                smell_res = await db.execute(select(CodeSmell).where(CodeSmell.analysis_id == analysis_id))
                code_smells = smell_res.scalars().all()
                
                test_res = await db.execute(select(TestSuggestion).where(TestSuggestion.analysis_id == analysis_id))
                test_sugg = test_res.scalars().first()
                test_suggestions = test_sugg.content if test_sugg else "No test suggestions generated."
                
                health_res = await db.execute(select(HealthScore).where(HealthScore.analysis_id == analysis_id))
                health_score_obj = health_res.scalars().first()
                
                generator_findings = []
                for f in sec_findings:
                    generator_findings.append({
                        "file": f.file, "line": f.line, "severity": f.severity, "category": "Security",
                        "issue": f.issue, "why_it_matters": f.why_it_matters or "", "risk_level": f.risk_level or f.severity,
                        "suggestion": f.suggestion, "before_code": f.before_code or "", "after_code": f.after_code or ""
                    })
                for f in code_smells:
                    generator_findings.append({
                        "file": f.file, "line": f.line, "severity": f.severity, "category": "Code Smell",
                        "issue": f.issue, "why_it_matters": f.why_it_matters or "", "risk_level": f.risk_level or f.severity,
                        "suggestion": f.suggestion, "before_code": f.before_code or "", "after_code": f.after_code or ""
                    })
                    
                repo_analysis_data = None
                if health_score_obj:
                    repo_analysis_data = {
                        "health_score": health_score_obj.health_score,
                        "deductions": health_score_obj.deductions or [],
                        "readme_exists": health_score_obj.readme_exists,
                        "large_files": health_score_obj.large_files or [],
                        "security_hotspots": health_score_obj.security_hotspots or [],
                        "missing_tests": health_score_obj.missing_tests or [],
                        "test_files_count": health_score_obj.test_files_count,
                        "source_files_count": health_score_obj.source_files_count,
                        "docstring_coverage": health_score_obj.docstring_coverage,
                        "analysis_report": analysis.insights or "Scan complete."
                    }
                    
                # Calculate fallback scores from actual findings
                sec_count = len(sec_findings)
                smell_count = len(code_smells)
                risk = analysis.risk_score or 0
                report_data = {
                    "repo_name": repo.name if repo else "Local Repo",
                    "pr_number": None,
                    "timestamp": analysis.timestamp.strftime("%Y-%m-%d %H:%M UTC") if analysis.timestamp else "N/A",
                    "risk_score": risk,
                    "findings": generator_findings,
                    "test_suggestions": test_suggestions,
                    "repo_analysis": repo_analysis_data,
                    "files_analyzed_log": [{
                        "file": "regenerated_from_db",
                        "type": "Aggregate",
                        "status": "Analyzed",
                        "findings": len(generator_findings)
                    }],
                    "scores": {
                        "code_quality": max(0, 100 - risk),
                        "security": max(0, 100 - risk - sec_count * 5),
                        "maintainability": max(0, 100 - risk - smell_count * 3),
                        "performance": max(0, 100 - risk),
                        "technical_debt": min(100, risk + sec_count * 3)
                    }
                }

                # ── Evidence-based insight sections (only when data exists) ──
                dep_res = await db.execute(select(DependencyFinding).where(DependencyFinding.analysis_id == analysis_id))
                dep_rows = list(dep_res.scalars().all())
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

                dup_res = await db.execute(select(DuplicateCodeFinding).where(DuplicateCodeFinding.analysis_id == analysis_id))
                dup_rows = list(dup_res.scalars().all())
                if dup_rows:
                    report_data["duplicates"] = {
                        "findings": [{
                            "file_a": d.file_a, "start_line_a": d.start_line_a, "end_line_a": d.end_line_a,
                            "file_b": d.file_b, "start_line_b": d.start_line_b, "end_line_b": d.end_line_b,
                            "similarity": d.similarity, "duplicated_lines": d.duplicated_lines,
                        } for d in dup_rows],
                    }

                debt_res = await db.execute(select(TechnicalDebtFinding).where(TechnicalDebtFinding.analysis_id == analysis_id))
                debt_rows = list(debt_res.scalars().all())
                if debt_rows:
                    report_data["technical_debt"] = {
                        "items": [{
                            "category": t.category, "severity": t.severity, "title": t.title,
                            "evidence": t.evidence, "file": t.file, "line_start": t.line_start,
                            "estimated_effort_hours": t.estimated_effort_hours,
                        } for t in debt_rows],
                        "summary": {
                            "overall_debt_score": None,
                            "total_estimated_effort_hours": round(sum(t.estimated_effort_hours or 0 for t in debt_rows), 1),
                        },
                    }

                arch_res = await db.execute(
                    select(ArchitectureAnalysis)
                    .where(ArchitectureAnalysis.analysis_id == analysis_id)
                    .order_by(ArchitectureAnalysis.created_at.desc())
                    .limit(1)
                )
                arch_row = arch_res.scalars().first()
                if arch_row and isinstance(arch_row.result, dict):
                    report_data["architecture"] = arch_row.result

                cx_res = await db.execute(select(ComplexityFinding).where(ComplexityFinding.analysis_id == analysis_id))
                cx_rows = list(cx_res.scalars().all())
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
                
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                storage_dir = os.path.join(base_dir, "storage")
                os.makedirs(storage_dir, exist_ok=True)
                
                for r_type in missing_types:
                    extension = {"Markdown": "md", "JSON": "json", "CSV": "csv", "PDF": "pdf"}[r_type]
                    filepath = os.path.join(storage_dir, f"report_{analysis_id}.{extension}")
                    try:
                        if r_type == "Markdown":
                            content = generate_markdown_report(report_data)
                            with open(filepath, "w", encoding="utf-8") as f:
                                f.write(content)
                        elif r_type == "JSON":
                            content = generate_json_report(report_data)
                            with open(filepath, "w", encoding="utf-8") as f:
                                f.write(content)
                        elif r_type == "CSV":
                            content = generate_csv_report(report_data)
                            with open(filepath, "w", encoding="utf-8") as f:
                                f.write(content)
                        elif r_type == "PDF":
                            generate_pdf_report(report_data, filepath)
                            
                        # Register/Update report object
                        rep_obj = existing_types.get(r_type)
                        if rep_obj:
                            rep_obj.filepath = filepath
                            db.add(rep_obj)
                        else:
                            new_rep = Report(
                                analysis_id=analysis_id,
                                user_id=current_user.id,
                                type=r_type,
                                filepath=filepath
                            )
                            db.add(new_rep)
                    except Exception as gen_err:
                        logger.error(f"Error generating {r_type} report on the fly: {gen_err}")
                
                await db.commit()
                # Fetch refreshed lists
                result = await db.execute(query.order_by(Report.created_at.desc()))
                reports = list(result.scalars().all())
                
    return reports

@router.get("/{id}", response_class=FileResponse)
async def download_report(
    id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    result = await db.execute(
        select(Report).where((Report.id == id) & (Report.user_id == current_user.id))
    )
    report = result.scalars().first()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found or permission denied."
        )
        
    if not os.path.exists(report.filepath):
        logger.warning(f"Report file {report.filepath} missing on disk. Attempting regeneration.")
        await list_user_reports(analysis_id=report.analysis_id, current_user=current_user, db=db)
        # Re-fetch
        result = await db.execute(
            select(Report).where((Report.id == id) & (Report.user_id == current_user.id))
        )
        report = result.scalars().first()
        if not report or not os.path.exists(report.filepath):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Static report file is missing on the server storage and regeneration failed."
            )
        
    filename = os.path.basename(report.filepath)
    media_types = {
        "PDF": "application/pdf",
        "Markdown": "text/markdown",
        "JSON": "application/json",
        "CSV": "text/csv"
    }
    media_type = media_types.get(report.type, "application/octet-stream")
    
    return FileResponse(
        path=report.filepath,
        filename=filename,
        media_type=media_type
    )

