"""Credential validation flow tests (users /keys endpoint).

Covers:
- all valid credentials           -> 200, persisted encrypted
- one invalid credential          -> 400 with provider name + safe reason
- multiple invalid credentials    -> 400 listing every failed provider
- optional empty providers        -> not validated, never reported as failed
- provider validation exception   -> safe plain-text reason (no raw exception)
- malformed response content      -> no markup/keys leak into error detail
- successful save                 -> persisted, booleans returned, nothing plaintext
"""
import pytest
from unittest.mock import patch

from app.auth.encryption import encryptor
from app.routers.users import _safe_validation_reason, _sanitize_error_detail


def get_auth_headers(client, email, password="CredTest123"):
    client.post("/api/v1/auth/register", json={"email": email, "password": password})
    login = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ── _safe_validation_reason unit tests ──────────────────────────────────────

@pytest.mark.parametrize("status_text", ["Connected", "Invalid Key", "Missing Key", "Timeout", "Unknown"])
def test_safe_reason_known_statuses_pass_through(status_text):
    assert _safe_validation_reason(status_text) == status_text


def test_safe_reason_http_error_keeps_status_only():
    assert _safe_validation_reason("Error (HTTP 503)") == "Error (HTTP 503)"


def test_safe_reason_raw_exception_never_leaks_content():
    """The exact deployed bug class: raw exception text (which can contain
    markup such as <svg> from provider error pages) must never be forwarded."""
    raw = "Error: 400, message='Bad Request', url='...<svg xmlns=\"http://www.w3.org/2000/svg\">'"
    reason = _safe_validation_reason(raw)
    assert "<" not in reason and ">" not in reason
    assert "svg" not in reason.lower()
    assert "Provider could not be reached" in reason


# ── _sanitize_error_detail unit tests ───────────────────────────────────────

def test_sanitize_error_detail_preserves_line_structure():
    detail = "The following API keys failed validation:\nGitHub PAT: Invalid Key\nGroq API Key: Invalid Key"
    out = _sanitize_error_detail(detail)
    assert out.count("\n") == 2
    assert "GitHub PAT: Invalid Key" in out
    assert "Groq API Key: Invalid Key" in out


def test_sanitize_error_detail_strips_markup_and_control_chars():
    detail = "Header:\nGroq API Key: Error: <svg onload=\"x\">bad\x1b[31m stuff"
    out = _sanitize_error_detail(detail)
    assert "<" not in out and ">" not in out
    assert "\x1b" not in out
    assert "Groq API Key: Error: svg onloadxbad31m stuff" in out


# ── /users/keys endpoint tests ──────────────────────────────────────────────

