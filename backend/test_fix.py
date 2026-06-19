import requests
import json
import sys

BASE_URL = "http://localhost:8000/api/v1"
EMAIL = "test_reviewer@example.com"
PASSWORD = "Password123!"

def run_fix_test():
    print("=== STARTING AUTO-FIX VERIFICATION ===")
    
    # 1. Login
    print("\n1. Logging in...")
    resp = requests.post(f"{BASE_URL}/auth/login", data={"username": EMAIL, "password": PASSWORD})
    if resp.status_code != 200:
        print(f"Login failed: {resp.status_code} - {resp.text}")
        return
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("Logged in successfully.")

    # 2. Get connected repositories
    print("\n2. Fetching connected repositories...")
    resp = requests.get(f"{BASE_URL}/repositories", headers=headers)
    repos = resp.json()
    if not repos:
        print("No repositories connected.")
        return
    repo = None
    for r in repos:
        if "Madhaveshwar/Automated-code-reviewer" in r["name"]:
            repo = r
            break
    if not repo:
        repo = repos[0]
    repo_id = repo["id"]
    repo_name = repo["name"]
    print(f"Found repository: {repo_name} (ID: {repo_id})")

    # 3. Get last completed analysis
    print("\n3. Fetching completed analyses...")
    resp = requests.get(f"{BASE_URL}/analysis/repo/{repo_id}", headers=headers)
    analyses = [a for a in resp.json() if a["status"] == "completed"]
    if not analyses:
        print("No completed analyses found for this repository. Run a scan first.")
        return
    last_analysis = analyses[0]
    analysis_id = last_analysis["id"]
    print(f"Using analysis ID: {analysis_id}")

    # 4. Fetch security findings
    print("\n4. Fetching security findings...")
    resp = requests.get(f"{BASE_URL}/security/analysis/{analysis_id}", headers=headers)
    findings = resp.json()
    if not findings:
        print("No security findings found in the last analysis.")
        return
    
    # Let's find one finding with before_code or just use the first finding
    finding = None
    for f in findings:
        if f.get("before_code"):
            finding = f
            break
    if not finding:
        finding = findings[0]
        
    finding_id = finding["id"]
    file_path = finding["file"]
    print(f"Found security finding ID: {finding_id} in file: {file_path}")
    print(f"Before Code in Finding: {finding.get('before_code')}")

    # 5. Generate Fix
    print(f"\n5. Requesting fix generation for {file_path}...")
    resp = requests.post(
        f"{BASE_URL}/fixes/generate",
        json={
            "repository_id": repo_id,
            "file_path": file_path,
            "issue_id": finding_id,
            "issue_type": "security"
        },
        headers=headers
    )
    if resp.status_code not in (200, 201):
        print(f"Fix generation failed: {resp.status_code} - {resp.text}")
        return
    fix_data = resp.json()
    generated_fix_id = fix_data["id"]
    print(f"Fix generated successfully! ID: {generated_fix_id}")
    print(f"Original Code:\n{fix_data.get('original_code')}")
    print(f"Fixed Code:\n{fix_data.get('fixed_code')}")
    print(f"Explanation: {fix_data.get('explanation')}")
    print(f"Confidence: {fix_data.get('confidence_score')}%")

    # 6. Apply Fix
    print("\n6. Applying fix (creating branch & pushing)...")
    resp = requests.post(
        f"{BASE_URL}/fixes/apply",
        json={"generated_fix_id": generated_fix_id},
        headers=headers
    )
    if resp.status_code not in (200, 201):
        print(f"Fix application failed: {resp.status_code} - {resp.text}")
        return
    apply_data = resp.json()
    branch_name = apply_data["branch_name"]
    print(f"Fix applied successfully to branch: {branch_name}")

    # 7. Create Pull Request
    print("\n7. Creating pull request...")
    resp = requests.post(
        f"{BASE_URL}/fixes/create-pr",
        json={"generated_fix_id": generated_fix_id},
        headers=headers
    )
    if resp.status_code not in (200, 201):
        print(f"PR creation failed: {resp.status_code} - {resp.text}")
        return
    pr_data = resp.json()
    print(f"Pull Request created successfully! PR URL: {pr_data['pr_url']}")

    # 8. Check Dashboard and Fix History
    print("\n8. Checking fix history...")
    resp = requests.get(f"{BASE_URL}/fixes/history", headers=headers)
    print(json.dumps(resp.json(), indent=2))

if __name__ == "__main__":
    run_fix_test()
