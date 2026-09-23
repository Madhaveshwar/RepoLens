import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4
import uuid
import os
from fastapi import status, HTTPException
from app.database.database import SessionLocal
from app.models.models import (
    User, Repository, PullRequest, Analysis,
    Report, SecurityFinding, CodeSmell, TestSuggestion, HealthScore
)

def get_auth_headers(client, email="boost@example.com", password="TestPass123"):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password}
    )
    login_resp = client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password}
    )
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

# --- USERS DIAGNOSTICS TESTS ---

@patch("httpx.AsyncClient.get")
def test_users_diagnostics(mock_httpx_get, client):
    headers = get_auth_headers(client, "diag@example.com")

    # Mock success responses
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_httpx_get.return_value = mock_resp

    resp = client.get("/api/v1/users/me/diagnostics", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "providers" in data
    assert "github" in data["providers"]

    # Mock error responses
    mock_resp_error = MagicMock()
    mock_resp_error.status_code = 401
    mock_httpx_get.return_value = mock_resp_error

    # Add credentials to db to hit database code paths
    client.post(
        "/api/v1/users/keys",
        json={"github_pat": "some-db-pat", "groq_api_key": "some-db-groq"},
        headers=headers
    )
    resp = client.get("/api/v1/users/me/diagnostics", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "providers" in data
    assert "database_status" in data
    assert "encryption_status" in data

    # Mock httpx failure/exceptions
    mock_httpx_get.side_effect = Exception("Connection Refused")
    resp = client.get("/api/v1/users/me/diagnostics", headers=headers)
    assert resp.status_code == 200

# --- REPORTS GENERATION AND REGENERATION ---

@patch("app.routers.reports.generate_pdf_report")
def test_reports_dynamic_regeneration(mock_gen_pdf, client):
    headers = get_auth_headers(client, "reports_regen@example.com")
    
    # 1. Seed DB objects
    db = SessionLocal()
    user = db.query(User).filter_by(email="reports_regen@example.com").first()
    
    repo = Repository(user_id=user.id, name="boost/repo", default_branch="main")
    db.add(repo)
    db.commit()
    
    analysis = Analysis(
        repository_id=repo.id,
        status="completed",
        progress=100,
        risk_score=15,
        insights="Mock insights"
    )
    db.add(analysis)
    db.commit()
    
    sf = SecurityFinding(
        analysis_id=analysis.id, file="test.py", line=1, severity="High",
        issue="Test Issue", suggestion="Fix it", before_code="foo", after_code="bar"
    )
    cs = CodeSmell(
        analysis_id=analysis.id, file="test.py", line=2, severity="Medium",
        issue="Smell", suggestion="Refactor", before_code="a", after_code="b"
    )
    ts = TestSuggestion(analysis_id=analysis.id, file="test.py", content="def test_foo(): pass")
    hs = HealthScore(
        analysis_id=analysis.id, health_score=85, deductions=["Smell"],
        readme_exists=True, large_files=[], security_hotspots=[], missing_tests=[]
    )
    db.add(sf)
    db.add(cs)
    db.add(ts)
    db.add(hs)
    db.commit()
    
    analysis_id = str(analysis.id)
    db.close()
    
    # 2. Get reports - triggers dynamic creation since no reports exist in DB or on disk
    resp = client.get(f"/api/v1/reports?analysis_id={analysis_id}", headers=headers)
    assert resp.status_code == 200
    reports = resp.json()
    assert len(reports) == 4  # PDF, Markdown, JSON, CSV
    
    # Check that a PDF report is registered
    pdf_report = [r for r in reports if r["type"] == "PDF"][0]
    pdf_report_id = pdf_report["id"]
    
    # Clean up generated files if they exist on disk to prevent cluttering
    for r in reports:
        db = SessionLocal()
        rep_obj = db.query(Report).filter_by(id=uuid.UUID(r["id"])).first()
        if rep_obj and rep_obj.filepath and os.path.exists(rep_obj.filepath):
            try:
                os.remove(rep_obj.filepath)
            except Exception:
                pass
        db.close()

# --- REPOSITORIES MANAGEMENT ROUTER ---

@patch("app.routers.repositories.GitHubService")
def test_repositories_endpoints_boost(mock_gh_service_class, client):
    headers = get_auth_headers(client, "repo_boost@example.com")
    
    # Seed repo
    db = SessionLocal()
    user = db.query(User).filter_by(email="repo_boost@example.com").first()
    repo = Repository(user_id=user.id, name="boost/repo-endpoints", default_branch="main")
    db.add(repo)
    db.commit()
    repo_id = str(repo.id)
    db.close()
    
    # Mock permissions
    mock_gh = mock_gh_service_class.return_value
    mock_gh_repo = MagicMock()
    mock_gh_repo.permissions = MagicMock()
    mock_gh_repo.permissions.admin = True
    mock_gh_repo.permissions.push = True
    mock_gh_repo.permissions.pull = True
    mock_gh.client.get_repo.return_value = mock_gh_repo
    
    # Test GET /{id}/permissions
    resp = client.get(f"/api/v1/repositories/{repo_id}/permissions", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["push"] is True
    
    # Test POST /{id}/disconnect
    disc_resp = client.post(f"/api/v1/repositories/{repo_id}/disconnect", headers=headers)
    assert disc_resp.status_code == 200
    assert disc_resp.json()["success"] is True
    
    # Test DELETE /{id}
    del_resp = client.delete(f"/api/v1/repositories/{repo_id}", headers=headers)
    assert del_resp.status_code == 200
    assert del_resp.json()["success"] is True

# --- ANALYSIS HISTORY & MANAGEMENT ---

def test_analysis_management_endpoints(client):
    headers = get_auth_headers(client, "analysis_mgmt@example.com")
    
    # Seed DB objects
    db = SessionLocal()
    user = db.query(User).filter_by(email="analysis_mgmt@example.com").first()
    repo = Repository(user_id=user.id, name="mgmt/repo", default_branch="main")
    db.add(repo)
    db.commit()
    
    analysis1 = Analysis(repository_id=repo.id, status="completed", progress=100, risk_score=50)
    analysis2 = Analysis(repository_id=repo.id, status="completed", progress=100, risk_score=40)
    db.add(analysis1)
    db.add(analysis2)
    db.commit()
    
    # Seed findings for comparison
    sf1 = SecurityFinding(analysis_id=analysis1.id, file="main.py", line=1, severity="High", issue="SQLi", suggestion="param")
    sf2 = SecurityFinding(analysis_id=analysis2.id, file="main.py", line=1, severity="High", issue="SQLi", suggestion="param")
    db.add(sf1)
    db.add(sf2)
    db.commit()
    
    an1_id = str(analysis1.id)
    an2_id = str(analysis2.id)
    repo_id = str(repo.id)
    db.close()
    
    # Test GET /{id}/stats
    stats_resp = client.get(f"/api/v1/analyses/{an1_id}/stats", headers=headers)
    assert stats_resp.status_code == 200
    assert "total_tokens" in stats_resp.json()
    
    # Test GET /compare
    comp_resp = client.get(f"/api/v1/analyses/compare?scan_a={an1_id}&scan_b={an2_id}", headers=headers)
    assert comp_resp.status_code == 200
    assert comp_resp.json()["status"] == "Improved"
    
    # Test DELETE /{id}
    del_resp = client.delete(f"/api/v1/analyses/{an1_id}", headers=headers)
    assert del_resp.status_code == 200
    assert del_resp.json()["success"] is True
    
    # Test GET /deleted
    deleted_resp = client.get("/api/v1/analysis/deleted", headers=headers)
    assert deleted_resp.status_code == 200
    assert len(deleted_resp.json()) == 1
    assert deleted_resp.json()[0]["id"] == an1_id
    
    # Test POST /{id}/restore
    restore_resp = client.post(f"/api/v1/analysis/{an1_id}/restore", headers=headers)
    assert restore_resp.status_code == 200
    assert restore_resp.json()["success"] is True
    
    # Test DELETE /repo/{repo_id}
    del_repo_resp = client.delete(f"/api/v1/analyses/repo/{repo_id}", headers=headers)
    assert del_repo_resp.status_code == 200
    assert del_repo_resp.json()["success"] is True
    
    # Test DELETE (delete all analyses)
    del_all_resp = client.delete("/api/v1/analyses", headers=headers)
    assert del_all_resp.status_code == 200
    assert del_all_resp.json()["success"] is True

# --- CELERY TASK WORKER TESTS ---

@patch("app.tasks.tasks.redis_client")
@patch("app.tasks.tasks.GitHubService")
@patch("app.tasks.tasks.build_llm_client")
@patch("app.tasks.tasks.review_entire_repository")
@patch("app.tasks.tasks.os.makedirs")
@patch("app.tasks.tasks.generate_pdf_report")
def test_celery_task_full_repo_scan(
    mock_gen_pdf,
    mock_makedirs,
    mock_review_repo,
    mock_build_groq,
    mock_gh_service,
    mock_redis,
    client
):
    headers = get_auth_headers(client, "celery_full@example.com")
    
    db = SessionLocal()
    user = db.query(User).filter_by(email="celery_full@example.com").first()
    
    repo = Repository(user_id=user.id, name="celery/full-repo", default_branch="main")
    db.add(repo)
    db.commit()
    
    analysis = Analysis(repository_id=repo.id, status="pending", progress=0)
    db.add(analysis)
    db.commit()
    
    analysis_id = str(analysis.id)
    db.close()
    
    # Mock review repo results
    mock_review_repo.return_value = {
        "risk_score": 10,
        "latency_seconds": 12,
        "estimated_token_usage": 1500,
        "files_analyzed_count": 5,
        "characters_analyzed_count": 8000,
        "groq_requests_made": 3,
        "cached_results_used": 1,
        "token_stats": {
            "model_name": "llama-3.3-70b-versatile",
            "prompt_tokens": 800,
            "completion_tokens": 700,
            "total_tokens": 1500
        },
        "findings": [
            {"category": "Security", "file": "main.py", "line": 2, "severity": "High", "issue": "SQLi", "suggestion": "Use param"},
            {"category": "Code Smell", "file": "helper.py", "line": 10, "severity": "Low", "issue": "Dead code", "suggestion": "Remove"}
        ],
        "test_suggestions": "Mock test suggestions content",
        "repo_analysis": {
            "health_score": 92,
            "deductions": ["Low test coverage"],
            "readme_exists": True,
            "large_files": [],
            "security_hotspots": [],
            "missing_tests": [],
            "test_files_count": 1,
            "source_files_count": 4,
            "docstring_coverage": 80,
            "analysis_report": "Clean codebase."
        }
    }
    
    # Call Celery task synchronously
    from app.tasks.tasks import run_analysis_task
    with patch("builtins.open", MagicMock()):
        run_analysis_task(analysis_id)
        
    # Verify results in DB
    db = SessionLocal()
    updated_an = db.query(Analysis).filter_by(id=uuid.UUID(analysis_id)).first()
    assert updated_an.status == "completed"
    assert updated_an.progress == 100
    assert updated_an.risk_score == 10
    
    # Verify report entries
    reports = db.query(Report).filter_by(analysis_id=uuid.UUID(analysis_id)).all()
    assert len(reports) >= 3  # Markdown, JSON, CSV should be added
    
    # Verify findings
    sec_f = db.query(SecurityFinding).filter_by(analysis_id=uuid.UUID(analysis_id)).all()
    assert len(sec_f) == 1
    
    db.close()


@patch("app.tasks.tasks.redis_client")
@patch("app.tasks.tasks.GitHubService")
@patch("app.tasks.tasks.build_llm_client")
@patch("app.tasks.tasks.review_pull_request")
@patch("app.tasks.tasks.os.makedirs")
@patch("app.tasks.tasks.generate_pdf_report")
def test_celery_task_pr_scan(
    mock_gen_pdf,
    mock_makedirs,
    mock_review_pr,
    mock_build_groq,
    mock_gh_service,
    mock_redis,
    client
):
    headers = get_auth_headers(client, "celery_pr@example.com")
    
    db = SessionLocal()
    user = db.query(User).filter_by(email="celery_pr@example.com").first()
    
    repo = Repository(user_id=user.id, name="celery/pr-repo", default_branch="main")
    db.add(repo)
    db.commit()
    
    pr = PullRequest(
        repository_id=repo.id,
        number=45,
        title="Celery PR Title",
        author="john",
        state="open",
        head_sha="sha1",
        base_sha="sha2"
    )
    db.add(pr)
    db.commit()
    
    analysis = Analysis(repository_id=repo.id, pull_request_id=pr.id, status="pending", progress=0)
    db.add(analysis)
    db.commit()
    
    analysis_id = str(analysis.id)
    db.close()
    
    # Mock review PR results
    mock_review_pr.return_value = {
        "risk_score": 25,
        "latency_seconds": 8,
        "estimated_token_usage": 1000,
        "files_analyzed_count": 2,
        "characters_analyzed_count": 3000,
        "groq_requests_made": 2,
        "cached_results_used": 0,
        "token_stats": {
            "model_name": "llama-3.3-70b-versatile",
            "prompt_tokens": 500,
            "completion_tokens": 500,
            "total_tokens": 1000
        },
        "findings": [],
        "scores": {"security": 75}
    }
    
    # Call task
    from app.tasks.tasks import run_analysis_task
    with patch("builtins.open", MagicMock()):
        run_analysis_task(analysis_id)
        
    # Verify completion
    db = SessionLocal()
    updated_an = db.query(Analysis).filter_by(id=uuid.UUID(analysis_id)).first()
    assert updated_an.status == "completed"
    assert updated_an.progress == 100
    db.close()


@patch("app.tasks.tasks.redis_client")
@patch("app.tasks.tasks.GitHubService")
@patch("app.tasks.tasks.build_llm_client")
@patch("app.tasks.tasks.review_entire_repository")
def test_celery_task_failure(
    mock_review_repo,
    mock_build_groq,
    mock_gh_service,
    mock_redis,
    client
):
    headers = get_auth_headers(client, "celery_fail@example.com")
    
    db = SessionLocal()
    user = db.query(User).filter_by(email="celery_fail@example.com").first()
    
    repo = Repository(user_id=user.id, name="celery/fail-repo", default_branch="main")
    db.add(repo)
    db.commit()
    
    analysis = Analysis(repository_id=repo.id, status="pending", progress=0)
    db.add(analysis)
    db.commit()
    
    analysis_id = str(analysis.id)
    db.close()
    
    # Trigger an error during execution
    mock_review_repo.side_effect = Exception("GitHub Rate Limit Exceeded")
    
    from app.tasks.tasks import run_analysis_task
    run_analysis_task(analysis_id)
    
    # Verify status changed to failed in DB
    db = SessionLocal()
    updated_an = db.query(Analysis).filter_by(id=uuid.UUID(analysis_id)).first()
    assert updated_an.status == "failed"
    # The task converts raw errors into user-friendly messages.
    # GitHub-related failures must point the user at their PAT in Settings.
    assert "GitHub token is invalid" in updated_an.insights
    assert "Settings" in updated_an.insights
    db.close()

# --- SECURITY SCANNER & PARSER ---

def test_security_scanner_parse_json_from_llm():
    from app.services.security_scanner import parse_json_from_llm
    
    assert parse_json_from_llm("") == []
    assert parse_json_from_llm(None) == []
    
    # Direct list JSON
    assert parse_json_from_llm('[{"file": "test.py", "severity": "High"}]') == [{"file": "test.py", "severity": "High"}]
    
    # Direct dict JSON
    assert parse_json_from_llm('{"file": "test.py", "severity": "High"}') == [{"file": "test.py", "severity": "High"}]
    
    # Inside markdown block
    assert parse_json_from_llm('```json\n{"file": "test.py"}\n```') == [{"file": "test.py"}]
    
    # Invalid JSON but contains array match
    assert parse_json_from_llm('Random text [\n{"file": "test.py"}\n] random text') == [{"file": "test.py"}]
    
    # Invalid JSON but contains dict match
    assert parse_json_from_llm('Random text {"file": "test.py", "issue": "x"} random text') == [{"file": "test.py", "issue": "x"}]
    
    # Random text with invalid JSON
    assert parse_json_from_llm("This is not JSON at all.") == []

def test_security_scanner_fallback():
    from app.services.security_scanner import scan_security
    
    mock_client = MagicMock()
    # Mock first choice to raise Exception, second to return success
    mock_chat = MagicMock()
    mock_comp1 = MagicMock()
    mock_comp1.choices = [MagicMock()]
    mock_comp1.choices[0].message.content = '[{"file": "main.py", "severity": "High", "issue": "Hardcoded secret found in source code which could lead to credential exposure", "line": 1, "suggestion": "Move the secret to an environment variable and access it via os.getenv() to prevent credential exposure", "why_it_matters": "Hardcoded secrets can be exposed if the repository is compromised"}]'
    
    mock_chat.create.side_effect = [Exception("Groq Llama 70b Rate Limit"), mock_comp1]
    mock_client.chat.completions = mock_chat
    
    findings = scan_security(mock_client, "main.py", "code", "patch", "Python")
    assert len(findings) == 1
    assert findings[0]["severity"] == "High"
    
    # If both fail
    mock_chat.create.side_effect = [Exception("Failed 1"), Exception("Failed 2")]
    with pytest.raises(Exception):
        scan_security(mock_client, "main.py", "code", "patch", "Python")

def test_smell_detector_fallback():
    from app.services.code_smell_detector import detect_code_smells
    
    mock_client = MagicMock()
    mock_chat = MagicMock()
    mock_comp1 = MagicMock()
    mock_comp1.choices = [MagicMock()]
    mock_comp1.choices[0].message.content = '[{"file": "main.py", "severity": "High", "issue": "Long Function detected in source code which affects code readability", "line": 1, "suggestion": "Break this long function into smaller focused functions to improve readability and maintainability of the codebase", "why_it_matters": "Long functions are harder to understand, test, and maintain"}]'
    
    mock_chat.create.side_effect = [Exception("Groq Rate Limit"), mock_comp1]
    mock_client.chat.completions = mock_chat
    
    findings = detect_code_smells(mock_client, "main.py", "code", "patch", "Python")
    assert len(findings) == 1
    assert findings[0]["severity"] == "High"
    
    # If both fail
    mock_chat.create.side_effect = [Exception("Failed 1"), Exception("Failed 2")]
    with pytest.raises(Exception):
        detect_code_smells(mock_client, "main.py", "code", "patch", "Python")


