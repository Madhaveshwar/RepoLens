"""
Technical Debt Analysis — strictly evidence-based.

Every item is derived from *measured* facts: scan findings already in the
database (security issues, code smells), deterministic analyzers run in
this request (duplication, complexity), and raw file evidence (TODO/FIXME
markers, long functions, large files, outdated dependencies).

Remediation effort uses ONE transparent heuristic (documented in the
response) and is always labelled as an estimate. AI is not used here.
"""

from __future__ import annotations

import re
from typing import Any

from app.utils.logger import get_logger

logger = get_logger("technical_debt_analyzer")

# ── Effort heuristic (transparent, linear) ────────────────────────────
# Hours are derived from the evidence count driving each item:
#   security critical  : 4 h each      |  code smell high : 2 h each
#   security high      : 3 h each      |  code smell med  : 1 h each
#   duplicated block   : 1.5 h each    |  complexity high : 3 h each
#   complexity medium  : 1.5 h each    |  long function   : 1 h each
#   TODO/FIXME marker  : 0.5 h each    |  large file      : 2 h each
#   outdated dep       : 1 h each      |  vulnerable dep  : 2 h each
EFFORT_WEIGHTS = {
    "security_critical": 4.0,
    "security_high": 3.0,
    "security_other": 1.0,
    "code_smell": 1.0,
    "code_smell_major": 2.0,
    "duplication": 1.5,
    "complexity_high": 3.0,
    "complexity_medium": 1.5,
    "todos": 0.5,
    "long_functions": 1.0,
    "large_files": 2.0,
    "dependency_vulnerable": 2.0,
    "dependency_outdated": 1.0,
}

SEVERITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}

TODO_PATTERN = re.compile(
    r"\b(TODO|FIXME|HACK|XXX|WORKAROUND)\b[:\s]?(.{0,120})",
)


def _severity_from_counts(count: int, high_at: int = 3, med_at: int = 1) -> str:
    if count >= high_at * 3:
        return "Critical"
    if count >= high_at:
        return "High"
    if count >= med_at:
        return "Medium"
    return "Low"


