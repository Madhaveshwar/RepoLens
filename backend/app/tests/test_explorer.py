import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4
from app.models.models import Repository
from app.database.database import SessionLocal

def get_auth_headers(client):
    email = "testexplorer@example.com"
    password = "SecretPass123"
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

@patch("app.routers.explorer.GitHubService")
@patch("app.routers.repositories.GitHubService")
def test_explorer_endpoints_flow(mock_gh_repo, mock_gh_explorer, client):
    headers = get_auth_headers(client)
    
    # Update user keys
    client.post(
        "/api/v1/users/keys",
        json={"github_pat": "mock-pat", "groq_api_key": "mock-groq-key"},
        headers=headers
    )

    # 1. Mock Repository Details
    mock_gh = mock_gh_repo.return_value
    mock_gh.get_repo_details.return_value = {
        "name": "mockowner/mockexplorer",
        "description": "mock repo description",
        "stars": 42,
        "forks": 1,
        "open_prs_count": 0,
        "open_issues_count": 2,
        "default_branch": "main",
        "languages": {"Python": 100}
    }
    mock_gh.get_open_pull_requests.return_value = []
    
    # Connect repository
    repo_resp = client.post(
        "/api/v1/repositories",
        json={"url": "https://github.com/mockowner/mockexplorer"},
        headers=headers
    )
    assert repo_resp.status_code == 201
    repo_id = repo_resp.json()["id"]

    # 2. Mock explorer tree retrieval
    mock_explorer = mock_gh_explorer.return_value
    
    mock_element1 = MagicMock()
    mock_element1.path = "main.py"
    mock_element1.type = "blob"
    
    mock_element2 = MagicMock()
    mock_element2.path = "utils"
    mock_element2.type = "tree"
    
    mock_element3 = MagicMock()
    mock_element3.path = "utils/helpers.py"
    mock_element3.type = "blob"
    
    mock_git_tree = MagicMock()
    mock_git_tree.tree = [mock_element1, mock_element2, mock_element3]
    
    mock_explorer.client.get_repo.return_value.get_git_tree.return_value = mock_git_tree
    
    # Call GET /repositories/{id}/explorer
    exp_resp = client.get(f"/api/v1/repositories/{repo_id}/explorer", headers=headers)
    assert exp_resp.status_code == 200
    tree_data = exp_resp.json()
    assert len(tree_data) == 2  # main.py and utils dir
    
    # 3. Mock file contents retrieval
    mock_explorer.get_file_content.return_value = "print('hello world')"
    
    file_resp = client.get(
        f"/api/v1/repositories/{repo_id}/files",
        params={"path": "main.py"},
        headers=headers
    )
    assert file_resp.status_code == 200
    assert file_resp.json()["content"] == "print('hello world')"
    assert file_resp.json()["path"] == "main.py"

    # 4. Mock save file updates
    mock_contents = MagicMock()
    mock_contents.sha = "oldfilesha"
    mock_explorer.client.get_repo.return_value.get_contents.return_value = mock_contents
    
    mock_explorer.client.get_repo.return_value.update_file.return_value = {
        "commit": MagicMock(sha="newcommitsha")
    }
    
    # Call POST /repositories/{id}/files
    with patch("app.routers.explorer.enqueue_analysis_task") as mock_celery_task:
        save_resp = client.post(
            f"/api/v1/repositories/{repo_id}/files",
            json={
                "path": "main.py",
                "content": "print('hello updated world')",
                "commit_message": "Updating file from tests"
            },
            headers=headers
        )
        assert save_resp.status_code == 200
        assert save_resp.json()["success"] is True
        assert "analysis_id" in save_resp.json()
        assert mock_celery_task.called is True
