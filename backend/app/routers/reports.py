from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
import uuid
import os

from app.database.database import get_async_db
from app.models.models import (
    User, Report, Analysis, Repository, SecurityFinding, CodeSmell, TestSuggestion, HealthScore
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

