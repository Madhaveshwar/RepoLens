import os
import requests
from backend.app.config import settings

def main():
    token = settings.GITHUB_TOKEN.strip()
    print(f"Token length: {len(token)}")
    print(f"Token starts with: {token[:10]}...")
    
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json"
    }
    
    # Check authenticated user
    resp = requests.get("https://api.github.com/user", headers=headers)
    if resp.status_code != 200:
        print(f"Failed to fetch user: {resp.status_code} - {resp.text}")
        return
        
    user_data = resp.json()
    username = user_data.get("login")
    print(f"Authenticated as GitHub user: {username}")
    
    # Check permissions on repository
    repo = "alajangimadhulika-code/AI-Resume-Screening-Interview-bot"
    perm_url = f"https://api.github.com/repos/{repo}/collaborators/{username}/permission"
    resp = requests.get(perm_url, headers=headers)
    if resp.status_code != 200:
        print(f"Failed to fetch repository permissions for {username}: {resp.status_code} - {resp.text}")
        print("Note: This usually means you do not have admin/write access to check collaborator permissions, or you are not a collaborator.")
    else:
        print(f"Repository permissions response: {resp.json()}")

if __name__ == "__main__":
    main()
