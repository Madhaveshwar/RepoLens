import requests
import time
import json
import sys

BASE_URL = "http://localhost:8000/api/v1"
EMAIL = "test_reviewer@example.com"
PASSWORD = "Password123!"
REPO_URL = "https://github.com/Madhaveshwar/Automated-code-reviewer"

def run_test():
    print("=== STARTING SCAN VERIFICATION ===")
    
    # Login
    print("\n1. Logging in...")
    resp = requests.post(f"{BASE_URL}/auth/login", data={"username": EMAIL, "password": PASSWORD})
    if resp.status_code != 200:
        print(f"Login failed: {resp.status_code} - {resp.text}")
        return
    token = resp.json()["access_token"]
    print(f"Login successful! Access token obtained.")
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Check /me for Fallbacks
    print("\n2. Checking /me profile...")
    resp = requests.get(f"{BASE_URL}/users/me", headers=headers)
    print(json.dumps(resp.json(), indent=2))

    # 3. Check Diagnostics
    print("\n3. Checking diagnostics...")
    resp = requests.get(f"{BASE_URL}/users/me/diagnostics", headers=headers)
    print(json.dumps(resp.json(), indent=2))

    # 4. Connect Repository
    print(f"\n4. Connecting repository: {REPO_URL}...")
    resp = requests.post(f"{BASE_URL}/repositories", json={"url": REPO_URL}, headers=headers)
    if resp.status_code not in (200, 201):
        print(f"Repo connection failed: {resp.status_code} - {resp.text}")
        return
    repo_data = resp.json()
    repo_id = repo_data["id"]
    print(f"Repository connected successfully! ID: {repo_id}")

    # 5. Trigger Analysis
    print("\n5. Triggering analysis...")
    resp = requests.post(f"{BASE_URL}/analysis/trigger", json={"repository_id": repo_id}, headers=headers)
    if resp.status_code not in (200, 202):
        print(f"Analysis trigger failed: {resp.status_code} - {resp.text}")
        return
    analysis_id = resp.json()["id"]
    print(f"Analysis job started! ID: {analysis_id}")

    # 6. Poll Analysis Status
    print("\n6. Polling analysis status...")
    status = "pending"
    progress = 0
    while status in ("pending", "started", "running") or progress < 100:
        resp = requests.get(f"{BASE_URL}/analysis/{analysis_id}", headers=headers)
        if resp.status_code != 200:
            print(f"Failed to fetch analysis status: {resp.status_code}")
            break
        data = resp.json()
        status = data["status"]
        progress = data["progress"]
        print(f"Progress: {progress}% - Status: {status}")
        if "failed" in status.lower():
            print(f"Analysis failed! Details: {data.get('insights')}")
            break
        if progress == 100:
            break
        time.sleep(3)

    if progress == 100 and "failed" not in status.lower():
        print("\n=== SCAN COMPLETED SUCCESSFULLY ===")
        # Get security findings
        resp_sec = requests.get(f"{BASE_URL}/security/analysis/{analysis_id}", headers=headers)
        print(f"\n[Security Findings] Count: {len(resp_sec.json())}")
        if resp_sec.json():
            print(json.dumps(resp_sec.json()[:2], indent=2))
            
        # Get code smells
        resp_smells = requests.get(f"{BASE_URL}/code-quality/analysis/{analysis_id}", headers=headers)
        print(f"\n[Code Smells] Count: {len(resp_smells.json())}")
        if resp_smells.json():
            print(json.dumps(resp_smells.json()[:2], indent=2))

        # Get test suggestions
        resp_tests = requests.get(f"{BASE_URL}/tests/analysis/{analysis_id}", headers=headers)
        print(f"\n[Test Suggestions] Count: {len(resp_tests.json())}")
        if resp_tests.json():
            print(json.dumps(resp_tests.json()[:2], indent=2))

        # Get Health score details from Analysis overview
        print(f"\n[Health Rating Dashboard Calculation]")
        risk_score = resp.json().get("risk_score", 0)
        print(f"Health Rating: {100 - risk_score}/100")
        
        # Get exports / reports list
        resp_reports = requests.get(f"{BASE_URL}/reports", headers=headers)
        print(f"\n[Reports Generated] Count: {len(resp_reports.json())}")
        for r in resp_reports.json():
            print(f"- Type: {r['type']}, ID: {r['id']}, Created At: {r['created_at']}")

        # Get Dashboard metrics
        resp_dash = requests.get(f"{BASE_URL}/users/me/dashboard", headers=headers)
        print(f"\n[Dashboard Metrics]")
        print(json.dumps(resp_dash.json(), indent=2))

if __name__ == "__main__":
    run_test()
