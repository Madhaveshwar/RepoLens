import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4
import uuid
import json
from fastapi import HTTPException, status, Request
from fastapi.testclient import TestClient
from backend.app.database.database import SessionLocal
from backend.app.models.models import (
    User, Repository, PullRequest, Analysis,
    Report, SecurityFinding, CodeSmell, TestSuggestion, HealthScore
)

def get_auth_headers(client, email="boostmore@example.com", password="testpassword"):
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

# --- ENCRYPTOR COVERS ---
def test_encryptor_covers():
    from backend.app.auth.encryption import encryptor
    assert encryptor.encrypt("") == ""
    assert encryptor.encrypt(None) == ""
    assert encryptor.decrypt("") == ""
    assert encryptor.decrypt(None) == ""
    assert encryptor.decrypt("invalid-cipher-text-here-should-fail") == ""

# --- SECURITY COVERS ---
def test_security_covers():
    from backend.app.auth.security import create_access_token, uuid_parse
    from datetime import timedelta
    # 1. expires_delta block
    tok = create_access_token("test-sub", expires_delta=timedelta(minutes=5))
    assert tok is not None
    # 2. uuid_parse ValueError path
    assert uuid_parse("invalid-uuid") is None

# --- DATABASE COVERS ---
def test_database_covers():
    from backend.app.database.database import get_sync_db, get_async_db
    # 1. get_sync_db success path
    gen = get_sync_db()
    db = next(gen)
    assert db is not None
    try:
        next(gen)
    except StopIteration:
        pass
    
    # 2. get_sync_db exception path
    gen_fail = get_sync_db()
    db_fail = next(gen_fail)
    with patch.object(db_fail, "commit", side_effect=Exception("mock commit fail")):
        with pytest.raises(Exception):
            next(gen_fail)

# --- CSRF MIDDLEWARE COVERS ---
def test_csrf_middleware_failures(client):
    headers = get_auth_headers(client, "csrf_fail@example.com")
    
    # Invalid Origin
    bad_origin_headers = {**headers, "Origin": "http://malicious.com"}
    resp = client.post("/api/v1/repositories", json={"url": "test/repo"}, headers=bad_origin_headers)
    assert resp.status_code == 403
    assert "invalid origin" in resp.json()["detail"]
    
    # Invalid Referer (Origin header not present)
    bad_referer_headers = {**headers, "Referer": "http://malicious.com/some-path"}
    resp = client.post("/api/v1/repositories", json={"url": "test/repo"}, headers=bad_referer_headers)
    assert resp.status_code == 403
    assert "invalid referer" in resp.json()["detail"]

# --- RATE LIMIT MIDDLEWARE COVERS ---
@pytest.mark.anyio
async def test_rate_limit_middleware_exceeded():
    from backend.app.main import RateLimitMiddleware
    mock_app = MagicMock()
    middleware = RateLimitMiddleware(mock_app, limit=1, window=60)
    
    # First request passes
    mock_request = MagicMock()
    mock_request.scope = {"type": "http"}
    mock_request.client.host = "1.2.3.4"
    mock_request.url.path = "/api/v1/some-route"
    mock_request.method = "GET"
    mock_request.headers = MagicMock()
    mock_request.headers.get.return_value = ""
    
    async def mock_call_next(req):
        return "success"
        
    res1 = await middleware.dispatch(mock_request, mock_call_next)
    assert res1 == "success"
    
    # Second request hits rate limit
    res2 = await middleware.dispatch(mock_request, mock_call_next)
    assert res2.status_code == 429

@pytest.mark.anyio
async def test_rate_limit_middleware_options_bypass():
    from backend.app.main import RateLimitMiddleware
    mock_app = MagicMock()
    middleware = RateLimitMiddleware(mock_app, limit=1, window=60)
    
    mock_request = MagicMock()
    mock_request.scope = {"type": "http"}
    mock_request.client.host = "1.2.3.4"
    mock_request.url.path = "/api/v1/some-route"
    mock_request.method = "OPTIONS"
    mock_request.headers = MagicMock()
    mock_request.headers.get.return_value = ""
    
    async def mock_call_next(req):
        return "success"
        
    # Multiple requests pass because method is OPTIONS
    res1 = await middleware.dispatch(mock_request, mock_call_next)
    assert res1 == "success"
    res2 = await middleware.dispatch(mock_request, mock_call_next)
    assert res2 == "success"

