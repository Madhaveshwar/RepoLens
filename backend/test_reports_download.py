"""E2E test: Create mock report records and files, then test the download API."""
import os
import sys
import uuid

# Ensure backend/ is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database.database import SessionLocal
from app.models.models import Report, User
from app.services.report_generator import (
    generate_markdown_report,
    generate_json_report,
    generate_csv_report,
    generate_pdf_report,
)

# ── Config ──────────────────────────────────────────────
STORAGE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "storage"
)
os.makedirs(STORAGE_DIR, exist_ok=True)

# User email we created earlier
USER_EMAIL = "e2e@test.com"

# Mock report data (same structure as real scans)
REPORT_DATA = {
    "repo_name": "E2E-Test-Repo",
    "risk_score": 25,
    "timestamp": "2026-06-20 12:00 UTC",
    "findings": [
        {
            "file": "src/app.py",
            "line": 42,
            "severity": "Critical",
            "category": "Security",
            "issue": "SQL Injection vulnerability",
            "why_it_matters": "User input directly concatenated into SQL query",
            "risk_level": "Critical",
            "suggestion": "Use parameterized queries with a database driver",
            "before_code": 'cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")',
            "after_code": 'cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))',
        }
    ],
    "test_suggestions": "Consider adding unit tests for all database access functions",
    "repo_analysis": {
        "health_score": 75,
        "source_files_count": 10,
        "test_files_count": 3,
        "docstring_coverage": 60,
        "analysis_report": "Good overall code quality",
    },
    "files_analyzed_log": [
        {"file": "src/app.py", "type": "Python", "status": "Analyzed", "findings": 1}
    ],
    "scores": {
        "code_quality": 85,
        "security": 70,
        "maintainability": 80,
        "performance": 90,
        "technical_debt": 15,
    },
}

# This analysis_id will be used in filenames
ANALYSIS_ID = str(uuid.uuid4())
print(f"Using analysis_id={ANALYSIS_ID}")
print(f"Storage dir: {STORAGE_DIR}")

# ── Generate files ──────────────────────────────────────
types_and_exts = [
    ("PDF", "pdf"),
    ("Markdown", "md"),
    ("JSON", "json"),
    ("CSV", "csv"),
]

created = []
for rtype, ext in types_and_exts:
    filepath = os.path.join(STORAGE_DIR, f"report_{ANALYSIS_ID}.{ext}")
    if rtype == "PDF":
        generate_pdf_report(REPORT_DATA, filepath)
    elif rtype == "Markdown":
        content = generate_markdown_report(REPORT_DATA)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
    elif rtype == "JSON":
        content = generate_json_report(REPORT_DATA)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
    elif rtype == "CSV":
        content = generate_csv_report(REPORT_DATA)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

    size = os.path.getsize(filepath)
    print(f"  OK {rtype:8s}  -> {filepath}  ({size} bytes)")
    created.append((rtype, filepath, size))

# ── Create DB records ───────────────────────────────────
db = SessionLocal()
user = db.query(User).filter(User.email == USER_EMAIL).first()
if not user:
    print(f"✗ User {USER_EMAIL} not found!")
    db.close()
    sys.exit(1)
print(f"\nUser found: {user.id} ({user.email})")

for rtype, filepath, size in created:
    report = Report(
        id=uuid.uuid4(),
        user_id=user.id,
        analysis_id=uuid.UUID(ANALYSIS_ID),
        type=rtype,
        filepath=filepath,
    )
    db.add(report)
    print(f"  OK DB record created for {rtype}")

db.commit()
db.close()

total_size = sum(s for _, _, s in created)
print(f"\n{'='*60}")
print(f"ALL 4 REPORTS CREATED SUCCESSFULLY")
print(f"  Analysis ID: {ANALYSIS_ID}")
print(f"  Total size:  {total_size} bytes")
print(f"{'='*60}")
