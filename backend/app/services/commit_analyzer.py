"""
Commit / Change Analysis — analyzes a REAL commit diff vs its parent.

Retrieves the actual commit from GitHub, computes the diff against the
parent commit, then applies the same deterministic scanners used by the
scan pipeline (static security + code smells + complexity) to the changed
files. An optional grounded AI summary explains the measured findings.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.github_service import GitHubService
from app.services.static_security_scanner import StaticSecurityAnalyzer
from app.services.static_code_smell_detector import StaticCodeSmellDetector
from app.services.complexity_analyzer import analyze_python, analyze_js
from app.utils.logger import get_logger

logger = get_logger("commit_analyzer")

SOURCE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".cs", ".go", ".rb", ".php", ".rs", ".kt"}


def _ext_to_lang(ext: str) -> str:
    return {
        ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript",
        ".tsx": "TypeScript", ".java": "Java", ".go": "Go", ".rb": "Ruby", ".rs": "Rust",
    }.get(ext, "Other")


def list_recent_commits(github_service: GitHubService, repo_name: str, branch: str, limit: int = 30) -> list[dict]:
    """Fetch the most recent real commits on a branch."""
    client = github_service.get_client_for_repo(repo_name)
    repo = client.get_repo(repo_name)
    commits = []
    for c in repo.get_commits(sha=branch):
        stats = getattr(c, "stats", None)
        commits.append({
            "sha": c.sha,
            "short_sha": c.sha[:8],
            "author": c.author.login if getattr(c, "author", None) else (c.commit.author.name if c.commit and c.commit.author else "unknown"),
            "date": c.commit.author.date.isoformat() if c.commit and c.commit.author else None,
            "message": (c.commit.message or "").split("\n")[0][:200],
            "additions": stats.additions if stats else None,
            "deletions": stats.deletions if stats else None,
            "files_changed": c.commit.tree and None,  # placeholder replaced below when needed
        })
        if len(commits) >= limit:
            break
    # files count needs the full commit; use len(c.files) lazily-safe
    for c_dict, c_obj in zip(commits, repo.get_commits(sha=branch)):
        try:
            c_dict["files_changed"] = c_obj.files and len(list(c_obj.files)) or None
        except Exception:
            c_dict["files_changed"] = None
        if len(commits) and commits.index(c_dict) >= limit - 1:
            break
    return commits


def get_commit_details(github_service: GitHubService, repo_name: str, sha: str) -> dict:
    """Fetch one real commit with parent + file patches."""
    client = github_service.get_client_for_repo(repo_name)
    repo = client.get_repo(repo_name)
    commit = repo.get_commit(sha)

    parents = [p.sha for p in commit.parents]
    author = (
        commit.author.login if getattr(commit, "author", None)
        else (commit.commit.author.name if commit.commit and commit.commit.author else "unknown")
    )
    committed_at = commit.commit.author.date.isoformat() if commit.commit and commit.commit.author else None

    files = []
    for f in commit.files:
        files.append({
            "filename": f.filename,
            "status": f.status,           # added / modified / removed / renamed
            "additions": f.additions,
            "deletions": f.deletions,
            "changes": f.changes,
            "patch": f.patch or "",
            "previous_filename": getattr(f, "previous_filename", None),
        })

    return {
        "sha": commit.sha,
        "parent_sha": parents[0] if parents else None,
        "author": author,
        "message": commit.commit.message or "",
        "committed_at": committed_at,
        "additions": commit.stats.additions if commit.stats else sum(f["additions"] for f in files),
        "deletions": commit.stats.deletions if commit.stats else sum(f["deletions"] for f in files),
        "files": files,
    }


def _extract_added_lines(patch: str) -> tuple[list[str], dict[int, str]]:
    """Return (all added lines, {new-file line number: line text})."""
    added: list[str] = []
    numbered: dict[int, str] = {}
    current = 0
    hunk_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
    for line in (patch or "").splitlines():
        m = hunk_re.match(line)
        if m:
            current = int(m.group(1))
        elif line.startswith("+"):
            added.append(line[1:])
            if current:
                numbered[current] = line[1:]
            current += 1
        elif line.startswith("-"):
            pass
        else:
            if current:
                current += 1
    return added, numbered


def analyze_commit(
    github_service: GitHubService,
    repo_name: str,
    sha: str,
) -> dict:
    """Analyze a real commit's changes deterministically."""
    details = get_commit_details(github_service, repo_name, sha)

    security_findings: list[dict] = []
    smell_findings: list[dict] = []
    complexity_findings: list[dict] = []
    scanned_files = 0

    for f in details["files"]:
        filename = f["filename"]
        ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
        if ext not in SOURCE_EXT or not f["patch"]:
            continue
        if f["status"] == "removed":
            continue

        added_lines, _ = _extract_added_lines(f["patch"])
        added_text = "\n".join(added_lines)
        if not added_text.strip():
            continue
        scanned_files += 1
        language = _ext_to_lang(ext)

        # Deterministic scanners on the ADDED code only — the part this
        # commit actually introduces.
        for sf in StaticSecurityAnalyzer.scan(code=added_text, filename=filename, language=language):
            security_findings.append({
                "file": filename, "line": sf.get("line"), "severity": sf.get("severity"),
                "issue": sf.get("issue"), "suggestion": sf.get("suggestion"),
                "source": "static_analysis", "code": (added_lines[sf.get("line", 1) - 1] if sf.get("line") and sf.get("line", 1) <= len(added_lines) else ""),
            })
        for sm in StaticCodeSmellDetector.scan(code=added_text, filename=filename, language=language):
            smell_findings.append({
                "file": filename, "line": sm.get("line"), "severity": sm.get("severity"),
                "issue": sm.get("issue"), "suggestion": sm.get("suggestion"),
                "source": "static_analysis",
            })

        # Complexity of the added code (measurable subset)
        if ext == ".py":
            for cx in analyze_python(added_text):
                complexity_findings.append({
                    "file": filename, "name": cx["name"], "line_start": cx["line_start"],
                    "cyclomatic_complexity": cx["cyclomatic_complexity"],
                    "length_lines": cx["length_lines"],
                    "note": "Measured on the lines added by this commit only (partial view of the full file).",
                })
        elif ext in (".js", ".jsx", ".ts", ".tsx"):
            for cx in analyze_js(added_text, language):
                complexity_findings.append({
                    "file": filename, "name": cx["name"], "line_start": cx["line_start"],
                    "cyclomatic_complexity": cx["cyclomatic_complexity"],
                    "length_lines": cx["length_lines"],
                    "note": "Measured on the lines added by this commit only (partial view of the full file).",
                })

    total_adds = details["additions"] or 0
    total_dels = details["deletions"] or 0

    # Security impact text — derived strictly from measured findings
    crit = sum(1 for s in security_findings if s["severity"] == "Critical")
    high = sum(1 for s in security_findings if s["severity"] == "High")
    med = sum(1 for s in security_findings if s["severity"] == "Medium")
    if crit:
        security_impact = f"{crit} critical security pattern(s) detected in the added code."
    elif high:
        security_impact = f"{high} high-severity security pattern(s) detected in the added code."
    elif med:
        security_impact = f"{med} medium-severity security pattern(s) detected in the added code."
    elif security_findings:
        security_impact = f"{len(security_findings)} low-severity security pattern(s) detected in the added code."
    else:
        security_impact = "No security patterns detected in the added code by the deterministic scanners."

    if smell_findings:
        quality_impact = (
            f"{len(smell_findings)} code smell(s) detected in the added code "
            f"({sum(1 for s in smell_findings if s['severity'] in ('High', 'Critical'))} high/critical)."
        )
    else:
        quality_impact = "No code smells detected in the added code by the deterministic scanners."

    return {
        "sha": details["sha"],
        "parent_sha": details["parent_sha"],
        "author": details["author"],
        "message": details["message"],
        "committed_at": details["committed_at"],
        "files_changed": len(details["files"]),
        "additions": total_adds,
        "deletions": total_dels,
        "files": details["files"],
        "security_findings": security_findings,
        "code_smells": smell_findings,
        "complexity_findings": complexity_findings,
        "security_impact": security_impact,
        "quality_impact": quality_impact,
        "scanned_files_count": scanned_files,
    }