@pytest.mark.anyio
async def test_rate_limit_middleware_dashboard_bypass():
    from backend.app.main import RateLimitMiddleware
    mock_app = MagicMock()
    middleware = RateLimitMiddleware(mock_app, limit=1, window=60)
    
    mock_request = MagicMock()
    mock_request.scope = {"type": "http"}
    mock_request.client.host = "1.2.3.4"
    mock_request.url.path = "/api/v1/users/me/dashboard"
    mock_request.method = "GET"
    mock_request.headers = MagicMock()
    mock_request.headers.get.side_effect = lambda key, default=None: "Bearer token123" if key == "authorization" else default
    
    async def mock_call_next(req):
        return "success"
        
    # Multiple requests pass because it's the dashboard path and authenticated
    res1 = await middleware.dispatch(mock_request, mock_call_next)
    assert res1 == "success"
    res2 = await middleware.dispatch(mock_request, mock_call_next)
    assert res2 == "success"

# --- REPOSITORIES ROUTER ERROR PATHS ---
@patch("backend.app.routers.repositories.GitHubService")
def test_repositories_router_errors(mock_gh_service_class, client):
    headers = get_auth_headers(client, "repo_errs@example.com")
    invalid_uuid = str(uuid4())
    
    # GET /{id} -> 404
    resp = client.get(f"/api/v1/repositories/{invalid_uuid}", headers=headers)
    assert resp.status_code == 404
    
    # GET /{id}/prs -> 404
    resp = client.get(f"/api/v1/repositories/{invalid_uuid}/prs", headers=headers)
    assert resp.status_code == 404
    
    # DELETE /{id} -> 404
    resp = client.delete(f"/api/v1/repositories/{invalid_uuid}", headers=headers)
    assert resp.status_code == 404
    
    # POST /{id}/disconnect -> 404
    resp = client.post(f"/api/v1/repositories/{invalid_uuid}/disconnect", headers=headers)
    assert resp.status_code == 404
    
    # GET /{id}/permissions -> 404
    resp = client.get(f"/api/v1/repositories/{invalid_uuid}/permissions", headers=headers)
    assert resp.status_code == 404
    
    # Seed repository to test valid ID but token missing or check throws exception
    db = SessionLocal()
    user = db.query(User).filter_by(email="repo_errs@example.com").first()
    repo = Repository(user_id=user.id, name="errs/repo", default_branch="main")
    db.add(repo)
    db.commit()
    repo_id = str(repo.id)
    db.close()
    
    # Temporarily remove default token / settings GITHUB_TOKEN
    with patch("backend.app.routers.repositories.settings") as mock_settings:
        mock_settings.GITHUB_TOKEN = None
        mock_settings.API_V1_STR = "/api/v1"
        resp = client.get(f"/api/v1/repositories/{repo_id}/permissions", headers=headers)
        assert resp.status_code == 400
        assert "token is not configured" in resp.json()["detail"]
        
    # GitHubService throws exception during permission check
    mock_gh = mock_gh_service_class.return_value
    mock_gh.client.get_repo.side_effect = Exception("GitHub API failure")
    resp = client.get(f"/api/v1/repositories/{repo_id}/permissions", headers=headers)
    assert resp.status_code == 400
    assert "Failed to check GitHub permissions" in resp.json()["detail"]
    
    # Connect repository with invalid URL
    resp = client.post("/api/v1/repositories", json={"url": "invalidurl"}, headers=headers)
    assert resp.status_code == 400
    assert "Invalid GitHub repository URL" in resp.json()["detail"]



