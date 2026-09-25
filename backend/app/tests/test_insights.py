"""
Tests for the repository insights features:

1. Health trend  2. Dependencies  3. Duplicates  4. Technical debt
5. Architecture  6. Complexity    7. PR review   8. Commit analysis

Covers: authentication, invalid repo IDs, empty data, filters,
deterministic analyzers on real content, and report integration.
"""

import pytest
import json
from unittest.mock import patch, MagicMock
from uuid import uuid4

from app.database.database import SessionLocal
from app.models.models import (
    User, Repository, Analysis,
    SecurityFinding, CodeSmell, HealthScore,
    RepositoryHealthSnapshot, DependencyFinding, DuplicateCodeFinding,
    TechnicalDebtFinding, ArchitectureAnalysis, ComplexityFinding,
)


def get_auth_headers(client, email="insights@example.com", password="TestPass123"):
    client.post("/api/v1/auth/register", json={"email": email, "password": password})
    login_resp = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def seed_repo_with_scan(email="insights@example.com", with_findings=True, with_insights=True, client=None):
    """Create a user + repo + completed analysis, optionally with findings
    and insight rows, mirroring what the scan pipeline persists.
    Pass `client` to auto-register the user first."""
    db = SessionLocal()
    user = db.query(User).filter_by(email=email).first()
    if user is None:
        # Auto-register via the auth router (needs password hashing context)
        from app.auth.security import get_password_hash
        user = User(email=email, hashed_password=get_password_hash("TestPass123"))
        db.add(user)
        db.commit()
    repo = Repository(user_id=user.id, name="owner/insights-repo", default_branch="main")
    db.add(repo)
    db.commit()

    analysis = Analysis(repository_id=repo.id, status="completed", progress=100, risk_score=20)
    db.add(analysis)
    db.commit()

    if with_findings:
        for sev in ("Critical", "High", "Medium"):
            db.add(SecurityFinding(
                analysis_id=analysis.id, file="app.py", line=5,
                severity=sev, issue=f"{sev} issue", suggestion="fix",
                before_code="", after_code="",
            ))
        db.add(CodeSmell(
            analysis_id=analysis.id, file="app.py", line=10,
            severity="Medium", issue="long function", suggestion="refactor",
            before_code="", after_code="",
        ))
        db.add(HealthScore(analysis_id=analysis.id, health_score=72))
        db.commit()

    if with_insights:
        db.add(DependencyFinding(
            analysis_id=analysis.id, ecosystem="pip", manifest_file="requirements.txt",
            package_name="requests", version_spec="==2.19.0", resolved_version="2.19.0",
            status="known_vulnerable", severity="High", advisory_id="CVE-2018-18074",
            vulnerable_range="<2.20.0", recommended_version="2.20.0",
            advisory_url="https://nvd.nist.gov/vuln/detail/CVE-2018-18074",
            evidence="Resolved version 2.19.0 falls within the documented affected range <2.20.0.",
        ))
        db.add(DependencyFinding(
            analysis_id=analysis.id, ecosystem="npm", manifest_file="package.json",
            package_name="react", version_spec="^18.0.0", resolved_version="18.0.0",
            status="unknown", evidence="Unverified: no advisory data available.",
        ))
        db.add(DuplicateCodeFinding(
            analysis_id=analysis.id,
            file_a="src/a.py", start_line_a=1, end_line_a=8,
            file_b="src/b.py", start_line_b=20, end_line_b=27,
            similarity=95, duplicated_lines=8, token_hash="abc123", snippet="def foo():",
        ))
        db.add(TechnicalDebtFinding(
            analysis_id=analysis.id, category="security", severity="Critical",
            title="1 Critical security finding(s)", evidence="1 finding detected.",
            file="app.py", line_start=5, estimated_effort_hours=4.0,
            remediation="Fix it.",
        ))
        db.add(ArchitectureAnalysis(
            analysis_id=analysis.id,
            result={
                "summary": {"structure": {"total_files": 10}, "languages": {"Python": 8}},
                "frameworks": [{"name": "FastAPI", "category": "Backend framework", "evidence": ["Declared in requirements.txt"]}],
                "layers": [{"layer": "tests", "evidence_directories": ["tests"]}],
                "components": [{"name": "app", "file_count": 6}],
                "entry_points": ["main.py"],
                "internal_dependencies": [],
                "external_dependencies": [],
                "concerns": [],
            },
        ))
        db.add(ComplexityFinding(
            analysis_id=analysis.id, file="app.py", name="process", kind="function",
            line_start=10, line_end=60, cyclomatic_complexity=18, nesting_depth=5,
            length_lines=51, language="Python", severity="High",
            explanation="High complexity.", suggestion="Split it.",
        ))
        db.add(RepositoryHealthSnapshot(
            repository_id=repo.id, analysis_id=analysis.id, branch="main",
            commit_sha="deadbeef", health_score=72, security_score=54,
            code_quality_score=92, code_smell_count=1, critical_count=1,
            high_count=1, medium_count=1, low_count=0, total_issue_count=4,
        ))
        db.commit()

    repo_id = str(repo.id)
    analysis_id = str(analysis.id)
    db.close()
    return repo_id, analysis_id


