"""Regression tests for email normalization in the auth flow.

Guards against the bug where a user registered with a mixed-case email
(e.g. "John@Example.COM", domain auto-lowercased by pydantic on storage)
could never sign in because login compared emails case-sensitively.
"""

import pytest

from app.routers.auth import _normalize_email, _find_user_by_email


PASSWORD = "SuperSecret123!"


def _register(client, email, password=PASSWORD):
    return client.post("/api/v1/auth/register", json={"email": email, "password": password})


def _login(client, email, password=PASSWORD):
    return client.post("/api/v1/auth/login", data={"username": email, "password": password})


# ── Unit: normalization helper ───────────────────────────────────────────────

def test_normalize_email_strips_and_lowercases():
    assert _normalize_email("  John@Example.COM  ") == "john@example.com"
    assert _normalize_email("USER@site.io") == "user@site.io"
    assert _normalize_email(None) == ""  # type: ignore[arg-type]
    assert _normalize_email("") == ""


# ── Registration stores normalized emails ────────────────────────────────────

def test_register_stores_lowercased_email(client):
    r = _register(client, "MixedCase.Reg@Example.COM")
    assert r.status_code == 201, r.text
    assert r.json()["email"] == "mixedcase.reg@example.com"


def test_register_rejects_case_variant_of_existing_email(client):
    assert _register(client, "Dupe@Example.com").status_code == 201
    r = _register(client, "DUPE@EXAMPLE.COM")
    assert r.status_code == 400
    assert "already exists" in r.json()["detail"]


# ── Login matches case-insensitively and tolerates whitespace ───────────────

def test_login_with_mixed_case_email_matches(client):
    assert _register(client, "CaseTest@Example.COM").status_code == 201
    # Same case as registered (post-normalization)
    assert _login(client, "CaseTest@example.com").status_code == 200
    # All-uppercase as a mobile autocapitalize might send
    assert _login(client, "CASETEST@EXAMPLE.COM").status_code == 200
    # The raw pre-normalization string the user originally typed
    assert _login(client, "CaseTest@Example.COM").status_code == 200
    # Lowercase everything
    assert _login(client, "casetest@example.com").status_code == 200


def test_login_with_surrounding_whitespace_matches(client):
    assert _register(client, "whitespace@example.com").status_code == 201
    assert _login(client, "  whitespace@example.com  ").status_code == 200


def test_login_still_rejects_wrong_password(client):
    assert _register(client, "wrongpw@example.com").status_code == 201
    r = _login(client, "wrongpw@example.com", "NotThePassword!")
    assert r.status_code == 401
    assert "email or password" in r.json()["detail"].lower()


def test_login_rejects_unknown_email(client):
    r = _login(client, "ghost-user-xyz@example.com", "Whatever123!")
    assert r.status_code == 401


# ── Forgot/reset password works through the same normalized lookup ──────────

def test_forgot_password_finds_mixed_case_user(client):
    assert _register(client, "ForgotCase@Example.COM").status_code == 201
    r = client.post("/api/v1/auth/forgot-password", json={"email": "forgotcase@example.com"})
    assert r.status_code == 200
    # Dev environment returns the reset link when SMTP is not configured
    assert r.json().get("dev_reset_url"), r.json()


@pytest.mark.asyncio
async def test_find_user_by_email_helper_is_case_insensitive(client):
    from app.database.database import Base, sync_engine, AsyncSessionLocal
    Base.metadata.create_all(bind=sync_engine)

    from app.models.models import User
    from sqlalchemy import select, delete

    async with AsyncSessionLocal() as db:
        db.add(User(email="Helper.Find@Example.COM", hashed_password="x"))
        await db.commit()

        user = await _find_user_by_email(db, "helper.find@example.com")
        assert user is not None
        user = await _find_user_by_email(db, "HELPER.FIND@EXAMPLE.COM")
        assert user is not None
        user = await _find_user_by_email(db, "  helper.find@example.com ")
        assert user is not None
        assert await _find_user_by_email(db, "missing@example.com") is None

        await db.execute(delete(User).where(User.email == "helper.find@example.com"))
        await db.commit()