# --- ANALYSIS ROUTER ERROR PATHS ---
def test_analysis_router_errors(client):
    headers = get_auth_headers(client, "analysis_errs@example.com")
    invalid_uuid = str(uuid4())
    
    # GET /analysis/repo/{repo_id} -> 404
    resp = client.get(f"/api/v1/analysis/repo/{invalid_uuid}", headers=headers)
    assert resp.status_code == 404
    
    # GET /analysis/{id} -> 404
    resp = client.get(f"/api/v1/analysis/{invalid_uuid}", headers=headers)
    assert resp.status_code == 404
    
    # POST /analysis/{id}/restore -> 404
    resp = client.post(f"/api/v1/analysis/{invalid_uuid}/restore", headers=headers)
    assert resp.status_code == 404
    
    # DELETE /analyses/{id} -> 404
    resp = client.delete(f"/api/v1/analyses/{invalid_uuid}", headers=headers)
    assert resp.status_code == 404
    
    # DELETE /analyses/repo/{repo_id} -> 404
    resp = client.delete(f"/api/v1/analyses/repo/{invalid_uuid}", headers=headers)
    assert resp.status_code == 404
    
    # GET /analyses/{id}/stats -> 404
    resp = client.get(f"/api/v1/analyses/{invalid_uuid}/stats", headers=headers)
    assert resp.status_code == 404
    
    # GET /analyses/compare -> 404 (one scan not found)
    resp = client.get(f"/api/v1/analyses/compare?scan_a={invalid_uuid}&scan_b={invalid_uuid}", headers=headers)
    assert resp.status_code == 404
    assert "scans not found" in resp.json()["detail"]
    
    # POST /analysis/trigger -> 404
    resp = client.post(
        "/api/v1/analysis/trigger",
        json={"repository_id": invalid_uuid},
        headers=headers
    )
    assert resp.status_code == 404

