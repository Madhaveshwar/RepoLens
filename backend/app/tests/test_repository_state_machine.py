"""
Repository-state machine tests.

Verifies the backend half of the required state machine:

  LOGIN → SETTINGS / CREDENTIAL STATUS → REPOSITORY SELECTION
        → USER EXPLICITLY SELECTS REPOSITORY → REPOSITORY DASHBOARD

Frontend behavior (login never auto-opens the previous repository, logout
clears the selection, refresh-on-explicit-URL may persist) is enforced in
App.tsx + stores and verified by live browser QA; these tests pin the server
side of the contract:

  T1. Chat: no repository selected → NO repository scan context is injected
      (must not silently answer from "the last scanned repository").
  T2. Chat: context loading is scoped to the selected repository AND its
      owner (frontend-supplied repository_id is verified server-side).
  T3. Dashboard metrics: deleting Repository A removes it from aggregates —
      deleted repos cannot resurface anywhere.
  T4. Old repository URL after delete → 404 with no data (ownership + existence).
  T5. Disconnect: repository disappears from the user's repository list.
  T6. Ownership isolation: user B can never read user A's repository.
"""

import uuid
import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4

from app.database.database import SessionLocal
from app.models.models import User, Repository, Analysis, SecurityFinding
from app.auth.security import get_password_hash_sync


def _register_login(client, email, password="TestPass123"):
    client.post("/api/v1/auth/register", json={"email": email, "password": password})
    login = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _seed_repo_with_scan(email, repo_name, risk_score=25, with_findings=True):
    """Create user (if needed) + repo + completed analysis with findings."""
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(email=email).first()
        if user is None:
            user = User(email=email, hashed_password=get_password_hash_sync("TestPass123"))
            db.add(user)
            db.commit()
            db.refresh(user)
        repo = Repository(user_id=user.id, name=repo_name, default_branch="main")
        db.add(repo)
        db.commit()
        db.refresh(repo)
        analysis = Analysis(repository_id=repo.id, status="completed", progress=100, risk_score=risk_score)
        db.add(analysis)
        db.commit()
        db.refresh(analysis)
        if with_findings:
            db.add(SecurityFinding(
                analysis_id=analysis.id, file="app.py", line=5,
                severity="Critical", issue="Hardcoded credential",
                suggestion="Use env var", before_code="", after_code="",
            ))
            db.commit()
        return str(repo.id)
    finally:
        db.close()


# ── T1/T2: Chat context is repository-scoped ────────────────────────────────

@pytest.fixture
def chat_user_headers(client):
    return _register_login(client, "statemachine_chat@example.com")


@pytest.fixture
def mock_llm():
    with patch("app.routers.chat.build_llm_client") as mock_build:
        client = MagicMock()
        resp = MagicMock()
        choice = MagicMock()
        choice.message.content = "answer"
        resp.choices = [choice]
        client.chat.completions.create.return_value = resp
        mock_build.return_value = client
        yield mock_build


def _capture_system_prompt(mock_build):
    kwargs = mock_build.return_value.chat.completions.create.call_args.kwargs
    for msg in kwargs["messages"]:
        if msg["role"] == "system":
            return msg["content"]
    return ""


def test_chat_no_repository_selected_injects_no_scan_context(client, chat_user_headers, mock_llm):
    """T1 — with NO repository selected, the latest scan of ANY repository must
    NOT be injected into the conversation (repository-state rule)."""
    # Seed a completed scan so the old behavior would have injected it.
    _seed_repo_with_scan("statemachine_chat@example.com", "ctx/selected-not")

    resp = client.post(
        "/api/v1/chat/ask",
        json={"message": "Summarize this scan", "current_page": "dashboard"},
        headers=chat_user_headers,
    )
    assert resp.status_code == 200, resp.text
    system = _capture_system_prompt(mock_llm)
    # No repository scan context may appear…
    assert "Current repository scan context" not in system
    assert "Latest completed repository scan" not in system
    assert "ctx/selected-not" not in system
    # …and the absence must be explicit so the model cannot hallucinate one.
    assert "No repository scan context is available" in system


def test_chat_context_scoped_to_selected_repository_and_owner(client, chat_user_headers, mock_llm):
    """T2 — when a repository IS selected, only THAT repository's data is
    injected; another user's repository id is never honored."""
    other_headers = _register_login(client, "statemachine_other@example.com")
    del other_headers  # only used to create the second user via API

    own_repo_id = _seed_repo_with_scan("statemachine_chat@example.com", "ctx/own", risk_score=10)
    # A different user's repo with a fresh scan
    foreign_repo_id = _seed_repo_with_scan("statemachine_intruder@example.com", "ctx/foreign", risk_score=99)

    # Selected: own repository → own data injected.
    resp = client.post(
        "/api/v1/chat/ask",
        json={"message": "Summarize this scan", "repository_id": own_repo_id},
        headers=chat_user_headers,
    )
    assert resp.status_code == 200, resp.text
    system = _capture_system_prompt(mock_llm)
    assert "ctx/own" in system
    assert "ctx/foreign" not in system

    # Selected: FOREIGN repository id → ownership check → no data at all.
    mock_build2 = mock_llm
    resp = client.post(
        "/api/v1/chat/ask",
        json={"message": "Summarize this scan", "repository_id": foreign_repo_id},
        headers=chat_user_headers,
    )
    assert resp.status_code == 200, resp.text
    system2 = _capture_system_prompt(mock_build2)
    assert "ctx/foreign" not in system2
    assert "No repository scan context is available" in system2