@patch("app.routers.users.test_github_api", return_value="Connected")
@patch("app.routers.users.test_llm_api", return_value="Connected")
def test_save_all_valid_credentials(mock_llm, mock_github, client):
    headers = get_auth_headers(client, "credvalid@example.com")
    resp = client.post(
        "/api/v1/users/keys",
        json={"github_pat": "ghp_valid", "groq_api_key": "gsk_valid"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_github_pat"] is True
    assert data["has_groq_api_key"] is True


@patch("app.routers.users.test_github_api", return_value="Connected")
@patch("app.routers.users.test_llm_api", return_value="Invalid Key")
def test_save_one_invalid_credential_lists_provider(mock_llm, mock_github, client):
    headers = get_auth_headers(client, "credinvalid@example.com")
    resp = client.post(
        "/api/v1/users/keys",
        json={"github_pat": "ghp_ok", "openai_api_key": "sk-bad"},
        headers=headers,
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "OpenAI API Key" in detail
    assert "Invalid Key" in detail
    # Not persisted
    me = client.get("/api/v1/users/me", headers=headers).json()
    assert me["has_openai_api_key"] is False
    assert me["has_github_pat"] is False  # all-or-nothing on failure


@patch("app.routers.users.test_github_api", return_value="Invalid Key")
@patch("app.routers.users.test_llm_api", return_value="Invalid Key")
def test_save_multiple_invalid_credentials_all_listed(mock_llm, mock_github, client):
    headers = get_auth_headers(client, "credmulti@example.com")
    resp = client.post(
        "/api/v1/users/keys",
        json={"github_pat": "ghp_bad", "groq_api_key": "gsk_bad", "claude_api_key": "sk-bad"},
        headers=headers,
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "GitHub PAT" in detail
    assert "Groq API Key" in detail
    assert "Claude API Key" in detail


@patch("app.routers.users.test_github_api", return_value="Connected")
@patch("app.routers.users.test_llm_api", return_value="Connected")
def test_empty_optional_providers_not_validated_or_reported(mock_llm, mock_github, client):
    headers = get_auth_headers(client, "credempty@example.com")
    # Only two keys supplied — the other four stay empty and must NOT appear
    # in any validation error, nor be reported as failed.
    resp = client.post(
        "/api/v1/users/keys",
        json={"github_pat": "ghp_ok", "groq_api_key": "gsk_ok"},
        headers=headers,
    )
    assert resp.status_code == 200
    me = resp.json()
    for field in ("has_openai_api_key", "has_claude_api_key", "has_gemini_api_key", "has_openrouter_api_key"):
        assert me[field] is False


def test_empty_payload_rejected_without_validation(client):
    headers = get_auth_headers(client, "crednone@example.com")
    resp = client.post("/api/v1/users/keys", json={}, headers=headers)
    assert resp.status_code == 400
    assert "at least one" in resp.json()["detail"].lower() or "enter" in resp.json()["detail"].lower()


@patch("app.routers.users.test_github_api", return_value="Connected")
@patch(
    "app.routers.users.test_llm_api",
    side_effect=Exception("400, message='<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>'"),
)
def test_provider_exception_produces_safe_reason(mock_llm, mock_github, client):
    headers = get_auth_headers(client, "credexc@example.com")
    resp = client.post(
        "/api/v1/users/keys",
        json={"github_pat": "ghp_ok", "gemini_api_key": "AIza-bad"},
        headers=headers,
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "<svg" not in detail
    assert "svg" not in detail.lower()
    assert "Gemini API Key" in detail  # provider is still identified
    assert "Provider could not be reached" in detail


@patch("app.routers.users.test_github_api", return_value="Connected")
@patch("app.routers.users.test_llm_api", return_value="Invalid Key")
def test_error_detail_never_contains_key_material(mock_llm, mock_github, client):
    """The submitted key value must never appear anywhere in the response."""
    headers = get_auth_headers(client, "credleak@example.com")
    secret = "sk-super-secret-value-12345"
    resp = client.post(
        "/api/v1/users/keys",
        json={"github_pat": "ghp_ok", "openai_api_key": secret},
        headers=headers,
    )
    assert resp.status_code == 400
    body = resp.text
    assert secret not in body


@patch("app.routers.users.test_github_api", return_value="Connected")
@patch("app.routers.users.test_llm_api", return_value="Connected")
def test_saved_credentials_are_encrypted_not_plaintext(mock_llm, mock_github, client):
    headers = get_auth_headers(client, "credenc@example.com")
    resp = client.post(
        "/api/v1/users/keys",
        json={"github_pat": "ghp_encrypted-check", "groq_api_key": "gsk_encrypted-check"},
        headers=headers,
    )
    assert resp.status_code == 200
    # Nothing in any response ever carries the plaintext value.
    assert "ghp_encrypted-check" not in resp.text
    assert "gsk_encrypted-check" not in resp.text


@patch("app.routers.users.test_github_api", return_value="Connected")
@patch("app.routers.users.test_llm_api", return_value="Connected")
def test_roundtrip_encryption(mock_llm, mock_github, client):
    """Stored value must decrypt back to the submitted key (AES-256 via encryptor)."""
    headers = get_auth_headers(client, "credround@example.com")
    resp = client.post("/api/v1/users/keys", json={"groq_api_key": "gsk_roundtrip"}, headers=headers)
    assert resp.status_code == 200
    # Fetch the stored ciphertext through the sync session (same DB).
    from sqlalchemy import select
    from app.database.database import SessionLocal
    from app.models.models import User

    with SessionLocal() as session:
        user = session.execute(
            select(User).where(User.email == "credround@example.com")
        ).scalar_one()

    assert user.groq_api_key_encrypted != "gsk_roundtrip"
    assert encryptor.decrypt(user.groq_api_key_encrypted) == "gsk_roundtrip"