# --- PULL REQUESTS ROUTER ERROR PATHS ---
@patch("backend.app.routers.pull_requests.GitHubService")
def test_pull_requests_router_errors_and_flows(mock_gh_service_class, client):
    headers = get_auth_headers(client, "pr_router_errs@example.com")
    invalid_uuid = str(uuid4())
    
    # GET /{id} -> 404
    resp = client.get(f"/api/v1/pull-requests/{invalid_uuid}", headers=headers)
    assert resp.status_code == 404
    
    # GET /{id}/files -> 404
    resp = client.get(f"/api/v1/pull-requests/{invalid_uuid}/files", headers=headers)
    assert resp.status_code == 404
    
    # POST /{id}/post-review -> 404
    resp = client.post(f"/api/v1/pull-requests/{invalid_uuid}/post-review", headers=headers)
    assert resp.status_code == 404

    # Seed PR and Repository
    db = SessionLocal()
    user = db.query(User).filter_by(email="pr_router_errs@example.com").first()
    repo = Repository(user_id=user.id, name="pr/errors", default_branch="main")
    db.add(repo)
    db.commit()
    db.refresh(repo)
    repo_id = repo.id
    
    pr = PullRequest(
        repository_id=repo_id,
        number=1,
        title="Mock PR",
        author="tester",
        state="open",
        head_sha="sha1",
        base_sha="sha2"
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)
    pr_id_val = pr.id
    
    pr_id = str(pr_id_val)
    
    # GET /{id}/files -> GitHub service exception
    mock_gh = mock_gh_service_class.return_value
    mock_gh.get_pr_files.side_effect = Exception("GitHub PR files API failure")
    resp = client.get(f"/api/v1/pull-requests/{pr_id}/files", headers=headers)
    assert resp.status_code == 400
    assert "Failed to fetch files" in resp.json()["detail"]
    
    # POST /{id}/post-review -> No completed analysis found
    resp = client.post(f"/api/v1/pull-requests/{pr_id}/post-review", headers=headers)
    assert resp.status_code == 400
    assert "No completed analysis found" in resp.json()["detail"]

    # Seed completed analysis and findings
    analysis = Analysis(repository_id=repo_id, pull_request_id=pr_id_val, status="completed", risk_score=10)
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    
    sf = SecurityFinding(analysis_id=analysis.id, file="main.py", line=1, severity="High", issue="SQLi", suggestion="param")
    db.add(sf)
    db.commit()
    db.close()
    
    # POST /{id}/post-review -> Missing GitHub PAT
    with patch("backend.app.routers.pull_requests.settings") as mock_settings:
        mock_settings.GITHUB_TOKEN = None
        resp = client.post(f"/api/v1/pull-requests/{pr_id}/post-review", headers=headers)
        assert resp.status_code == 400
        assert "Personal Access Token is required" in resp.json()["detail"]
        
    # POST /{id}/post-review -> Success path
    mock_gh.post_inline_comments.return_value = (1, 0)
    resp = client.post(f"/api/v1/pull-requests/{pr_id}/post-review", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

# --- REPORTS ROUTER COVERS ---
@patch("backend.app.routers.reports.generate_pdf_report")
def test_reports_router_downloads(mock_gen_pdf, client):
    headers = get_auth_headers(client, "reports_download@example.com")
    invalid_uuid = str(uuid4())
    
    # GET /reports/{id} -> 404
    resp = client.get(f"/api/v1/reports/{invalid_uuid}", headers=headers)
    assert resp.status_code == 404
    
    # Seed DB
    db = SessionLocal()
    user = db.query(User).filter_by(email="reports_download@example.com").first()
    repo = Repository(user_id=user.id, name="reports/download", default_branch="main")
    db.add(repo)
    db.commit()
    db.refresh(repo)
    repo_id_val = repo.id
    
    analysis = Analysis(repository_id=repo_id_val, status="completed", risk_score=20)
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    analysis_id_val = analysis.id
    
    report = Report(analysis_id=analysis_id_val, user_id=user.id, type="PDF", filepath="missing_on_disk.pdf")
    db.add(report)
    db.commit()
    db.refresh(report)
    report_id = str(report.id)
    
    # GET /reports/{id} -> Missing file, attempts dynamic regeneration but fails
    resp = client.get(f"/api/v1/reports/{report_id}", headers=headers)
    assert resp.status_code == 404
    assert "Static report file is missing" in resp.json()["detail"]
    
    # Success dynamic generation and download (e.g. Markdown report)
    md_report = Report(analysis_id=analysis_id_val, user_id=user.id, type="Markdown", filepath="real_report.md")
    db.add(md_report)
    db.commit()
    db.refresh(md_report)
    md_report_id = str(md_report.id)
    db.close()
    
    # Mock open and check file exists to return true for download
    from fastapi import Response
    with patch("os.path.exists", return_value=True):
        with patch("backend.app.routers.reports.FileResponse", return_value=Response("report content", media_type="text/markdown")):
            resp = client.get(f"/api/v1/reports/{md_report_id}", headers=headers)
            assert resp.status_code == 200
            assert resp.text == "report content"

# --- CODE QUALITY, SECURITY, TESTS ROUTER ERROR PATHS ---
def test_other_routers_analysis_not_found(client):
    headers = get_auth_headers(client, "other_routers@example.com")
    invalid_uuid = str(uuid4())
    
    # GET /code-quality/analysis/{id} -> 404
    resp = client.get(f"/api/v1/code-quality/analysis/{invalid_uuid}", headers=headers)
    assert resp.status_code == 404
    
    # GET /security/analysis/{id} -> 404
    resp = client.get(f"/api/v1/security/analysis/{invalid_uuid}", headers=headers)
    assert resp.status_code == 404
    
    # GET /tests/analysis/{id} -> 404
    resp = client.get(f"/api/v1/tests/analysis/{invalid_uuid}", headers=headers)
    assert resp.status_code == 404

# --- VALIDATION EXTRA BRANCHES ---
def test_validation_extra_branches():
    from backend.app.utils.validation import is_valid_code
    # 1. structure_hits >= 2 and alpha_count >= 4 -> returns True
    assert is_valid_code("abcd = {123: 456}") is True
    # 2. structure_hits >= 2 but alpha_count < 4 -> returns False
    assert is_valid_code("a = {1}") is False

# --- WEBSOCKET MANAGER EXCEPTION BRANCH ---
@pytest.mark.anyio
async def test_listen_to_redis_channel_exception_branch():
    from backend.app.websockets.websocket_manager import listen_to_redis_channel
    
    mock_ws = AsyncMock()
    mock_redis_client = AsyncMock()
    mock_pubsub = AsyncMock()
    
    # Trigger Exception during get_message
    mock_pubsub.get_message.side_effect = Exception("mock connection failure")
    mock_redis_client.pubsub = MagicMock(return_value=mock_pubsub)
    
    with patch("backend.app.websockets.websocket_manager.aioredis.from_url", return_value=mock_redis_client):
        await listen_to_redis_channel("analysis_123", mock_ws)
        
    mock_pubsub.unsubscribe.assert_called_once_with("analysis_progress_analysis_123")

# --- ADDITIONAL SERVICE COVERAGE ---

def test_test_generator_coverage():
    from backend.app.services.test_generator import generate_tests
    # 1. empty code strip
    assert generate_tests(None, "app.py", "", "Python") == "No code provided to generate tests."

    # 2. primary fails, fallback succeeds
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content="fallback tests"))
    ]
    mock_client.chat.completions.create.side_effect = [
        Exception("Primary model fail"),
        mock_response
    ]
    res = generate_tests(mock_client, "app.py", "def test(): pass", "Python")
    assert res == "fallback tests"

    # 3. primary fails, fallback fails
    mock_client_fail = MagicMock()
    mock_client_fail.chat.completions.create.side_effect = Exception("Double fail")
    with pytest.raises(Exception):
        generate_tests(mock_client_fail, "app.py", "def test(): pass", "Python")