# ── T3: deleted repository leaves all aggregates ────────────────────────────

def test_deleted_repository_disappears_from_dashboard_metrics(client):
    headers = _register_login(client, "statemachine_del@example.com")
    repo_id = _seed_repo_with_scan("statemachine_del@example.com", "ctx/deleted-repo", risk_score=55)

    resp = client.get("/api/v1/users/me/dashboard", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["repositories_count"] == 1
    assert data["vulnerabilities_count"] >= 1

    # Delete Repository A
    del_resp = client.delete(f"/api/v1/repositories/{repo_id}", headers=headers)
    assert del_resp.status_code == 200, del_resp.text

    # Aggregates no longer contain it
    resp2 = client.get("/api/v1/users/me/dashboard", headers=headers)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["repositories_count"] == 0
    assert data2["vulnerabilities_count"] == 0


# ── T4: old repository URL after delete → 404, no data ──────────────────────

def test_old_repository_url_returns_404_after_delete(client):
    headers = _register_login(client, "statemachine_url@example.com")
    repo_id = _seed_repo_with_scan("statemachine_url@example.com", "ctx/old-url")

    # While it exists the URL works (explicitly selected by id)
    ok = client.get(f"/api/v1/repositories/{repo_id}", headers=headers)
    assert ok.status_code == 200

    client.delete(f"/api/v1/repositories/{repo_id}", headers=headers)

    gone = client.get(f"/api/v1/repositories/{repo_id}", headers=headers)
    assert gone.status_code == 404
    # The detail scan-identity endpoint (deep-link data source) is closed too
    gone2 = client.get(f"/api/v1/repositories/{repo_id}/scan-identity", headers=headers)
    assert gone2.status_code == 404


# ── T5: disconnect removes the repository from selection ────────────────────

def test_disconnected_repository_leaves_repository_list(client):
    headers = _register_login(client, "statemachine_disc@example.com")
    repo_id = _seed_repo_with_scan("statemachine_disc@example.com", "ctx/disconnected")

    listed = client.get("/api/v1/repositories", headers=headers)
    assert listed.status_code == 200
    assert any(r["id"] == repo_id for r in listed.json())

    disc = client.post(f"/api/v1/repositories/{repo_id}/disconnect", headers=headers)
    assert disc.status_code == 200, disc.text

    listed2 = client.get("/api/v1/repositories", headers=headers)
    assert listed2.status_code == 200
    assert all(r["id"] != repo_id for r in listed2.json())


# ── T6: cross-user isolation on repository URLs ─────────────────────────────

def test_repository_url_denied_to_other_user(client):
    owner_headers = _register_login(client, "statemachine_owner@example.com")
    repo_id = _seed_repo_with_scan("statemachine_owner@example.com", "ctx/private-repo")

    attacker_headers = _register_login(client, "statemachine_attacker@example.com")
    resp = client.get(f"/api/v1/repositories/{repo_id}", headers=attacker_headers)
    assert resp.status_code == 404
    resp2 = client.get(f"/api/v1/analysis/repo/{repo_id}", headers=attacker_headers)
    assert resp2.status_code in (403, 404)


# ── T7: deletion removes scan-result cache rows (FK-cascade regression) ─────

def test_delete_repository_purges_result_cache_and_all_data(client):
    """Deleting a repository that has persistent result-cache rows must
    succeed and leave NO repository, analysis, findings, or cache rows behind.
    Regression for the FK-violation delete failure on cached scans."""
    from app.database.database import SessionLocal
    from app.models.models import (
        AnalysisResultCache, SecurityFinding, CodeSmell,
        RepositoryHealthSnapshot, Analysis, Repository,
    )

    headers = _register_login(client, "statemachine_cachepurge@example.com")
    repo_id = _seed_repo_with_scan("statemachine_cachepurge@example.com", "ctx/cache-purge", with_findings=True)

    db = SessionLocal()
    try:
        repo_uuid = uuid.UUID(repo_id)
        analysis = db.query(Analysis).filter(Analysis.repository_id == repo_uuid).first()
        assert analysis is not None

        # Seed the associated rows that a real scan produces
        db.add(AnalysisResultCache(
            repository_id=repo_uuid,
            commit_sha="abc123",
            analysis_version="v4-fast-scan",
            cache_key="test-key-cache-purge",
            result_json={"summary": "cached"},
        ))
        db.add(CodeSmell(analysis_id=analysis.id, file="a.py", line=1, severity="Low", issue="smell", suggestion="fix it"))
        db.add(RepositoryHealthSnapshot(repository_id=repo_uuid, analysis_id=analysis.id, health_score=80))
        db.commit()

        # Sanity: cache row exists before deletion
        assert db.query(AnalysisResultCache).filter(
            AnalysisResultCache.repository_id == repo_uuid
        ).count() == 1
    finally:
        db.close()

    # Delete via the API (frontend path: DELETE /repositories/{id})
    del_resp = client.delete(f"/api/v1/repositories/{repo_id}", headers=headers)
    assert del_resp.status_code == 200, del_resp.text
    assert del_resp.json() == {"success": True}

    # Refresh the user's repository list (what the UI shows after refresh)
    listed = client.get("/api/v1/repositories", headers=headers)
    assert listed.status_code == 200
    assert all(r["id"] != repo_id for r in listed.json())

    # And the database holds no orphan rows
    db2 = SessionLocal()
    try:
        repo_uuid = uuid.UUID(repo_id)
        assert db2.query(Repository).filter(Repository.id == repo_uuid).count() == 0
        assert db2.query(Analysis).filter(Analysis.repository_id == repo_uuid).count() == 0
        assert db2.query(AnalysisResultCache).filter(AnalysisResultCache.repository_id == repo_uuid).count() == 0
        assert db2.query(SecurityFinding).join(Analysis).filter(
            Analysis.repository_id == repo_uuid
        ).count() == 0
    finally:
        db2.close()


# ── T8: chatbot "Explain this page" is grounded in the current page ─────────

def test_chat_explain_this_page_uses_actual_scan_data(client, chat_user_headers, mock_llm):
    """'Explain this page' on a repository page with a completed scan must
    inject that scan's real data (repo name, scores, findings)."""
    repo_id = _seed_repo_with_scan("statemachine_chat@example.com", "ctx/explain-scan", risk_score=42)

    resp = client.post(
        "/api/v1/chat/ask",
        json={
            "message": "Explain this page",
            "current_page": "repo-detail",
            "repository_id": repo_id,
            "finding_context": {"type": "repository_scan", "repo_page": "security", "repository": "ctx/explain-scan", "risk_score": 42, "security_findings_count": 1, "security_findings": [{"issue": "Hardcoded credential", "severity": "Critical", "file": "app.py", "line": 5}]},
        },
        headers=chat_user_headers,
    )
    assert resp.status_code == 200, resp.text
    system = _capture_system_prompt(mock_llm)
    assert "ctx/explain-scan" in system                     # actual repository
    assert "42/100" in system                                # actual risk score
    assert "Hardcoded credential" in system                  # actual finding
    assert "Security Findings" in system                     # actual page (sub-tab)
    assert "explain the CURRENT page" in system              # prompt rule present


def test_chat_explain_this_page_before_any_scan(client, chat_user_headers, mock_llm):
    """'Explain this page' with NO scan yet must still name the page and the
    repository — and explicitly state no scan data exists (no hallucination)."""
    repo_id = _seed_repo_with_scan("statemachine_chat@example.com", "ctx/noscan-yet", with_findings=False)

    resp = client.post(
        "/api/v1/chat/ask",
        json={
            "message": "Explain this page",
            "current_page": "repo-detail",
            "repository_id": repo_id,
            "finding_context": {"type": "repository_page", "repository": "ctx/noscan-yet", "repo_page": "overview"},
        },
        headers=chat_user_headers,
    )
    assert resp.status_code == 200, resp.text
    system = _capture_system_prompt(mock_llm)
    assert "Repository Dashboard" in system                  # names the actual page
    assert "ctx/noscan-yet" in system                        # names the repository
    assert "no scan has been completed" in system            # honest no-data state
    # It must NOT present data as if a scan exists
    assert "Current repository scan context" not in system


def test_chat_explain_this_page_after_refresh_uses_db_scan(client, chat_user_headers, mock_llm):
    """After a refresh (frontend store empty), the backend injects the latest
    completed scan from the DB for the selected repository — so 'explain this
    page' still explains the current results."""
    repo_id = _seed_repo_with_scan("statemachine_chat@example.com", "ctx/refresh-db", risk_score=18)

    resp = client.post(
        "/api/v1/chat/ask",
        json={
            "message": "Explain this page",
            "current_page": "repo-detail",
            "repository_id": repo_id,
            "finding_context": {"type": "repository_page", "repository": "ctx/refresh-db", "repo_page": "overview"},
        },
        headers=chat_user_headers,
    )
    assert resp.status_code == 200, resp.text
    system = _capture_system_prompt(mock_llm)
    assert "Latest completed repository scan" in system      # DB-injected context
    assert "ctx/refresh-db" in system
    assert "18/100" in system
