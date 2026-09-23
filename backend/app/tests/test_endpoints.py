import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4
import uuid
import os
from app.database.database import SessionLocal
from app.models.models import (
    Repository, Analysis, Report, User,
    PullRequest, SecurityFinding, CodeSmell, HealthScore
)

# Helpers to register and login user
def get_auth_headers(client, email="testendpoints@example.com", password="TestPass123"):
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

# --- AUTH & USER ROUTERS ---

def test_register_duplicate_email(client):
    email = "dup@example.com"
    password = "Password123"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password}
    )
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password}
    )
    assert resp.status_code == 400
    assert "already exists" in resp.json()["detail"].lower()

def test_login_invalid_credentials(client):
    email = "invalid@example.com"
    password = "WrongPass999"
    resp = client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password}
    )
    assert resp.status_code == 401
    assert "incorrect email or password" in resp.json()["detail"].lower()

def test_users_me_profile(client):
    headers = get_auth_headers(client, "profile@example.com")
    resp = client.get("/api/v1/users/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "profile@example.com"

@patch("app.routers.users.test_github_api", return_value="Connected")
@patch("app.routers.users.test_llm_api", return_value="Connected")
def test_users_keys_update(mock_llm, mock_github, client):
    headers = get_auth_headers(client, "keys@example.com")
    resp = client.post(
        "/api/v1/users/keys",
        json={"github_pat": "my-github-pat", "groq_api_key": "my-groq-key"},
        headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["has_github_pat"] is True
    assert resp.json()["has_groq_api_key"] is True

def test_users_dashboard_metrics(client):
    headers = get_auth_headers(client, "dash@example.com")
    resp = client.get("/api/v1/users/me/dashboard", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "repositories_count" in data
    assert "avg_health_score" in data

# --- REPOSITORIES ROUTER ---

@patch("app.routers.repositories.GitHubService")
def test_connect_repository_success(mock_gh_service_class, client):
    headers = get_auth_headers(client, "repo@example.com")
    mock_gh = mock_gh_service_class.return_value
    mock_gh.get_repo_details.return_value = {
        "name": "testowner/testrepo",
        "description": "test desc",
        "stars": 15,
        "forks": 3,
        "open_prs_count": 1,
        "open_issues_count": 4,
        "default_branch": "main",
        "languages": {"Python": 90}
    }
    mock_gh.get_open_pull_requests.return_value = [
        {"number": 1, "title": "Test PR"}
    ]
    mock_gh.get_pr_details.return_value = {
        "number": 1,
        "title": "Test PR",
        "author": "author",
        "state": "open",
        "additions": 10,
        "deletions": 5,
        "head_sha": "headsha123",
        "base_sha": "basesha123"
    }

    resp = client.post(
        "/api/v1/repositories",
        json={"url": "https://github.com/testowner/testrepo"},
        headers=headers
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "testowner/testrepo"

    # List Connected Repositories
    list_resp = client.get("/api/v1/repositories", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1
    repo_id = list_resp.json()[0]["id"]

    # Get Single Repository Details
    detail_resp = client.get(f"/api/v1/repositories/{repo_id}", headers=headers)
    assert detail_resp.status_code == 200
    assert detail_resp.json()["name"] == "testowner/testrepo"

    # Get Repo PRs list (sync mock)
    mock_gh.get_open_pull_requests.return_value = []
    prs_resp = client.get(f"/api/v1/repositories/{repo_id}/prs", headers=headers)
    assert prs_resp.status_code == 200

# --- ANALYSIS ROUTER ---

@patch("app.routers.analysis.enqueue_analysis_task")
@patch("app.services.github_service.GitHubService")
def test_trigger_analysis_endpoints(mock_gh_analysis_class, mock_task, client):
    headers = get_auth_headers(client, "analysis@example.com")
    
    # Mock GitHubService for analysis validation
    mock_gh_analysis = mock_gh_analysis_class.return_value
    mock_gh_repo = MagicMock()
    mock_gh_repo.permissions = MagicMock()
    mock_gh_repo.permissions.pull = True
    mock_gh_analysis.client.get_repo.return_value = mock_gh_repo

    
    # 1. Connect Repo First
    with patch("app.routers.repositories.GitHubService") as mock_gh_class:
        mock_gh = mock_gh_class.return_value
        mock_gh.get_repo_details.return_value = {
            "name": "org/repo",
            "description": "desc",
            "stars": 0, "forks": 0, "open_prs_count": 0, "open_issues_count": 0,
            "default_branch": "main", "languages": {}
        }
        mock_gh.get_open_pull_requests.return_value = []
        repo_resp = client.post(
            "/api/v1/repositories",
            json={"url": "org/repo"},
            headers=headers
        )
        repo_id = repo_resp.json()["id"]

    # 2. Trigger Analysis
    trigger_resp = client.post(
        "/api/v1/analysis/trigger",
        json={"repository_id": repo_id},
        headers=headers
    )
    assert trigger_resp.status_code == 202
    analysis_id = trigger_resp.json()["id"]

    # 3. Retrieve analysis details
    get_resp = client.get(f"/api/v1/analysis/{analysis_id}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "pending"

    # 4. List analyses by repo
    list_resp = client.get(f"/api/v1/analysis/repo/{repo_id}", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

# Local Review endpoints were removed; review_single_code_snippet remains only as a
# shared helper for /analysis/validate-fix-code.

# --- REPORTS ROUTER ---

def test_download_report_endpoints(client):
    headers = get_auth_headers(client, "reports@example.com")
    
    # List reports (empty initially)
    list_resp = client.get("/api/v1/reports", headers=headers)
    assert list_resp.status_code == 200
    assert isinstance(list_resp.json(), list)

    # Seed dummy repository & analysis & report in DB
    db = SessionLocal()
    user = db.query(User).filter_by(email="reports@example.com").first()
    
    repo = Repository(user_id=user.id, name="owner/repo", default_branch="main")
    db.add(repo)
    db.commit()
    
    analysis = Analysis(repository_id=repo.id, status="completed", progress=100)
    db.add(analysis)
    db.commit()

    # Create dummy local file
    file_path = "test_report_file.pdf"
    with open(file_path, "w") as f:
        f.write("PDF Content Mock")

    report = Report(
        analysis_id=analysis.id,
        user_id=user.id,
        type="PDF",
        filepath=os.path.abspath(file_path)
    )
    db.add(report)
    db.commit()
    report_id = str(report.id)
    db.close()

    # Request PDF download
    dl_resp = client.get(f"/api/v1/reports/{report_id}", headers=headers)
    assert dl_resp.status_code == 200
    assert dl_resp.headers["content-type"] == "application/pdf"
    
    # Cleanup
    if os.path.exists(file_path):
        os.remove(file_path)

# --- SECURITY, CODE QUALITY, TESTS ROUTERS ---

def test_findings_details_endpoints(client):
    headers = get_auth_headers(client, "findings@example.com")
    
    # Seed DB analysis first to avoid 404
    db = SessionLocal()
    user = db.query(User).filter_by(email="findings@example.com").first()
    repo = Repository(user_id=user.id, name="owner/repo", default_branch="main")
    db.add(repo)
    db.commit()
    analysis = Analysis(repository_id=repo.id, status="completed", progress=100)
    db.add(analysis)
    db.commit()
    analysis_id = str(analysis.id)
    db.close()

    resp1 = client.get(f"/api/v1/security/analysis/{analysis_id}", headers=headers)
    assert resp1.status_code == 200
    assert isinstance(resp1.json(), list)

    resp2 = client.get(f"/api/v1/code-quality/analysis/{analysis_id}", headers=headers)
    assert resp2.status_code == 200
    assert isinstance(resp2.json(), list)

    resp3 = client.get(f"/api/v1/tests/analysis/{analysis_id}", headers=headers)
    assert resp3.status_code == 200
    assert isinstance(resp3.json(), list)

# --- HEALTH ROUTER ---

def test_health_check_endpoint(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert "status" in resp.json()
    assert "api" in resp.json()


# --- PULL REQUESTS ROUTER ---

@patch("app.routers.pull_requests.GitHubService")
def test_pull_requests_endpoints(mock_gh_service_class, client):
    headers = get_auth_headers(client, "prs@example.com")
    
    # Seed DB objects
    db = SessionLocal()
    user = db.query(User).filter_by(email="prs@example.com").first()
    repo = Repository(user_id=user.id, name="owner/repo", default_branch="main")
    db.add(repo)
    db.commit()
    
    pr = PullRequest(
        repository_id=repo.id,
        number=101,
        title="My PR Title",
        author="someone",
        state="open",
        additions=20,
        deletions=5,
        head_sha="head123",
        base_sha="base123"
    )
    db.add(pr)
    db.commit()
    
    analysis = Analysis(repository_id=repo.id, pull_request_id=pr.id, status="completed", progress=100, risk_score=15)
    db.add(analysis)
    db.commit()
    
    sf = SecurityFinding(analysis_id=analysis.id, file="main.py", line=5, severity="High", issue="SQLi", suggestion="param", before_code="", after_code="")
    cs = CodeSmell(analysis_id=analysis.id, file="main.py", line=10, severity="Low", issue="smell", suggestion="refactor", before_code="", after_code="")
    db.add(sf)
    db.add(cs)
    db.commit()
    
    pr_id = str(pr.id)
    db.close()
    
    # Setup GitHub mocks
    mock_gh = mock_gh_service_class.return_value
    mock_gh.get_pr_files.return_value = [
        {"filename": "main.py", "additions": 10, "deletions": 2, "changes": 12, "status": "modified", "patch": "@@ ... @@", "raw_url": "http://raw"}
    ]
    mock_gh.post_inline_comments.return_value = (2, 0)
    
    # 1. GET /pull-requests/{id}
    res_pr = client.get(f"/api/v1/pull-requests/{pr_id}", headers=headers)
    assert res_pr.status_code == 200
    assert res_pr.json()["title"] == "My PR Title"
    
    # 2. GET /pull-requests/{id}/files
    res_files = client.get(f"/api/v1/pull-requests/{pr_id}/files", headers=headers)
    assert res_files.status_code == 200
    assert res_files.json()["risk_score"] == 15
    assert len(res_files.json()["files"]) == 1
    assert len(res_files.json()["files"][0]["findings"]) == 2
    
    # 3. POST /pull-requests/{id}/post-review
    res_post = client.post(f"/api/v1/pull-requests/{pr_id}/post-review", headers=headers)
    assert res_post.status_code == 200
    assert res_post.json()["posted_inline"] == 2


# --- REPOSITORIES PR SYNC ---

@patch("app.routers.repositories.GitHubService")
def test_repositories_list_prs_sync(mock_gh_service_class, client):
    headers = get_auth_headers(client, "repoprs@example.com")
    
    # Seed DB repo
    db = SessionLocal()
    user = db.query(User).filter_by(email="repoprs@example.com").first()
    repo = Repository(user_id=user.id, name="owner/repo_prs", default_branch="main")
    db.add(repo)
    db.commit()
    
    # Seed an existing PR in DB to test "update" and "cleanup" logic in sync
    existing_pr = PullRequest(
        repository_id=repo.id,
        number=1,
        title="Old Title",
        author="someone",
        state="open",
        additions=5,
        deletions=2,
        head_sha="oldsha",
        base_sha="oldbase"
    )
    db.add(existing_pr)
    
    # Seed a PR that will be closed (not returned by get_open_pull_requests)
    closed_pr = PullRequest(
        repository_id=repo.id,
        number=2,
        title="Will Be Closed Title",
        author="someone",
        state="open",
        additions=5,
        deletions=2,
        head_sha="closedsha",
        base_sha="closedbase"
    )
    db.add(closed_pr)
    db.commit()
    
    repo_id = str(repo.id)
    db.close()
    
    # Setup mock
    mock_gh = mock_gh_service_class.return_value
    mock_gh.get_open_pull_requests.return_value = [
        {"number": 1, "title": "Updated Title"},  # will update existing
        {"number": 3, "title": "New Title"}        # will create new
    ]
    
    def mock_get_pr_details(repo_name, number):
        if number == 1:
            return {"title": "Updated Title", "author": "someone", "state": "open", "additions": 10, "deletions": 3, "head_sha": "newsha", "base_sha": "newbase"}
        elif number == 3:
            return {"title": "New Title", "author": "other", "state": "open", "additions": 15, "deletions": 1, "head_sha": "sha3", "base_sha": "base3"}
        return {}
    mock_gh.get_pr_details.side_effect = mock_get_pr_details
    
    # GET /repositories/{id}/prs
    resp = client.get(f"/api/v1/repositories/{repo_id}/prs", headers=headers)
    assert resp.status_code == 200
    res_list = resp.json()
    assert len(res_list) == 2
    
    # Verify titles
    titles = [x["title"] for x in res_list]
    assert "Updated Title" in titles
    assert "New Title" in titles


# --- USER DASHBOARD METRICS WITH REPOS ---

def test_users_dashboard_metrics_with_repos(client):
    headers = get_auth_headers(client, "dash_metrics@example.com")
    
    db = SessionLocal()
    user = db.query(User).filter_by(email="dash_metrics@example.com").first()
    
    # Create repo
    repo = Repository(user_id=user.id, name="owner/repo", default_branch="main")
    db.add(repo)
    db.commit()
    
    # Create analysis
    analysis = Analysis(
        repository_id=repo.id,
        pull_request_id=None,
        status="completed",
        progress=100,
        risk_score=10
    )
    db.add(analysis)
    db.commit()
    
    # Health score
    hs = HealthScore(
        analysis_id=analysis.id,
        health_score=90
    )
    db.add(hs)
    
    # Finding
    sf = SecurityFinding(
        analysis_id=analysis.id,
        file="main.py",
        line=5,
        severity="High",
        issue="SQL Injection",
        suggestion="Use parameterized query",
        before_code="",
        after_code=""
    )
    db.add(sf)
    db.commit()
    db.close()
    
    # Call dashboard metrics
    resp = client.get("/api/v1/users/me/dashboard", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["repositories_count"] == 1
    assert data["vulnerabilities_count"] == 1
    assert data["avg_health_score"] == 90.0