def test_security_scanner_coverage():
    from backend.app.services.security_scanner import parse_json_from_llm, scan_security
    
    # 1. parse_json_from_llm exceptions
    assert parse_json_from_llm("invalid json [1,2,3") == []
    assert parse_json_from_llm("[ {invalid: json} ]") == []
    assert parse_json_from_llm('{ "file": invalid }') == []
    assert parse_json_from_llm("invalid-content-not-json-at-all") == []
    
    # 2. scan_security fallback success
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content='[{"issue": "Fallback Secret"}]'))
    ]
    mock_client.chat.completions.create.side_effect = [
        Exception("Primary scan fail"),
        mock_response
    ]
    findings = scan_security(mock_client, "app.py", "code", "", "Python")
    assert len(findings) == 1
    assert findings[0]["issue"] == "Fallback Secret"
    
    # 3. scan_security double fail
    mock_client_fail = MagicMock()
    mock_client_fail.chat.completions.create.side_effect = Exception("Double scan fail")
    with pytest.raises(Exception):
        scan_security(mock_client_fail, "app.py", "code", "", "Python")

def test_code_smell_detector_coverage():
    from backend.app.services.code_smell_detector import detect_code_smells
    
    # 1. fallback success
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content='[{"issue": "Fallback Smell"}]'))
    ]
    mock_client.chat.completions.create.side_effect = [
        Exception("Primary smell fail"),
        mock_response
    ]
    findings = detect_code_smells(mock_client, "app.py", "code", "", "Python")
    assert len(findings) == 1
    assert findings[0]["issue"] == "Fallback Smell"
    
    # 2. double fail
    mock_client_fail = MagicMock()
    mock_client_fail.chat.completions.create.side_effect = Exception("Double smell fail")
    with pytest.raises(Exception):
        detect_code_smells(mock_client_fail, "app.py", "code", "", "Python")

def test_repository_analyzer_coverage():
    from backend.app.services.repository_analyzer import analyze_repository
    
    mock_client = MagicMock()
    mock_gh_service = MagicMock()
    mock_repo = MagicMock()
    mock_gh_service.client.get_repo.return_value = mock_repo
    
    # 1. Test fetch git tree exception path
    mock_repo.get_branch.side_effect = Exception("Branch retrieval failed")
    res = analyze_repository(
        mock_client,
        mock_gh_service,
        "owner/repo",
        qualitative_report="PENDING"
    )
    assert res["health_score"] == 60 # readme missing (-20), no tests (-20)
    
    # 2. Test requirements.txt detection, large files, missing tests, outdated dependencies
    mock_repo.get_branch.side_effect = None
    mock_repo.default_branch = "main"
    mock_branch = MagicMock()
    mock_branch.commit.sha = "12345"
    mock_repo.get_branch.return_value = mock_branch
    
    # Git tree blobs
    mock_blob_readme = MagicMock()
    mock_blob_readme.path = "README.md"
    mock_blob_readme.type = "blob"
    mock_blob_readme.size = 1000
    
    mock_blob_req = MagicMock()
    mock_blob_req.path = "requirements.txt"
    mock_blob_req.type = "blob"
    mock_blob_req.size = 1000
    
    mock_blob_src1 = MagicMock()
    mock_blob_src1.path = "src/main.py"
    mock_blob_src1.type = "blob"
    mock_blob_src1.size = 600 * 1024 # 600 KB (large file)
    
    mock_blob_src2 = MagicMock()
    mock_blob_src2.path = "src/helper.py"
    mock_blob_src2.type = "blob"
    mock_blob_src2.size = 10 * 1024
    
    mock_tree = MagicMock()
    mock_tree.tree = [mock_blob_readme, mock_blob_req, mock_blob_src1, mock_blob_src2]
    mock_repo.get_git_tree.return_value = mock_tree
    
    def mock_get_content(repo, path, branch):
        if "requirements" in path:
            return "requirements.txt\npycrypto\nrequests<2.10.0\nurllib3<1.25.0"
        return "'''docstring'''"
    mock_gh_service.get_file_content.side_effect = mock_get_content
    
    # LLM success response
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content="qualitative report analysis"))
    ]
    mock_client.chat.completions.create.return_value = mock_response
    
    res = analyze_repository(
        mock_client,
        mock_gh_service,
        "owner/repo",
        qualitative_report=None
    )
    # readme_exists = True, test_files = 0, large_files = 1, missing_tests = 2 (main and helper), outdated deps = 3
    # deductions: "No test files detected (-20)", "1 large files detected (-5)", "Outdated/risky dependencies in requirements.txt (-10)"
    assert res["health_score"] == 65 # 100 - 20 - 5 - 10 = 65
    assert res["readme_exists"] is True
    assert len(res["large_files"]) == 1
    assert len(res["missing_tests"]) == 1
    
    # 3. Test LLM failure fallback paths in repository analyzer
    # Primary model throws exception, fallback succeeds
    mock_client_fail = MagicMock()
    mock_client_fail.chat.completions.create.side_effect = [
        Exception("Primary model report failure"),
        mock_response
    ]
    res_fallback = analyze_repository(
        mock_client_fail,
        mock_gh_service,
        "owner/repo",
        qualitative_report=None
    )
    assert res_fallback["analysis_report"] == "qualitative report analysis"
    
    # Double LLM failure
    mock_client_double_fail = MagicMock()
    mock_client_double_fail.chat.completions.create.side_effect = Exception("Double report failure")
    with pytest.raises(Exception):
        analyze_repository(
            mock_client_double_fail,
            mock_gh_service,
            "owner/repo",
            qualitative_report=None
        )


