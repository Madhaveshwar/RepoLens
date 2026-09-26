"""
Regression tests for the AI Assistant chat router.

Covers:
- Scan-context prompt serialization (frontend repository_scan dict + server-loaded DB context)
- Latest-scan DB loader returns the user's most recent completed scan with findings
- /chat/ask returns a real LLM answer (mocked provider) instead of an error
- /chat/ask/stream delivers token SSE events end-to-end with a mocked provider
- Friendly errors when no LLM key is configured
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from app.routers.chat import _build_context_prompt, _format_scan_context, _load_latest_scan_context


def _make_scan_context() -> dict:
    return {
        "type": "repository_scan",
        "repository": "demo/repo",
        "risk_score": 42,
        "status": "completed",
        "security_findings_count": 2,
        "code_smells_count": 1,
        "security_findings": [
            {"issue": "Hardcoded credential", "severity": "critical", "file": "config.py", "line": 10, "suggestion": "Use env var"},
            {"issue": "SQL injection", "severity": "high", "file": "db.py", "line": 20, "suggestion": "Parameterize"},
        ],
        "code_smells": [
            {"issue": "Long function", "severity": "medium", "file": "x.py", "line": 5},
        ],
    }


# ── Context prompt serialization ────────────────────────────────────────────

def test_context_prompt_includes_frontend_scan_context():
    prompt = _build_context_prompt("dashboard", _make_scan_context())
    assert "demo/repo" in prompt
    assert "Hardcoded credential" in prompt
    assert "SQL injection" in prompt
    assert "Long function" in prompt


def test_context_prompt_includes_db_scan_context():
    prompt = _build_context_prompt("dashboard", None, _make_scan_context())
    assert "Latest completed repository scan" in prompt
    assert "Hardcoded credential" in prompt


def test_context_prompt_without_context_is_empty():
    assert _build_context_prompt(None, None, None) == ""


def test_format_scan_context_lists_findings_with_files_and_lines():
    lines = _format_scan_context(_make_scan_context())
    joined = "\n".join(lines)
    assert "demo/repo" in joined
    assert "config.py" in joined and "10" in joined
    assert "Use env var" in joined


# ── Latest-scan DB loader ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_load_latest_scan_context_returns_latest_completed_scan(client):
    from app.database.database import Base, sync_engine
    Base.metadata.create_all(bind=sync_engine)

    import asyncio
    from app.database.database import AsyncSessionLocal
    from app.models.models import User, Repository, Analysis, SecurityFinding, CodeSmell
    from sqlalchemy import select, delete
    from datetime import datetime, timezone

    async with AsyncSessionLocal() as db:
        # Arrange: user + repo + two completed analyses, the older with findings
        user = User(email="chatctx@example.com", hashed_password="x")
        db.add(user)
        await db.flush()
        uid = user.id

        repo = Repository(name="ctx/older", user_id=uid)
        db.add(repo)
        await db.flush()
        older = Analysis(
            repository_id=repo.id, status="completed", risk_score=30,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        newer = Analysis(
            repository_id=repo.id, status="completed", risk_score=70,
            timestamp=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        db.add_all([older, newer])
        await db.flush()
        db.add(SecurityFinding(analysis_id=newer.id, issue="Newest finding", severity="high", file="a.py", line=1, suggestion="Fix it"))
        db.add(CodeSmell(analysis_id=newer.id, issue="Newest smell", severity="low", file="b.py", line=2, suggestion="Refactor"))
        await db.commit()

        # Act — context is loaded ONLY for the explicitly selected repository
        ctx = await _load_latest_scan_context(db, uid, str(repo.id))

        # Assert: picks the *newest* completed scan and includes its findings
        assert ctx is not None
        assert ctx["repository"] == "ctx/older"
        assert ctx["risk_score"] == 70
        assert ctx["security_findings_count"] == 1
        assert ctx["code_smells_count"] == 1
        assert ctx["security_findings"][0]["issue"] == "Newest finding"

        # Cleanup
        await db.execute(delete(SecurityFinding).where(SecurityFinding.analysis_id == newer.id))
        await db.execute(delete(CodeSmell).where(CodeSmell.analysis_id == newer.id))
        await db.execute(delete(Analysis).where(Analysis.id.in_([older.id, newer.id])))
        await db.delete(repo)
        await db.delete(user)
        await db.commit()


# ── Endpoints with a mocked LLM ─────────────────────────────────────────────

@pytest.fixture
def auth_headers(client):
    email = "chatapi@example.com"
    r = fixture_register_login(client, email, "SuperSecret123!")
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def fixture_register_login(client, email, password):
    client.post("/api/v1/auth/register", json={"email": email, "password": password})
    return client.post("/api/v1/auth/login", data={"username": email, "password": password})


def _mock_llm_response(text="**Scan Summary**\n\n- 2 critical findings\n- Risk score 42/100"):
    resp = MagicMock()
    choice = MagicMock()
    choice.message.content = text
    resp.choices = [choice]
    return resp


class _FakeStreamChunk:
    def __init__(self, content):
        choice = MagicMock()
        choice.delta.content = content
        self.choices = [choice]


@pytest.fixture
def mock_llm():
    with patch("app.routers.chat.build_llm_client") as mock_build:
        client = MagicMock()
        client.chat.completions.create.return_value = _mock_llm_response()
        # Streaming path returns an iterable of chunks
        client.chat.completions.create.side_effect = None

        def _create(**kwargs):
            if kwargs.get("stream"):
                return iter([
                    _FakeStreamChunk("Hello"),
                    _FakeStreamChunk(" from"),
                    _FakeStreamChunk(" RepoLens AI"),
                ])
            return _mock_llm_response()

        client.chat.completions.create.side_effect = _create
        mock_build.return_value = client
        yield mock_build


def test_chat_ask_streams_real_answer(client, auth_headers, mock_llm):
    resp = client.post(
        "/api/v1/chat/ask",
        json={"message": "Summarize this scan", "current_page": "dashboard"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "Scan Summary" in body["reply"]
    assert body["suggested_questions"]


def test_chat_ask_without_key_returns_friendly_error(client):
    email = "chatnokey@example.com"
    client.post("/api/v1/auth/register", json={"email": email, "password": "SuperSecret123!"})
    login = client.post("/api/v1/auth/login", data={"username": email, "password": "SuperSecret123!"})
    token = login.json()["access_token"]
    resp = client.post(
        "/api/v1/chat/ask",
        json={"message": "hi"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code in (400, 502)
    assert "Settings" in resp.json()["detail"]


def test_chat_ask_stream_emits_token_sse_events(client, auth_headers, mock_llm):
    resp = client.post(
        "/api/v1/chat/ask/stream",
        json={"message": "What are the critical security issues?", "current_page": "repositories"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")

    body = resp.text
    assert '"token"' in body
    assert "RepoLens AI" in body


# ── Repository-context behaviour (the 5 required cases) ────────────────────

def _capture_system_prompt(mock_llm) -> str:
    """Return the system prompt the chat endpoint sent to the LLM.

    mock_llm patches build_llm_client; the endpoint calls .create() on the
    client that the mocked builder returns.
    """
    client = mock_llm.return_value
    kwargs = client.chat.completions.create.call_args.kwargs
    return kwargs["messages"][0]["content"]


def test_chat_case_a_no_repository_general_question(client, auth_headers, mock_llm):
    """CASE A — no repo: general questions answered normally, no invented repo."""
    resp = client.post(
        "/api/v1/chat/ask",
        json={"message": "What is architecture analysis?", "current_page": "settings"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    system = _capture_system_prompt(mock_llm)
    # Explicit no-context instruction is present so no repo is hallucinated
    assert "No repository scan context is available" in system
    assert "has not been scanned yet" in system


def test_chat_case_b_repository_with_completed_scan_uses_real_data(client, auth_headers, mock_llm):
    """CASE B — repo scanned: context includes REAL repo name + findings."""
    scan_ctx = _make_scan_context()  # demo/repo, hardcoded credential @ config.py:10
    resp = client.post(
        "/api/v1/chat/ask",
        json={"message": "Explain the architecture of this repository.",
              "current_page": "repository", "finding_context": scan_ctx},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    system = _capture_system_prompt(mock_llm)
    assert "demo/repo" in system
    assert "Hardcoded credential" in system
    assert "config.py" in system
    # Must NOT claim data was unavailable — real context was provided
    assert "No repository scan context is available" not in system


def test_chat_case_c_repository_selected_but_not_scanned(client, auth_headers, mock_llm):
    """CASE C — repo page but NO completed scan anywhere: prompt must say
    the repository has not been scanned and suggest running a scan."""
    with patch("app.routers.chat._load_latest_scan_context", return_value=None):
        resp = client.post(
            "/api/v1/chat/ask",
            json={"message": "Explain the architecture of this repository.",
                  "current_page": "repository"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    system = _capture_system_prompt(mock_llm)
    assert "not been scanned" in system or "running a scan first" in system
    # No repository name can leak into the context because none exists
    assert "Current repository scan context" not in system


def test_chat_case_c_stream_repository_not_scanned(client, auth_headers, mock_llm):
    """CASE C for the streaming endpoint."""
    with patch("app.routers.chat._load_latest_scan_context", return_value=None):
        resp = client.post(
            "/api/v1/chat/ask/stream",
            json={"message": "Summarize this scan", "current_page": "repository"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    system = _capture_system_prompt(mock_llm)
    assert "not been scanned" in system or "running a scan first" in system


def test_chat_case_d_unrelated_question_gets_no_forced_repo_context(client, auth_headers, mock_llm):
    """CASE D — unrelated question: no repository scan context is injected."""
    with patch("app.routers.chat._load_latest_scan_context", return_value=None):
        resp = client.post(
            "/api/v1/chat/ask",
            json={"message": "How do I write a Python list comprehension?",
                  "current_page": "settings"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    system = _capture_system_prompt(mock_llm)
    assert "Current repository scan context" not in system
    assert "Latest completed repository scan" not in system


def test_chat_case_e_missing_evidence_rule_present(client, auth_headers, mock_llm):
    """CASE E — the grounding rule requiring 'couldn't find enough evidence'
    must always be part of the system prompt."""
    resp = client.post(
        "/api/v1/chat/ask",
        json={"message": "How many lines does main.py have?", "current_page": "repository"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    system = _capture_system_prompt(mock_llm)
    assert "couldn't find enough evidence in the scanned repository" in system