# ── Authentication / access control ──────────────────────────────────

def test_insights_endpoints_require_auth(client):
    # Register the user first, then seed (seed_repo_with_scan requires the user row)
    get_auth_headers(client, "authreq@example.com")
    repo_id, _ = seed_repo_with_scan("authreq@example.com", with_findings=False, with_insights=False)
    for path in (
        f"/api/v1/repositories/{repo_id}/health-trend",
        f"/api/v1/repositories/{repo_id}/dependencies",
        f"/api/v1/repositories/{repo_id}/duplicates",
        f"/api/v1/repositories/{repo_id}/technical-debt",
        f"/api/v1/repositories/{repo_id}/architecture",
        f"/api/v1/repositories/{repo_id}/complexity",
        f"/api/v1/repositories/{repo_id}/pull-requests",
        f"/api/v1/repositories/{repo_id}/commits",
    ):
        resp = client.get(path)
        assert resp.status_code == 401, f"{path} should require auth"


def test_insights_invalid_repo_id_404(client):
    headers = get_auth_headers(client, "invalidrepo@example.com")
    fake_id = str(uuid4())
    for path in (
        f"/api/v1/repositories/{fake_id}/health-trend",
        f"/api/v1/repositories/{fake_id}/dependencies",
        f"/api/v1/repositories/{fake_id}/technical-debt",
    ):
        resp = client.get(path, headers=headers)
        assert resp.status_code == 404


def test_insights_repo_of_other_user_404(client):
    get_auth_headers(client, "owner1@example.com")
    repo_id, _ = seed_repo_with_scan("owner1@example.com", with_findings=False, with_insights=False)
    other_headers = get_auth_headers(client, "owner2@example.com")
    resp = client.get(f"/api/v1/repositories/{repo_id}/health-trend", headers=other_headers)
    assert resp.status_code == 404


# ── 0. Repository overview ───────────────────────────────────────────

def test_overview_requires_auth(client):
    get_auth_headers(client, "ovauth@example.com")
    repo_id, _ = seed_repo_with_scan("ovauth@example.com", with_findings=False, with_insights=False)
    resp = client.get(f"/api/v1/repositories/{repo_id}/overview")
    assert resp.status_code == 401, "overview should require auth"


def test_overview_other_users_repo_404(client):
    get_auth_headers(client, "ovowner1@example.com")
    repo_id, _ = seed_repo_with_scan("ovowner1@example.com", with_findings=False, with_insights=False)
    other_headers = get_auth_headers(client, "ovowner2@example.com")
    resp = client.get(f"/api/v1/repositories/{repo_id}/overview", headers=other_headers)
    assert resp.status_code == 404