def test_security_scanner_exclusions_and_preservation():
    from backend.app.services.security_scanner import scan_security
    
    mock_client = MagicMock()
    # Mock LLM to return 4 findings
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps([
            {
                "file": "app.py",
                "line": 1,
                "severity": "High",
                "issue": "Plain env get",
                "before_code": "secret_key = os.getenv('SECRET')"
            },
            {
                "file": "app.py",
                "line": 2,
                "severity": "High",
                "issue": "BaseSettings class",
                "before_code": "class MyConfig(BaseSettings):"
            },
            {
                "file": "app.py",
                "line": 3,
                "severity": "High",
                "issue": "Hardcoded secret",
                "before_code": "password = 'super_secret_password_12345'"
            },
            {
                "file": "app.py",
                "line": 4,
                "severity": "High",
                "issue": "Insecure default",
                "before_code": "api_key = os.getenv('API_KEY', 'xoxb-1234567890-abcdefgh')"
            }
        ])))
    ]
    mock_client.chat.completions.create.return_value = mock_response
    
    code = """secret_key = os.getenv('SECRET')
class MyConfig(BaseSettings):
password = 'super_secret_password_12345'
api_key = os.getenv('API_KEY', 'xoxb-1234567890-abcdefgh')
"""
    findings = scan_security(
        client=mock_client,
        filename="app.py",
        code=code,
        patch="",
        language="Python"
    )
    
    issues = [f["issue"] for f in findings]
    assert "Plain env get" not in issues
    assert "BaseSettings class" not in issues
    assert "Hardcoded secret" in issues
    assert "Insecure default" in issues


def test_root_security_scanner_exclusions():
    from security_scanner import scan_security
    
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps([
            {
                "file": "app.py",
                "line": 1,
                "severity": "High",
                "issue": "Plain env get",
                "before_code": "secret_key = os.getenv('SECRET')"
            },
            {
                "file": "app.py",
                "line": 3,
                "severity": "High",
                "issue": "Hardcoded secret",
                "before_code": "password = 'super_secret_password_12345'"
            }
        ])))
    ]
    mock_client.chat.completions.create.return_value = mock_response
    
    code = """secret_key = os.getenv('SECRET')
password = 'super_secret_password_12345'
"""
    findings = scan_security(
        client=mock_client,
        filename="app.py",
        code=code,
        patch="",
        language="Python"
    )
    
    issues = [f["issue"] for f in findings]
    assert "Plain env get" not in issues
    assert "Hardcoded secret" in issues


