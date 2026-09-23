from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Dict, Any
import uuid

from app.database.database import get_async_db
from app.models.models import User, PullRequest, Repository, Analysis, SecurityFinding, CodeSmell
from app.schemas.schemas import PullRequestOut
from app.auth.security import get_current_user
from app.auth.encryption import encryptor
from app.services.github_service import GitHubService
from app.config import settings

router = APIRouter(prefix="/pull-requests", tags=["Pull Requests"])

@router.get("/{id}", response_model=PullRequestOut)
async def get_pr_details_by_id(
    id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    result = await db.execute(
        select(PullRequest)
        .join(Repository)
        .where((PullRequest.id == id) & (Repository.user_id == current_user.id))
    )
    pr = result.scalars().first()
    if not pr:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pull Request not found.")
    return pr

@router.get("/{id}/files")
async def get_pr_files_with_findings(
    id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    # Load PR & Repository
    result = await db.execute(
        select(PullRequest)
        .join(Repository)
        .where((PullRequest.id == id) & (Repository.user_id == current_user.id))
    )
    pr = result.scalars().first()
    if not pr:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pull Request not found.")
        
    # Get Repository name
    repo_res = await db.execute(select(Repository).where(Repository.id == pr.repository_id))
    repo = repo_res.scalars().first()
    
    # Load files changed via GitHub API
    pat = encryptor.decrypt(current_user.github_pat_encrypted) if current_user.github_pat_encrypted else settings.GITHUB_TOKEN
    try:
        github_service = GitHubService(token=pat)
        files = github_service.get_pr_files(repo.name, pr.number)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch files from GitHub: {str(exc)}"
        )
        
    # Check if there is a completed analysis for this PR
    analysis_res = await db.execute(
        select(Analysis)
        .where((Analysis.pull_request_id == pr.id) & (Analysis.status == "completed"))
        .order_by(Analysis.timestamp.desc())
    )
    latest_analysis = analysis_res.scalars().first()
    
    findings_map = {}
    if latest_analysis:
        # Load Security findings
        sec_res = await db.execute(
            select(SecurityFinding).where(SecurityFinding.analysis_id == latest_analysis.id)
        )
        for f in sec_res.scalars().all():
            findings_map.setdefault(f.file, []).append({
                "id": str(f.id),
                "line": f.line,
                "severity": f.severity,
                "category": "Security",
                "issue": f.issue,
                "why_it_matters": f.why_it_matters,
                "suggestion": f.suggestion,
                "before_code": f.before_code,
                "after_code": f.after_code
            })
            
        # Load Code quality smells
        smell_res = await db.execute(
            select(CodeSmell).where(CodeSmell.analysis_id == latest_analysis.id)
        )
        for f in smell_res.scalars().all():
            findings_map.setdefault(f.file, []).append({
                "id": str(f.id),
                "line": f.line,
                "severity": f.severity,
                "category": "Code Smell",
                "issue": f.issue,
                "why_it_matters": f.why_it_matters,
                "suggestion": f.suggestion,
                "before_code": f.before_code,
                "after_code": f.after_code
            })
            
    # Attach findings to files list
    files_with_findings = []
    for f in files:
        filename = f["filename"]
        files_with_findings.append({
            "filename": filename,
            "additions": f["additions"],
            "deletions": f["deletions"],
            "changes": f["changes"],
            "status": f["status"],
            "patch": f["patch"],
            "raw_url": f["raw_url"],
            "findings": findings_map.get(filename, [])
        })
        
    return {
        "analysis_id": str(latest_analysis.id) if latest_analysis else None,
        "risk_score": latest_analysis.risk_score if latest_analysis else None,
        "files": files_with_findings
    }

@router.post("/{id}/post-review")
async def post_review_to_github_api(
    id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """Post AI findings back to GitHub PR discussion and inline comments."""
    result = await db.execute(
        select(PullRequest)
        .join(Repository)
        .where((PullRequest.id == id) & (Repository.user_id == current_user.id))
    )
    pr = result.scalars().first()
    if not pr:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pull Request not found.")
        
    repo_res = await db.execute(select(Repository).where(Repository.id == pr.repository_id))
    repo = repo_res.scalars().first()
    
    # Load completed analysis
    analysis_res = await db.execute(
        select(Analysis)
        .where((Analysis.pull_request_id == pr.id) & (Analysis.status == "completed"))
        .order_by(Analysis.timestamp.desc())
    )
    latest_analysis = analysis_res.scalars().first()
    if not latest_analysis:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No completed analysis found to post reviews."
        )
        
    # Get user token
    pat = encryptor.decrypt(current_user.github_pat_encrypted) if current_user.github_pat_encrypted else settings.GITHUB_TOKEN
    if not pat:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub Personal Access Token is required to write back reviews."
        )
        
    github_service = GitHubService(token=pat)
    
    # Load findings to comment
    sec_res = await db.execute(select(SecurityFinding).where(SecurityFinding.analysis_id == latest_analysis.id))
    smell_res = await db.execute(select(CodeSmell).where(CodeSmell.analysis_id == latest_analysis.id))
    
    inline_comments = []
    
    # Format inline review comments
    for sf in sec_res.scalars().all():
        body = f"### ðŸ›¡ï¸ AI Security Finding\n**Issue:** {sf.issue}\n**Severity:** {sf.severity}\n**Why it matters:** {sf.why_it_matters}\n**Recommendation:** {sf.suggestion}"
        if sf.after_code:
            body += f"\n\n```\n{sf.after_code}\n```"
        inline_comments.append({
            "file": sf.file,
            "line": sf.line,
            "body": body
        })
        
    for cs in smell_res.scalars().all():
        body = f"### ðŸ” AI Code Quality Finding\n**Issue:** {cs.issue}\n**Severity:** {cs.severity}\n**Why it matters:** {cs.why_it_matters}\n**Recommendation:** {cs.suggestion}"
        if cs.after_code:
            body += f"\n\n```\n{cs.after_code}\n```"
        inline_comments.append({
            "file": cs.file,
            "line": cs.line,
            "body": body
        })
        
    # Post discussion summary comment
    summary_body = f"## ðŸ¤– AI Code Review Summary\n"
    summary_body += f"- **Risk Score:** {latest_analysis.risk_score}/100\n"
    summary_body += f"- **Security Issues Count:** {len([x for x in inline_comments if 'Security' in x['body']])}\n"
    summary_body += f"- **Maintainability Issues Count:** {len([x for x in inline_comments if 'Quality' in x['body']])}\n"
    summary_body += f"\n*Review generated automatically by RepoLens AI full-stack dashboard.*"
    
    github_service.post_comment(repo.name, pr.number, summary_body)
    
    # Post inline comment annotations
    posted, failed = github_service.post_inline_comments(
        repo.name, pr.number, inline_comments
    )
    
    return {
        "status": "success",
        "posted_inline": posted,
        "failed_inline": failed,
        "message": "Review submitted back to GitHub!"
    }