def test_overview_no_scan_returns_honest_empty_state(client):
    """A repo without a completed scan reports scan=None, not fake data."""
    get_auth_headers(client, "ovempty@example.com")
    db = SessionLocal()
    user = db.query(User).filter_by(email="ovempty@example.com").first()
    repo = Repository(user_id=user.id, name="owner/insights-repo", default_branch="main")
    db.add(repo)
    db.commit()
    repo_id = str(repo.id)
    db.close()

    headers = get_auth_headers(client, "ovempty@example.com")
    resp = client.get(f"/api/v1/repositories/{repo_id}/overview", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["scan"] is None
    assert "No completed repository scan" in data["message"]
    assert data["repository"]["name"] == "owner/insights-repo"


def test_overview_returns_real_counts_from_persisted_rows(client):
    """Overview counts must match the persisted findings for this scan."""
    repo_id, analysis_id = seed_repo_with_scan("ovcounts@example.com", with_findings=True, with_insights=True)
    headers = get_auth_headers(client, "ovcounts@example.com")
    resp = client.get(f"/api/v1/repositories/{repo_id}/overview", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    scan = data["scan"]
    assert scan["analysis_id"] == analysis_id
    assert scan["health_score"] == 72
    assert scan["files_analyzed"] == 0  # seeded without file count, still real value
    counts = data["counts"]
    assert counts["security_issues"] == 3
    assert counts["critical_security"] == 1
    assert counts["high_security"] == 1
    assert counts["code_smells"] == 1
    assert counts["dependencies"] == 2
    assert counts["vulnerable_dependencies"] == 1
    assert counts["duplicate_blocks"] == 1
    assert counts["technical_debt"] == 1
    assert counts["complexity_issues"] == 1
    assert counts["high_complexity"] == 1

    # Freshness info comes from the seeded snapshot
    assert scan["branch"] == "main"
    assert scan["commit_sha"] == "deadbeef"

    # Summary must be present and grounded (either scan report or deterministic)
    assert data["ai_summary"]
    assert data["ai_summary_source"] in ("scan_report", "deterministic")
    assert data["message"] is None


def test_overview_invalid_repo_404(client):
    headers = get_auth_headers(client, "ovinvalid@example.com")
    resp = client.get(f"/api/v1/repositories/{uuid4()}/overview", headers=headers)
    assert resp.status_code == 404


# ── Scan identity / snapshot tracking ───────────────────────────────

def test_scan_identity_requires_auth(client):
    get_auth_headers(client, "siauth@example.com")
    repo_id, _ = seed_repo_with_scan("siauth@example.com", with_findings=False, with_insights=False)
    resp = client.get(f"/api/v1/repositories/{repo_id}/scan-identity")
    assert resp.status_code == 401, "scan-identity should require auth"


def test_scan_identity_reports_last_scan_commit(client):
    """With no PAT configured, current head is None but the last scan's
    persisted commit SHA must still be reported from the health snapshot."""
    repo_id, _ = seed_repo_with_scan("sihash@example.com", with_findings=True, with_insights=True)
    headers = get_auth_headers(client, "sihash@example.com")
    resp = client.get(f"/api/v1/repositories/{repo_id}/scan-identity", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    # Snapshot seeded with commit_sha="deadbeef"
    assert data["last_scan"]["commit_sha"] == "deadbeef"
    assert data["last_scan"]["analysis_id"]
    # No GitHub PAT in test env → current head unavailable, so not "already_analyzed"
    assert data["current_head_commit"] is None
    assert data["already_analyzed"] is False
    assert data["branch"] == "main"


def test_scan_identity_no_scan(client):
    get_auth_headers(client, "sinone@example.com")
    db = SessionLocal()
    user = db.query(User).filter_by(email="sinone@example.com").first()
    repo = Repository(user_id=user.id, name="owner/si-repo", default_branch="main")
    db.add(repo)
    db.commit()
    repo_id = str(repo.id)
    db.close()
    headers = get_auth_headers(client, "sinone@example.com")
    resp = client.get(f"/api/v1/repositories/{repo_id}/scan-identity", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["last_scan"] is None
    assert data["already_analyzed"] is False


def test_dashboard_includes_latest_scan_summary(client):
    """The simplified dashboard contract: latest scan snapshot with real
    attention counts and recommendations derived from persisted rows."""
    repo_id, analysis_id = seed_repo_with_scan("dashsummary@example.com", with_findings=True, with_insights=True)
    headers = get_auth_headers(client, "dashsummary@example.com")
    resp = client.get("/api/v1/users/me/dashboard", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    summary = data.get("latest_scan_summary")
    assert summary is not None
    assert summary["analysis_id"] == analysis_id
    assert summary["repository"] == "owner/insights-repo"
    assert summary["health_score"] == 72
    assert summary["commit_sha"] == "deadbeef"
    attention = summary["attention"]
    assert attention["critical_security"] == 1
    assert attention["high_security"] == 1
    assert attention["code_quality"] == 1
    assert attention["dependencies"] == 1  # 1 known_vulnerable seeded
    # Recommendations must mention the critical security finding first
    assert summary["recommendations"]
    assert "critical security" in summary["recommendations"][0].lower()


# ── 1. Health trend ──────────────────────────────────────────────────

def test_health_trend_single_snapshot_requires_multiple(client):
    repo_id, _ = seed_repo_with_scan("trend1@example.com", with_findings=True, with_insights=True)
    headers = get_auth_headers(client, "trend1@example.com")
    resp = client.get(f"/api/v1/repositories/{repo_id}/health-trend", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["snapshot_count"] == 1
    assert data["sufficient_data"] is False
    assert data["message"] == "Trend analysis requires multiple scans."
    assert data["points"][0]["health_score"] == 72


def test_health_trend_multiple_snapshots_shows_deltas(client):
    repo_id, _ = seed_repo_with_scan("trend2@example.com", with_findings=True, with_insights=True)
    import uuid as _uuid
    from datetime import datetime, timedelta
    db = SessionLocal()
    repo = db.query(Repository).filter_by(id=_uuid.UUID(repo_id)).first()
    # Older, worse snapshot (explicit timestamp so ordering is deterministic)
    analysis2 = Analysis(repository_id=repo.id, status="completed", progress=100, risk_score=50)
    db.add(analysis2)
    db.commit()
    db.add(RepositoryHealthSnapshot(
        repository_id=repo.id, analysis_id=analysis2.id, branch="main",
        health_score=40, security_score=30, code_quality_score=60,
        code_smell_count=8, critical_count=2, high_count=3, medium_count=3,
        low_count=0, total_issue_count=8,
        created_at=datetime.utcnow() - timedelta(days=7),
    ))
    db.commit()
    db.close()

    headers = get_auth_headers(client, "trend2@example.com")
    resp = client.get(f"/api/v1/repositories/{repo_id}/health-trend", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["snapshot_count"] == 2
    assert data["sufficient_data"] is True
    assert data["message"] is None
    assert data["trend_status"] in ("improved", "declined", "mixed", "no_change")
    assert data["deltas"]["health_score"]["from"] == 40
    assert data["deltas"]["health_score"]["to"] == 72


def test_health_trend_range_filters(client):
    repo_id, _ = seed_repo_with_scan("trend3@example.com", with_findings=False, with_insights=True)
    headers = get_auth_headers(client, "trend3@example.com")
    for rng in ("7", "30", "all"):
        resp = client.get(f"/api/v1/repositories/{repo_id}/health-trend?range={rng}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["range"] == rng


# ── 2. Dependencies ──────────────────────────────────────────────────

def test_dependencies_returns_findings_and_filters(client):
    repo_id, _ = seed_repo_with_scan("deps1@example.com", with_findings=False, with_insights=True)
    headers = get_auth_headers(client, "deps1@example.com")

    resp = client.get(f"/api/v1/repositories/{repo_id}/dependencies", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["total"] == 2
    assert data["summary"]["known_vulnerable"] == 1
    vuln = data["findings"][0]
    assert vuln["package_name"] == "requests"
    assert vuln["status"] == "known_vulnerable"
    assert vuln["advisory_id"] == "CVE-2018-18074"  # real advisory, never fabricated
    assert vuln["advisory_url"].startswith("https://")

    # Filter by ecosystem
    resp2 = client.get(f"/api/v1/repositories/{repo_id}/dependencies?ecosystem=pip", headers=headers)
    assert resp2.status_code == 200
    assert all(f["ecosystem"] == "pip" for f in resp2.json()["findings"])

    # Filter by severity
    resp3 = client.get(f"/api/v1/repositories/{repo_id}/dependencies?severity=high", headers=headers)
    assert resp3.status_code == 200
    assert all((f["severity"] or "").lower() == "high" for f in resp3.json()["findings"])


def test_dependencies_no_scan_returns_empty_with_message(client):
    # Repo without any completed scan: seed then delete the analysis rows
    import uuid as _uuid
    repo_id, analysis_id = seed_repo_with_scan("deps2@example.com", with_findings=False, with_insights=False)
    db = SessionLocal()
    from app.models.models import Analysis as _Analysis
    an = db.query(_Analysis).filter_by(id=_uuid.UUID(analysis_id)).first()
    if an:
        db.delete(an)
        db.commit()
    db.close()

    headers = get_auth_headers(client, "deps2@example.com")
    resp = client.get(f"/api/v1/repositories/{repo_id}/dependencies", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["analysis_id"] is None
    assert data["findings"] == []
    assert "No completed scan" in data["message"]


# ── 3. Duplicates ────────────────────────────────────────────────────

def test_duplicates_returns_findings_and_threshold_filter(client):
    repo_id, _ = seed_repo_with_scan("dup1@example.com", with_findings=False, with_insights=True)
    headers = get_auth_headers(client, "dup1@example.com")

    resp = client.get(f"/api/v1/repositories/{repo_id}/duplicates", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["findings"]) == 1
    f = data["findings"][0]
    assert f["file_a"] != f["file_b"]  # never same file
    assert f["similarity"] == 95
    assert f["duplicated_lines"] == 8

    # Threshold filtering
    resp2 = client.get(f"/api/v1/repositories/{repo_id}/duplicates?min_similarity=98", headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["findings"] == []


def test_duplicate_detector_deterministic():
    """Unit test: detect real duplicated blocks, skip trivial ones."""
    from app.services.duplicate_detector import detect_duplicates

    shared = [
        "    total = 0",
        "    for item in items:",
        "        total += item.price",
        "    if total > 100:",
        "        total -= 10",
        "        total -= 5",
        "    return total",
    ]
    lines_a = ["def compute_total(items):"] + shared + ["", "def unrelated():", "    pass"]
    lines_b = ["def compute_sum(products):"] + shared + ["", "def other():", "    pass"]
    files = [
        {"path": "a.py", "content": "\n".join(lines_a), "lines": lines_a},
        {"path": "b.py", "content": "\n".join(lines_b), "lines": lines_b},
    ]
    result = detect_duplicates(files, min_lines=5, min_similarity=70)
    assert result["files_analyzed"] == 2
    # The shared 7-line block is detected across both files
    assert len(result["findings"]) >= 1
    f = result["findings"][0]
    assert f["file_a"] != f["file_b"]
    assert f["similarity"] >= 70
    assert f["duplicated_lines"] >= 5


def test_duplicate_detector_no_duplicates(client):
    from app.services.duplicate_detector import detect_duplicates
    files = [
        {"path": "x.py", "content": "import os\nprint(os)\n", "lines": ["import os", "print(os)"]},
        {"path": "y.py", "content": "import sys\nprint(sys)\n", "lines": ["import sys", "print(sys)"]},
    ]
    result = detect_duplicates(files, min_lines=5)
    assert result["findings"] == []


# ── 4. Technical debt ────────────────────────────────────────────────

def test_technical_debt_returns_items_with_evidence(client):
    repo_id, _ = seed_repo_with_scan("debt1@example.com", with_findings=True, with_insights=True)
    headers = get_auth_headers(client, "debt1@example.com")

    resp = client.get(f"/api/v1/repositories/{repo_id}/technical-debt", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["item_count"] >= 1
    item = data["items"][0]
    assert item["evidence"]  # every item has measured evidence
    assert "estimate" in data["summary"]["effort_estimate_note"].lower()
    assert item["estimated_effort_hours"] is not None

    # Category filter
    resp2 = client.get(f"/api/v1/repositories/{repo_id}/technical-debt?category=security", headers=headers)
    assert resp2.status_code == 200
    assert all(i["category"] == "security" for i in resp2.json()["items"])


def test_technical_debt_analyzer_transparent_estimates():
    """Unit test: effort weights applied transparently from real findings."""
    from app.services.technical_debt_analyzer import build_technical_debt_report

    report = build_technical_debt_report(
        security_findings=[{"severity": "Critical", "issue": "SQLi", "file": "db.py", "line": 3}],
        code_smells=[],
        duplicates={"findings": [{"file_a": "a.py", "start_line_a": 1, "end_line_a": 10,
                                  "file_b": "b.py", "start_line_b": 5, "end_line_b": 14,
                                  "similarity": 90, "duplicated_lines": 10}]},
        complexity={"findings": [{"file": "c.py", "name": "f", "line_start": 1, "line_end": 40,
                                  "cyclomatic_complexity": 20, "length_lines": 40, "severity": "High"}]},
        source_files=[{"path": "d.py", "lines": ["# TODO fix this later"] * 3 + ["x = 1"]}],
        dependencies={"findings": [{"status": "known_vulnerable", "package_name": "requests",
                                    "resolved_version": "2.19.0", "advisory_id": "CVE-2018-18074",
                                    "recommended_version": "2.20.0", "severity": "High",
                                    "manifest_file": "requirements.txt"}]},
    )
    # Security Critical 1 × 4h + duplication 1 × 1.5h + complexity high 1 × 3h
    # + todos 3 × 0.5h + vulnerable dep 1 × 2h = 4 + 1.5 + 3 + 1.5 + 2 = 12
    assert report["summary"]["total_estimated_effort_hours"] == 12.0
    categories = {i["category"] for i in report["items"]}
    assert {"security", "duplication", "complexity", "unfinished_work", "dependencies"} <= categories
    assert report["summary"]["item_count"] == len(report["items"])


# ── 5. Architecture ──────────────────────────────────────────────────

def test_architecture_returns_stored_analysis(client):
    repo_id, _ = seed_repo_with_scan("arch1@example.com", with_findings=False, with_insights=True)
    headers = get_auth_headers(client, "arch1@example.com")

    resp = client.get(f"/api/v1/repositories/{repo_id}/architecture", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"]["frameworks"][0]["name"] == "FastAPI"
    assert data["result"]["summary"]["structure"]["total_files"] == 10


def test_architecture_no_scan_404(client):
    repo_id, _ = seed_repo_with_scan("arch2@example.com", with_findings=False, with_insights=False)
    headers = get_auth_headers(client, "arch2@example.com")
    resp = client.get(f"/api/v1/repositories/{repo_id}/architecture", headers=headers)
    assert resp.status_code == 404


def test_architecture_analyzer_evidence_based():
    """Unit test: only technologies with real evidence are reported."""
    from app.services.architecture_analyzer import _detect_frameworks

    # Flask declared in a real requirements.txt → detected with evidence
    frameworks = _detect_frameworks(
        tree_paths=["requirements.txt", "app/main.py"],
        manifest_pkgs={"flask": "requirements.txt", "redis": "requirements.txt"},
        file_contents={"docker-compose.yml": "services:\n  db:\n    image: postgres\n"},
    )
    names = {f["name"] for f in frameworks}
    assert "Flask" in names
    assert "PostgreSQL" in names  # from compose file content
    # Not declared → NOT reported
    assert "Django" not in names
    assert "Express" not in names
    assert "MongoDB" not in names
    for f in frameworks:
        assert f["evidence"], "every detected technology must cite evidence"


# ── 6. Complexity ────────────────────────────────────────────────────

def test_complexity_returns_findings_and_filters(client):
    repo_id, _ = seed_repo_with_scan("cx1@example.com", with_findings=False, with_insights=True)
    headers = get_auth_headers(client, "cx1@example.com")

    resp = client.get(f"/api/v1/repositories/{repo_id}/complexity", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["findings"][0]["cyclomatic_complexity"] == 18

    resp2 = client.get(f"/api/v1/repositories/{repo_id}/complexity?severity=High", headers=headers)
    assert resp2.status_code == 200
    assert all(f["severity"] == "High" for f in resp2.json()["findings"])

    resp3 = client.get(f"/api/v1/repositories/{repo_id}/complexity?language=Python", headers=headers)
    assert resp3.status_code == 200
    assert all(f["language"] == "Python" for f in resp3.json()["findings"])


def test_complexity_analyzer_python_ast():
    """Unit test: real AST-based cyclomatic complexity for Python."""
    from app.services.complexity_analyzer import analyze_files

    code = (
        "def simple():\n"
        "    return 1\n"
        "\n"
        "def branching(x):\n"
        "    if x > 0:\n"
        "        for i in range(x):\n"
        "            if i % 2 == 0 and x > 5:\n"
        "                return i\n"
        "    elif x < 0:\n"
        "        while x < -1:\n"
        "            x += 1\n"
        "    return x\n"
    )
    files = [{"path": "mod.py", "content": code}]
    result = analyze_files(files)
    by_name = {f["name"]: f for f in result["findings"]}
    # simple(): CC 1 → below threshold, not reported
    assert "simple" not in by_name
    # branching(): 1 + if(1) + for(1) + if(1) + bool-and(1) + elif(1) + while(1) = 7 → not reported (threshold 8)
    # Use a clearly complex function instead:
    code2 = code + (
        "def very_complex(x):\n"
        "    if x: return 1\n"
        "    if x > 1: return 2\n"
        "    if x > 2: return 3\n"
        "    if x > 3: return 4\n"
        "    if x > 4: return 5\n"
        "    if x > 5: return 6\n"
        "    if x > 6: return 7\n"
        "    for i in range(3):\n"
        "        for j in range(3):\n"
        "            if i == j: return 8\n"
        "    return 0\n"
    )
    result2 = analyze_files([{"path": "mod.py", "content": code2}])
    by_name2 = {f["name"]: f for f in result2["findings"]}
    assert "very_complex" in by_name2
    assert by_name2["very_complex"]["cyclomatic_complexity"] >= 10
    assert by_name2["very_complex"]["severity"] in ("Medium", "High")
    # Values are measured, not fabricated — verified exact AST line number
    assert by_name2["very_complex"]["line_start"] == 13


def test_complexity_analyzer_js():
    from app.services.complexity_analyzer import analyze_files
    code = (
        "function handle(x) {\n"
        "  if (x === 1) return 'a';\n"
        "  if (x === 2) return 'b';\n"
        "  if (x === 3) return 'c';\n"
        "  if (x === 4) return 'd';\n"
        "  if (x === 5) return 'e';\n"
        "  if (x === 6) return 'f';\n"
        "  if (x === 7) return 'g';\n"
        "  if (x === 8) return 'h';\n"
        "  if (x === 9) return 'i';\n"
        "  return 'j';\n"
        "}\n"
    )
    result = analyze_files([{"path": "app.js", "content": code}])
    assert len(result["findings"]) == 1
    f = result["findings"][0]
    assert f["name"] == "handle"
    assert f["cyclomatic_complexity"] == 10  # 1 base + 9 ifs
    assert f["language"] == "JavaScript"


def test_complexity_analyzer_unsupported_language_skipped():
    from app.services.complexity_analyzer import analyze_files
    result = analyze_files([
        {"path": "Main.java", "content": "public class Main { void x() {} }"},
        {"path": "main.go", "content": "package main\nfunc main() {}"},
    ])
    assert result["findings"] == []
    assert result["files_analyzed"] == 0  # unsupported languages are skipped, not fabricated


# ── 7. PR review ─────────────────────────────────────────────────────

@patch("app.routers.insights.GitHubService")
def test_pr_review_endpoint(mock_gh_class, client):
    headers = get_auth_headers(client, "prrev1@example.com")
    repo_id, _ = seed_repo_with_scan("prrev1@example.com", with_findings=False, with_insights=False)

    mock_gh = mock_gh_class.return_value
    mock_gh.get_pr_details.return_value = {
        "number": 7, "title": "Add login", "author": "alice",
        "additions": 30, "deletions": 2, "state": "open",
        "head_sha": "abc123", "base_sha": "def456",
    }
    mock_gh.get_pr_files.return_value = [
        {"filename": "auth.py", "additions": 20, "deletions": 0, "changes": 20,
         "status": "modified",
         "patch": "@@ -1,2 +1,5 @@\n import os\n+password = \"hunter2secret\"\n+def login(user):\n+    os.system(\"ls \" + user)", "raw_url": "x"},
        {"filename": "README.md", "additions": 10, "deletions": 2, "changes": 12,
         "status": "modified", "patch": "+docs", "raw_url": "y"},
    ]
    # Mock the PR body/branches fetch
    mock_pr_obj = MagicMock()
    mock_pr_obj.body = "Adds login feature"
    mock_pr_obj.base.ref = "main"
    mock_pr_obj.head.ref = "feature/login"
    mock_repo = MagicMock()
    mock_repo.get_pull.return_value = mock_pr_obj
    mock_client = MagicMock()
    mock_client.get_repo.return_value = mock_repo
    mock_gh.get_client_for_repo.return_value = mock_client

    resp = client.post(f"/api/v1/repositories/{repo_id}/pull-requests/7/review", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["pr_number"] == 7
    assert data["base_branch"] == "main"
    assert data["head_branch"] == "feature/login"
    assert data["description"] == "Adds login feature"
    # Deterministic findings from the real patch content
    assert len(data["findings"]) >= 1
    assert all(f["source"] == "deterministic" for f in data["findings"])
    assert any(f["file"] == "auth.py" for f in data["findings"])
    # README.md has no scan-able language → not scanned
    assert data["files_changed"] == 2
    assert data["summary"]  # AI fallback or grounded summary always present

    # GET the stored review
    resp2 = client.get(f"/api/v1/repositories/{repo_id}/pull-requests/7/review", headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["risk_score"] == data["risk_score"]


@patch("app.routers.insights.GitHubService")
def test_pr_review_bad_pr_400(mock_gh_class, client):
    headers = get_auth_headers(client, "prrev2@example.com")
    repo_id, _ = seed_repo_with_scan("prrev2@example.com", with_findings=False, with_insights=False)
    mock_gh_class.return_value.get_pr_details.side_effect = Exception("PR not found")
    resp = client.post(f"/api/v1/repositories/{repo_id}/pull-requests/999/review", headers=headers)
    assert resp.status_code == 400


@patch("app.routers.insights.GitHubService")
def test_pr_list_includes_review_status(mock_gh_class, client):
    headers = get_auth_headers(client, "prlist@example.com")
    repo_id, _ = seed_repo_with_scan("prlist@example.com", with_findings=False, with_insights=False)
    mock_gh_class.return_value.get_open_pull_requests.return_value = [
        {"number": 1, "title": "PR one", "author": "a", "state": "open",
         "additions": 5, "deletions": 1, "head_sha": "h1", "base_sha": "b1"},
    ]
    resp = client.get(f"/api/v1/repositories/{repo_id}/pull-requests", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["pull_requests"][0]["number"] == 1
    assert data["pull_requests"][0]["review"] is None  # not reviewed yet


# ── 8. Commit analysis ───────────────────────────────────────────────

@patch("app.routers.insights.GitHubService")
def test_commit_analyze_endpoint(mock_gh_class, client):
    headers = get_auth_headers(client, "commit1@example.com")
    repo_id, _ = seed_repo_with_scan("commit1@example.com", with_findings=False, with_insights=False)

    from datetime import datetime
    mock_commit = MagicMock()
    mock_commit.sha = "abc123def4567890" * 2
    parent = MagicMock(); parent.sha = "parent000" * 4
    mock_commit.parents = [parent]
    mock_commit.author = None
    mock_commit.commit.author.name = "Bob"
    mock_commit.commit.author.date = datetime(2026, 9, 1, 12, 0, 0)
    mock_commit.commit.message = "Fix bug"
    mock_commit.stats.additions = 10
    mock_commit.stats.deletions = 2

    mock_file = MagicMock()
    mock_file.filename = "payment.py"
    mock_file.status = "modified"
    mock_file.additions = 10
    mock_file.deletions = 2
    mock_file.changes = 12
    mock_file.patch = "@@ -1,2 +1,5 @@\n import os\n+API_KEY = \"sk-live-abcdefgh123456\"\n+def pay():\n+    pass"
    mock_file.previous_filename = None
    mock_commit.files = [mock_file]
    mock_commit.stats.additions = 10

    mock_repo = MagicMock()
    mock_repo.get_commit.return_value = mock_commit
    mock_client = MagicMock()
    mock_client.get_repo.return_value = mock_repo
    mock_gh_class.return_value.get_client_for_repo.return_value = mock_client

    resp = client.post(f"/api/v1/repositories/{repo_id}/commits/abc123def456/analyze", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["files_changed"] == 1
    assert data["additions"] == 10
    assert data["deletions"] == 2
    assert data["parent_sha"] == "parent000" * 4
    # Findings come from the deterministic scanner on the real added lines
    assert len(data["security_findings"]) >= 1
    assert all(f["source"] == "static_analysis" for f in data["security_findings"])
    assert data["ai_summary"]  # grounded fallback present

    # Stored analysis retrievable via GET
    resp2 = client.get(f"/api/v1/repositories/{repo_id}/commits/abc123def4567890abc123def4567890/analysis", headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["commit_sha"].startswith("abc123")


@patch("app.routers.insights.GitHubService")
def test_commit_list_endpoint(mock_gh_class, client):
    headers = get_auth_headers(client, "commit2@example.com")
    repo_id, _ = seed_repo_with_scan("commit2@example.com", with_findings=False, with_insights=False)

    from datetime import datetime
    mock_commit = MagicMock()
    mock_commit.sha = "aaaabbbbccccdddd" * 2
    mock_commit.author = None
    mock_commit.commit.author.name = "Ann"
    mock_commit.commit.author.date = datetime(2026, 9, 10)
    mock_commit.commit.message = "Initial commit"
    mock_commit.stats = None
    mock_commit.files = []

    mock_repo = MagicMock()
    mock_repo.get_commits.return_value = iter([mock_commit])
    mock_client = MagicMock()
    mock_client.get_repo.return_value = mock_repo
    mock_gh_class.return_value.get_client_for_repo.return_value = mock_client

    resp = client.get(f"/api/v1/repositories/{repo_id}/commits", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["commits"]) == 1
    c = data["commits"][0]
    assert c["sha"] == "aaaabbbbccccdddd" * 2
    assert c["author"] == "Ann"
    assert c["analyzed"] is False


def test_commit_analyze_invalid_sha(client):
    headers = get_auth_headers(client, "commit3@example.com")
    repo_id, _ = seed_repo_with_scan("commit3@example.com", with_findings=False, with_insights=False)
    resp = client.post(f"/api/v1/repositories/{repo_id}/commits/not-a-sha/analyze", headers=headers)
    assert resp.status_code == 400


# ── Dependency scanner unit tests ────────────────────────────────────

def test_dependency_scanner_classifies_real_advisories():
    from app.services.dependency_scanner import classify_dependency, parse_requirements_txt, parse_package_json

    # Real vulnerable version → known_vulnerable with the REAL CVE id
    r = classify_dependency("pip", "requests", "2.6.0", "==2.6.0")
    assert r["status"] == "known_vulnerable"
    assert r["advisory_id"] == "CVE-2018-18074"
    assert r["severity"] == "High"

    # Safe modern version → not vulnerable
    r2 = classify_dependency("pip", "requests", "2.32.0", None)
    assert r2["status"] != "known_vulnerable"

    # Package without advisory data → unknown (never guessed)
    r3 = classify_dependency("pip", "some-unknown-package", "1.0.0", "==1.0.0")
    assert r3["status"] == "unknown"
    assert r3["advisory_id"] is None

    # Unresolvable spec → unknown
    r4 = classify_dependency("npm", "lodash", None, "*")
    assert r4["status"] == "unknown"

    # Parsers
    reqs = parse_requirements_txt("requests==2.6.0\nflask>=1.0\n# comment\n-r other.txt\n")
    assert {"name": "requests", "spec": "==2.6.0", "resolved": "2.6.0"} in [
        {"name": d["name"], "spec": d["spec"], "resolved": d["resolved"]} for d in reqs
    ]
    pkg = parse_package_json('{"dependencies": {"lodash": "^4.17.15"}}')
    assert pkg[0]["name"] == "lodash"
    assert pkg[0]["resolved"] == "4.17.15"


def test_dependency_scanner_never_fabricates_advisories():
    """The scanner must never claim a CVE for an unknown package."""
    from app.services.dependency_scanner import scan_dependencies

    class FakeFetcher:
        def list_manifest_paths(self):
            return [{"path": "requirements.txt", "ecosystem": "pip", "size": 20}]
        def fetch_content(self, path, branch=None):
            return "totally-fake-package==1.2.3\n"
        def get_tree_items(self, branch=None):
            return []

    result = scan_dependencies(FakeFetcher())
    assert result["summary"]["total"] == 1
    assert result["summary"]["known_vulnerable"] == 0
    for f in result["findings"]:
        assert f["status"] == "unknown"
        assert f["advisory_id"] is None


# ── Report integration ───────────────────────────────────────────────

def test_report_includes_insight_sections():
    from app.services.report_generator import generate_markdown_report
    data = {
        "repo_name": "x/y", "timestamp": "now", "risk_score": 10, "findings": [],
        "dependencies": {
            "findings": [{"package_name": "requests", "ecosystem": "pip", "resolved_version": "2.6.0",
                          "status": "known_vulnerable", "severity": "High",
                          "advisory_id": "CVE-2018-18074", "recommended_version": "2.20.0"}],
            "summary": {"total": 1, "known_vulnerable": 1, "outdated": 0, "unknown": 0},
        },
        "duplicates": {"findings": [{"file_a": "a.py", "start_line_a": 1, "end_line_a": 8,
                                     "file_b": "b.py", "start_line_b": 2, "end_line_b": 9,
                                     "similarity": 92, "duplicated_lines": 8}]},
        "technical_debt": {
            "items": [{"category": "security", "severity": "High", "title": "t",
                       "evidence": "e", "file": "f.py", "line_start": 1,
                       "estimated_effort_hours": 3.0}],
            "summary": {"overall_debt_score": 95, "total_estimated_effort_hours": 3.0},
        },
        "architecture": {
            "frameworks": [{"name": "FastAPI", "category": "Backend framework"}],
            "layers": [{"layer": "tests", "evidence_directories": ["tests"]}],
            "components": [{"name": "app", "file_count": 5}],
            "concerns": [{"concern": "big dir"}],
        },
        "complexity": {
            "findings": [{"file": "a.py", "name": "f", "line_start": 3,
                          "cyclomatic_complexity": 16, "length_lines": 40, "severity": "High"}],
            "summary": {"total_functions_measured": 10, "reported": 1, "average_complexity": 4.2},
        },
    }
    md = generate_markdown_report(data)
    assert "## Dependency Vulnerabilities" in md
    assert "CVE-2018-18074" in md
    assert "## Duplicate Code" in md
    assert "## Technical Debt" in md
    assert "heuristic estimate" in md
    assert "## Architecture Analysis" in md
    assert "FastAPI" in md
    assert "## Code Complexity" in md


def test_report_without_insights_unchanged():
    """Existing reports must not break when no insight data exists."""
    from app.services.report_generator import generate_markdown_report
    md = generate_markdown_report({"repo_name": "x/y", "risk_score": 5, "findings": []})
    assert "RepoLens AI Report" in md
    assert "## Dependency Vulnerabilities" not in md
