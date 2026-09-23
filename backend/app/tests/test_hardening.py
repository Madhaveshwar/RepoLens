import pytest
import hmac
import hashlib
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

from fastapi import status

from app.config import settings
from app.database.database import SessionLocal
from app.models.models import User, Repository, PullRequest, Analysis, AuditLog
from app.services.reviewer import review_files_combined

def get_auth_headers(client, email="hardening@example.com", password="TestPass123"):
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

def test_webhook_ping_event(client):
    headers = {
        "X-GitHub-Event": "ping",
        "Content-Type": "application/json"
    }
    response = client.post("/api/v1/webhooks/github", json={}, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"message": "pong"}

def test_webhook_invalid_signature(client):
    # Set GITHUB_WEBHOOK_SECRET temporarily
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", "super_secret_secret"):
        headers = {
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": "sha256=invalid_signature",
            "Content-Type": "application/json"
        }
        response = client.post("/api/v1/webhooks/github", json={}, headers=headers)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["detail"] == "Signature mismatch."

def test_webhook_pr_event_trigger(client):
    # Setup test repository
    db = SessionLocal()
    repo = Repository(
        user_id=uuid.uuid4(),
        name="owner/test-webhook-repo",
        default_branch="main",
        is_connected=True
    )
    db.add(repo)
    db.commit()
    repo_id = repo.id
    db.close()

    payload = {
        "action": "opened",
        "pull_request": {
            "number": 12,
            "title": "A new change",
            "user": {"login": "testuser"},
            "head": {"sha": "headsha123"},
            "base": {"sha": "basesha123"}
        },
        "repository": {
            "full_name": "owner/test-webhook-repo"
        }
    }

    headers = {
        "X-GitHub-Event": "pull_request",
        "Content-Type": "application/json"
    }

    # Set webhook secret to None to bypass signature checking
    with patch.object(settings, "GITHUB_WEBHOOK_SECRET", None):
        with patch("app.routers.webhooks.enqueue_analysis_task") as mock_celery:
            response = client.post("/api/v1/webhooks/github", json=payload, headers=headers)
            assert response.status_code == 200
            assert "Scan triggered for PR #12" in response.json()["message"]
            
            # Verify PR record created
            db = SessionLocal()
            pr = db.query(PullRequest).filter_by(repository_id=repo_id, number=12).first()
            assert pr is not None
            assert pr.head_sha == "headsha123"
            
            # Verify Analysis record created
            analysis = db.query(Analysis).filter_by(repository_id=repo_id).first()
            assert analysis is not None
            assert analysis.status == "pending"
            
            mock_celery.assert_called_once()
            db.close()

def test_audit_logs_retrieval(client):
    email = "audit@example.com"
    headers = get_auth_headers(client, email)
    
    db = SessionLocal()
    user = db.query(User).filter_by(email=email).first()
    assert user is not None
    user_id = user.id
    
    # Insert audit logs
    log = AuditLog(
        user_id=user_id,
        action="TEST_ACTION",
        details={"foo": "bar"}
    )
    db.add(log)
    db.commit()
    db.close()

    response = client.get("/api/v1/audit-logs", headers=headers)
    assert response.status_code == 200
    logs = response.json()
    assert len(logs) >= 1
    assert any(l["action"] == "TEST_ACTION" for l in logs)

def test_dlq_tasks_and_retry(client):
    """DLQ endpoints removed with Auto-Fix Engine; test preserved as placeholder."""
    assert True

def test_diff_chunking_and_fallback():
    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = '{"files_reviews": {}, "repository_insights": "insights content"}'
    mock_client.chat.completions.create.return_value.choices = [mock_choice]
    mock_client.chat.completions.create.return_value.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    
    files = [
        {"filename": "a.py", "content": "print('hello')", "patch": "@@ -0,0 +1 @@\n+print('hello')", "language": "Python"},
        {"filename": "b.py", "content": "print('world')", "patch": "@@ -0,0 +1 @@\n+print('world')", "language": "Python"}
    ]
    
    with patch("app.services.reviewer.load_cache", return_value={}):
        with patch("app.services.reviewer.save_cache"):
            with patch("app.services.reviewer.settings") as mock_settings:
                mock_settings.FORCE_GROQ_ANALYSIS = True
                
                res_map, cache_hits, insights, requests_made, chars_sent, stats = review_files_combined(
                    client=mock_client,
                    files_to_review=files,
                    repo_metadata={"folder_structure": "", "dependency_risks": "", "large_files": [], "security_hotspots": [], "doc_coverage": {}},
                    repo_name="owner/repo",
                    model_name="llama-3.3-70b-versatile"
                )
                
                assert requests_made >= 1
                assert stats["total_tokens"] > 0
