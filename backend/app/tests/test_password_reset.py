"""End-to-end tests for the forgot/reset password flow."""
import pytest


def _register(client, email, password):
    r = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text


def _login(client, email, password):
    return client.post("/api/v1/auth/login", data={"username": email, "password": password})


def _request_reset(client, email):
    return client.post("/api/v1/auth/forgot-password", json={"email": email})


def _reset_password(client, token, new_password, confirm_password=None):
    return client.post(
        "/api/v1/auth/reset-password",
        json={
            "token": token,
            "new_password": new_password,
            "confirm_password": confirm_password if confirm_password is not None else new_password,
        },
    )


def test_full_password_reset_flow(client):
    """Register → forgot password → dev reset link → reset → login with new password."""
    email = "reset_flow_user@example.com"
    old_password = "OldPassword123"
    new_password = "NewPassword456"

    _register(client, email, old_password)
    assert _login(client, email, old_password).status_code == 200

    # Forgot password — no SMTP configured in tests, so dev mode returns a link
    r = _request_reset(client, email)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "message" in body
    assert body.get("dev_reset_url"), "dev_reset_url must be present in dev mode (no SMTP)"
    assert "token=" in body["dev_reset_url"]
    token = body["dev_reset_url"].split("token=", 1)[1]
    assert token

    # Reset the password
    r = _reset_password(client, token, new_password)
    assert r.status_code == 200, r.text

    # Old password no longer works
    assert _login(client, email, old_password).status_code == 401

    # New password works
    assert _login(client, email, new_password).status_code == 200


def test_reset_token_is_single_use(client):
    email = "single_use_user@example.com"
    _register(client, email, "Password123")

    r = _request_reset(client, email)
    token = r.json()["dev_reset_url"].split("token=", 1)[1]

    assert _reset_password(client, token, "NewPassword456").status_code == 200

    # Reusing the same token must fail
    r = _reset_password(client, token, "AnotherPass789")
    assert r.status_code == 400
    assert "already been used" in r.json()["detail"]

    # And the second reset must not have succeeded
    assert _login(client, email, "AnotherPass789").status_code == 401
    assert _login(client, email, "NewPassword456").status_code == 200


def test_forgot_password_unknown_email_does_not_leak(client):
    """Generic response with no dev link for unknown emails."""
    r = _request_reset(client, "ghost_user@example.com")
    assert r.status_code == 200
    body = r.json()
    assert "message" in body
    assert not body.get("dev_reset_url")


def test_reset_password_invalid_token(client):
    r = _reset_password(client, "not-a-real-token", "NewPassword456")
    assert r.status_code == 400


def test_reset_password_mismatched_confirmation(client):
    email = "mismatch_user@example.com"
    _register(client, email, "Password123")

    r = _request_reset(client, email)
    token = r.json()["dev_reset_url"].split("token=", 1)[1]

    r = _reset_password(client, token, "NewPassword456", "DifferentPass789")
    assert r.status_code == 400
    assert "do not match" in r.json()["detail"]

    # Token was not consumed by the failed attempt
    assert _reset_password(client, token, "NewPassword456").status_code == 200


def test_reset_password_too_short(client):
    email = "short_pass_user@example.com"
    _register(client, email, "Password123")

    r = _request_reset(client, email)
    token = r.json()["dev_reset_url"].split("token=", 1)[1]

    r = _reset_password(client, token, "short")
    assert r.status_code == 400
    assert "8 characters" in r.json()["detail"]


def test_new_reset_request_invalidates_previous_token(client):
    """Requesting a second reset link invalidates the first unused token."""
    email = "invalidate_user@example.com"
    _register(client, email, "Password123")

    r1 = _request_reset(client, email)
    token1 = r1.json()["dev_reset_url"].split("token=", 1)[1]

    r2 = _request_reset(client, email)
    token2 = r2.json()["dev_reset_url"].split("token=", 1)[1]

    # Old token no longer works, new one does
    assert _reset_password(client, token1, "NewPassword456").status_code == 400
    assert _reset_password(client, token2, "NewPassword456").status_code == 200