def build_technical_debt_report(
    *,
    security_findings: list[dict],
    code_smells: list[dict],
    duplicates: dict,
    complexity: dict,
    source_files: list[dict],
    dependencies: dict,
) -> dict:
    """Build a technical debt report from real, measured inputs.

    All arguments come from actual scan results / deterministic analyzers.
    """
    items: list[dict] = []
    total_hours = 0.0

    # ── 1. Security issues ─────────────────────────────────────────
    sec_by_sev: dict[str, list[dict]] = {}
    for f in security_findings:
        sec_by_sev.setdefault((f.get("severity") or "Info"), []).append(f)

    for sev, group in sorted(sec_by_sev.items(), key=lambda kv: SEVERITY_ORDER.get(kv[0], 9)):
        weight_key = (
            "security_critical" if sev == "Critical"
            else "security_high" if sev == "High"
            else "security_other"
        )
        hours = round(EFFORT_WEIGHTS[weight_key] * len(group), 1)
        total_hours += hours
        top_files = sorted({f.get("file") for f in group if f.get("file")})
        first = group[0]
        items.append({
            "category": "security",
            "severity": sev,
            "title": f"{len(group)} {sev} severity security finding(s) requiring remediation",
            "evidence": (
                f"{len(group)} security findings at {sev} severity were detected by the scanner "
                f"(e.g. {first.get('file')}:{first.get('line')} — {first.get('issue')})."
            ),
            "file": top_files[0] if top_files else None,
            "line_start": first.get("line"),
            "line_end": None,
            "estimated_effort_hours": hours,
            "remediation": "Address the highest severity findings first using each finding's remediation guidance.",
        })

    # ── 2. Code smells ─────────────────────────────────────────────
    major_smells = [s for s in code_smells if (s.get("severity") or "") in ("Critical", "High")]
    minor_smells = [s for s in code_smells if (s.get("severity") or "") == "Medium"]
    if major_smells:
        hours = round(EFFORT_WEIGHTS["code_smell_major"] * len(major_smells), 1)
        total_hours += hours
        first = major_smells[0]
        items.append({
            "category": "code_smells",
            "severity": "High",
            "title": f"{len(major_smells)} high-severity code smell(s)",
            "evidence": (
                f"{len(major_smells)} code smells at High/Critical severity were detected "
                f"(e.g. {first.get('file')}:{first.get('line')} — {first.get('issue')})."
            ),
            "file": first.get("file"),
            "line_start": first.get("line"),
            "line_end": None,
            "estimated_effort_hours": hours,
            "remediation": "Refactor the flagged locations; each smell page includes a concrete refactoring suggestion.",
        })
    if minor_smells:
        hours = round(EFFORT_WEIGHTS["code_smell"] * len(minor_smells), 1)
        total_hours += hours
        items.append({
            "category": "code_smells",
            "severity": "Medium",
            "title": f"{len(minor_smells)} medium-severity code smell(s)",
            "evidence": f"{len(minor_smells)} Medium severity code smells were detected by the code quality scan.",
            "file": minor_smells[0].get("file"),
            "line_start": minor_smells[0].get("line"),
            "line_end": None,
            "estimated_effort_hours": hours,
            "remediation": "Batch clean-up: address smells file-by-file during normal maintenance.",
        })

    # ── 3. Duplicated code ─────────────────────────────────────────
    dup_findings = (duplicates or {}).get("findings") or []
    if dup_findings:
        dup_lines = sum(d["duplicated_lines"] for d in dup_findings)
        hours = round(EFFORT_WEIGHTS["duplication"] * len(dup_findings), 1)
        total_hours += hours
        worst = dup_findings[0]
        items.append({
            "category": "duplication",
            "severity": _severity_from_counts(len(dup_findings), high_at=5, med_at=2),
            "title": f"{len(dup_findings)} duplicated code block(s) (~{dup_lines} duplicated lines)",
            "evidence": (
                f"Cross-file clone detection found {len(dup_findings)} duplicated blocks "
                f"(e.g. {worst['file_a']}:{worst['start_line_a']}-{worst['end_line_a']} "
                f"≈ {worst['file_b']}:{worst['start_line_b']}-{worst['end_line_b']}, "
                f"{worst['similarity']}% similar)."
            ),
            "file": worst["file_a"],
            "line_start": worst["start_line_a"],
            "line_end": worst["end_line_a"],
            "estimated_effort_hours": hours,
            "remediation": "Extract each duplicated block into a single shared function/module and call it from both sites.",
        })

    # ── 4. Complexity hotspots ─────────────────────────────────────
    cx_findings = (complexity or {}).get("findings") or []
    high_cx = [c for c in cx_findings if c.get("severity") == "High"]
    med_cx = [c for c in cx_findings if c.get("severity") == "Medium"]
    if high_cx:
        hours = round(EFFORT_WEIGHTS["complexity_high"] * len(high_cx), 1)
        total_hours += hours
        worst = high_cx[0]
        items.append({
            "category": "complexity",
            "severity": "High",
            "title": f"{len(high_cx)} high-complexity function(s)",
            "evidence": (
                f"Static complexity analysis measured cyclomatic complexity ≥ 15 in {len(high_cx)} function(s); "
                f"worst: {worst['file']}:{worst['line_start']} '{worst['name']}' (CC {worst['cyclomatic_complexity']})."
            ),
            "file": worst["file"],
            "line_start": worst["line_start"],
            "line_end": worst.get("line_end"),
            "estimated_effort_hours": hours,
            "remediation": "Decompose the flagged functions and add unit tests around current behaviour before refactoring.",
        })
    if med_cx:
        hours = round(EFFORT_WEIGHTS["complexity_medium"] * len(med_cx), 1)
        total_hours += hours
        items.append({
            "category": "complexity",
            "severity": "Medium",
            "title": f"{len(med_cx)} medium-complexity function(s)",
            "evidence": f"Static complexity analysis measured cyclomatic complexity between 10 and 14 in {len(med_cx)} function(s).",
            "file": med_cx[0].get("file"),
            "line_start": med_cx[0].get("line_start"),
            "line_end": None,
            "estimated_effort_hours": hours,
            "remediation": "Add test coverage and simplify branching where feasible.",
        })

    # ── 5. Long functions (from complexity measurements) ───────────
    long_funcs = [c for c in cx_findings if (c.get("length_lines") or 0) > 80]
    if long_funcs:
        hours = round(EFFORT_WEIGHTS["long_functions"] * len(long_funcs), 1)
        total_hours += hours
        items.append({
            "category": "long_functions",
            "severity": "Medium",
            "title": f"{len(long_funcs)} function(s) longer than 80 lines",
            "evidence": f"Measured function lengths exceed 80 lines (longest: '{long_funcs[0]['name']}' at {long_funcs[0]['length_lines']} lines).",
            "file": long_funcs[0].get("file"),
            "line_start": long_funcs[0].get("line_start"),
            "line_end": long_funcs[0].get("line_end"),
            "estimated_effort_hours": hours,
            "remediation": "Split long functions into logical stages; extract helpers with descriptive names.",
        })

    # ── 6. TODO / FIXME markers (raw file evidence) ────────────────
    todo_hits: list[dict] = []
    for f in source_files or []:
        for idx, line in enumerate(f.get("lines") or [], start=1):
            m = TODO_PATTERN.search(line)
            if m:
                todo_hits.append({
                    "file": f["path"], "line": idx,
                    "marker": m.group(1), "text": (m.group(2) or "").strip(),
                })
    if todo_hits:
        hours = round(EFFORT_WEIGHTS["todos"] * len(todo_hits), 1)
        total_hours += hours
        by_marker: dict[str, int] = {}
        for h in todo_hits:
            by_marker[h["marker"]] = by_marker.get(h["marker"], 0) + 1
        marker_str = ", ".join(f"{k}: {v}" for k, v in sorted(by_marker.items(), key=lambda x: -x[1]))
        first = todo_hits[0]
        items.append({
            "category": "unfinished_work",
            "severity": _severity_from_counts(len(todo_hits), high_at=15, med_at=5),
            "title": f"{len(todo_hits)} TODO/FIXME/HACK marker(s) in source",
            "evidence": f"Raw source scan found markers — {marker_str}. First: {first['file']}:{first['line']}.",
            "file": first["file"],
            "line_start": first["line"],
            "line_end": None,
            "estimated_effort_hours": hours,
            "remediation": "Convert each marker into a tracked issue, then resolve or remove it.",
        })

    # ── 7. Large files ─────────────────────────────────────────────
    large = [f for f in (source_files or []) if len(f.get("lines") or []) > 500]
    if large:
        hours = round(EFFORT_WEIGHTS["large_files"] * len(large), 1)
        total_hours += hours
        worst = max(large, key=lambda f: len(f.get("lines") or []))
        items.append({
            "category": "large_files",
            "severity": _severity_from_counts(len(large), high_at=8, med_at=3),
            "title": f"{len(large)} source file(s) exceed 500 lines",
            "evidence": f"Measured file lengths exceed 500 lines (largest: {worst['path']} at {len(worst['lines'])} lines).",
            "file": worst["path"],
            "line_start": None,
            "line_end": None,
            "estimated_effort_hours": hours,
            "remediation": "Split large modules by responsibility; move cohesive groups into their own modules.",
        })

    # ── 8. Dependency debt ─────────────────────────────────────────
    dep_findings = (dependencies or {}).get("findings") or []
    vulnerable = [d for d in dep_findings if d.get("status") == "known_vulnerable"]
    outdated = [d for d in dep_findings if d.get("status") == "outdated"]
    if vulnerable:
        hours = round(EFFORT_WEIGHTS["dependency_vulnerable"] * len(vulnerable), 1)
        total_hours += hours
        first = vulnerable[0]
        items.append({
            "category": "dependencies",
            "severity": first.get("severity") or "High",
            "title": f"{len(vulnerable)} dependency(ies) with known vulnerabilities",
            "evidence": (
                f"Dependency scan matched {len(vulnerable)} package(s) against documented advisories "
                f"(e.g. {first['package_name']} {first.get('resolved_version') or first.get('version_spec')} — {first.get('advisory_id')})."
            ),
            "file": first.get("manifest_file"),
            "line_start": None,
            "line_end": None,
            "estimated_effort_hours": hours,
            "remediation": f"Upgrade to the recommended versions (e.g. {first['package_name']} ≥ {first.get('recommended_version')}).",
        })
    if outdated:
        hours = round(EFFORT_WEIGHTS["dependency_outdated"] * len(outdated), 1)
        total_hours += hours
        items.append({
            "category": "dependencies",
            "severity": "Low",
            "title": f"{len(outdated)} outdated dependency(ies)",
            "evidence": f"Dependency scan found {len(outdated)} package(s) two or more major versions behind the latest known release.",
            "file": outdated[0].get("manifest_file"),
            "line_start": None,
            "line_end": None,
            "estimated_effort_hours": hours,
            "remediation": "Schedule periodic dependency upgrades; prioritise packages with breaking-major gaps.",
        })

    # ── Assemble summary ───────────────────────────────────────────
    items.sort(key=lambda i: SEVERITY_ORDER.get(i["severity"], 9))
    by_category: dict[str, int] = {}
    for i in items:
        by_category[i["category"]] = by_category.get(i["category"], 0) + 1

    severity_counts: dict[str, int] = {}
    for i in items:
        severity_counts[i["severity"]] = severity_counts.get(i["severity"], 0) + 1

    top_areas = []
    file_counts: dict[str, float] = {}
    for i in items:
        if i.get("file"):
            file_counts[i["file"]] = file_counts.get(i["file"], 0.0) + (i.get("estimated_effort_hours") or 0)
    for fname, hours in sorted(file_counts.items(), key=lambda x: -x[1])[:5]:
        top_areas.append({"file": fname, "estimated_effort_hours": round(hours, 1)})

    # Debt score: 100 (clean) minus transparent penalties, floored at 0.
    debt_penalty = (
        8 * severity_counts.get("Critical", 0)
        + 5 * severity_counts.get("High", 0)
        + 2 * severity_counts.get("Medium", 0)
        + 1 * severity_counts.get("Low", 0)
    )
    debt_score = max(0, 100 - debt_penalty)

    if not items:
        summary_text = (
            "No technical debt items were detected by the deterministic analyzers "
            "in the scanned portion of the repository."
        )
    else:
        summary_text = (
            f"{len(items)} evidence-based debt item(s) detected across "
            f"{len(by_category)} category(ies). Total remediation estimate: "
            f"~{round(total_hours, 1)} hours (heuristic estimate — see per-item evidence; "
            "these are NOT measured actuals)."
        )

    return {
        "summary": {
            "overall_debt_score": debt_score,
            "score_explanation": "100 = no detected debt; penalties are 8/5/2/1 points per Critical/High/Medium/Low debt item.",
            "total_estimated_effort_hours": round(total_hours, 1),
            "effort_estimate_note": (
                "Effort figures are heuristic ESTIMATES derived from the transparent weights "
                f"{EFFORT_WEIGHTS}. They are not measured actuals."
            ),
            "item_count": len(items),
            "categories": by_category,
            "severity_counts": severity_counts,
            "text": summary_text,
        },
        "items": items,
        "top_impact_areas": top_areas,
    }
