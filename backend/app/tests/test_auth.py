def test_read_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Welcome" in response.json()["message"]

def test_register_and_login(client):
    # Register
    email = "test@example.com"
    password = "SecretPass123"
    reg_response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password}
    )
    assert reg_response.status_code == 201
    data = reg_response.json()
    assert data["email"] == email
    assert "id" in data

    # Login
    login_response = client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password}
    )
    assert login_response.status_code == 200
    token_data = login_response.json()
    assert "access_token" in token_data
    assert token_data["token_type"] == "bearer"


def test_password_hashing_and_verification():
    from app.auth.security import get_password_hash_sync, verify_password_sync
    plain_password = "my_super_secret_pass_123"
    hashed = get_password_hash_sync(plain_password)
    
    assert hashed != plain_password
    assert len(hashed) > 10
    
    # Successful verification
    assert verify_password_sync(plain_password, hashed) is True
    
    # Failed verification (wrong password)
    assert verify_password_sync("wrong_password", hashed) is False

