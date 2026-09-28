"""
Fast Whole-Repository Scan Pipeline
====================================

Replaces the slow per-file-per-chunk LLM architecture with a pipeline that:

1. Fetches the complete repository tree (GitHub API)
2. Fetches all relevant file contents
3. Runs ALL static analysis locally and IN PARALLEL:
   - Static security scanning
   - Static code smell detection
   - Complexity analysis
   - Duplicate detection
   - Dependency scanning
   - Architecture analysis
   - Repository health (repository_analyzer)
4. Builds a COMPACT repository summary
5. Sends 1 LLM request (max 3) for intelligent synthesis
6. Generates the final report

Hard constraints:
- Every relevant file is inventoried and analyzed locally
- LLM requests: target 1, hard limit 3
- Total scan time: target <120 seconds
- No per-file LLM calls
"""

from __future__ import annotations

import os
import re
import time
import hashlib
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from app.utils.logger import get_logger
from app.utils.validation import should_skip_file, is_valid_code
from app.services.llm_client import GROQ_FALLBACK_MODEL, is_model_not_found_error, friendly_llm_error

logger = get_logger("fast_scan")

# ── Constants ──────────────────────────────────────────────────────────────
MODEL_NAME = "openai/gpt-oss-120b"
MODEL_TEMPERATURE = 0.0

# Hard limits for LLM requests
LLM_MAX_REQUESTS = 3
LLM_MAX_ATTEMPTS_PER_REQUEST = 2
LLM_MAX_RETRY_SECONDS = 5

# Time budget (seconds)
TIME_BUDGET_TOTAL = 120
TIME_BUDGET_LLM_CUTOFF = 110  # Don't start new expensive ops after this

# File size limits
MAX_FILE_BYTES = 256 * 1024  # 256 KB per file
MAX_SNIPPET_LINES = 30       # Max lines per file snippet sent to LLM
MAX_FILES_FOR_SNIPPETS = 30  # Max files to include snippets for in LLM context

# Extensions considered source code
SOURCE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".cs", ".go", ".rb",
    ".php", ".cpp", ".cc", ".c", ".h", ".hpp", ".rs", ".kt", ".swift",
}

# Extensions for config files
CONFIG_EXTENSIONS = {
    ".json", ".yaml", ".yml", ".ini", ".cfg", ".toml", ".xml", ".env",
}

# Extensions for documentation
DOC_EXTENSIONS = {".md", ".txt", ".rst", ".adoc"}

# Extension to language mapping
EXT_LANG_MAP = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".java": "Java",
    ".cs": "C#", ".go": "Go", ".rb": "Ruby", ".php": "PHP",
    ".cpp": "C/C++", ".cc": "C/C++", ".c": "C/C++", ".h": "C/C++",
    ".hpp": "C/C++", ".rs": "Rust", ".kt": "Kotlin", ".swift": "Swift",
}

# Directories excluded from code analysis (not from inventory)
EXCLUDED_DIRS = {
    ".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build",
    "coverage", "vendor", "env", "virtualenv", "site-packages", ".next",
    ".nuxt", "out", "target", "obj", "bin", "bower_components", ".terraform",
    ".idea", ".vscode", "storage", ".pytest_cache",
}


class FastScanMetrics:
    """Track performance metrics for the scan pipeline."""

    def __init__(self):
        self.start_time = time.time()
        self.repository_files = 0
        self.relevant_files = 0
        self.excluded_files = 0
        self.inventory_duration = 0.0
        self.fetch_duration = 0.0
        self.security_duration = 0.0
        self.quality_duration = 0.0
        self.dependency_duration = 0.0
        self.complexity_duration = 0.0
        self.duplicate_duration = 0.0
        self.architecture_duration = 0.0
        self.local_analysis_duration = 0.0
        self.summary_build_duration = 0.0
        self.llm_requests = 0
        self.llm_duration = 0.0
        self.llm_failures = 0
        self.llm_retries = 0
        self.report_generation_duration = 0.0
        self.total_duration = 0.0
        self.cache_hits = 0
        self.cache_misses = 0

    def elapsed(self) -> float:
        return time.time() - self.start_time

    def log_all(self):
        self.total_duration = self.elapsed()
        logger.info(
            "[FAST_SCAN] repository_files=%d relevant_files=%d excluded_files=%d",
            self.repository_files, self.relevant_files, self.excluded_files,
        )
        logger.info("[SCAN-TIMER] inventory=%.2f", self.inventory_duration)
        logger.info("[SCAN-TIMER] file_fetch=%.2f", self.fetch_duration)
        logger.info(
            "[SCAN-TIMER] security=%.2f code_quality=%.2f dependencies=%.2f "
            "complexity=%.2f duplicates=%.2f architecture=%.2f",
            self.security_duration, self.quality_duration,
            self.dependency_duration, self.complexity_duration,
            self.duplicate_duration, self.architecture_duration,
        )
        logger.info("[SCAN-TIMER] local_analysis=%.2f", self.local_analysis_duration)
        logger.info("[SCAN-TIMER] summary_build=%.2f", self.summary_build_duration)
        logger.info("[SCAN-TIMER] llm=%.2f", self.llm_duration)
        logger.info("[SCAN-LLM] requests=%d successful=%d failed=%d retries=%d",
                    self.llm_requests,
                    self.llm_requests - self.llm_failures,
                    self.llm_failures,
                    self.llm_retries)
        logger.info("[SCAN-TIMER] report=%.2f", self.report_generation_duration)
        logger.info("[SCAN-TIMER] TOTAL=%.2f", self.total_duration)
        logger.info("[FAST_SCAN] TOTAL_DURATION=%.2f", self.total_duration)
        logger.info("[FAST_SCAN] cache_hits=%d cache_misses=%d", self.cache_hits, self.cache_misses)

        if self.llm_requests > LLM_MAX_REQUESTS:
            logger.warning(
                "[PERFORMANCE-REGRESSION] llm_request_limit_exceeded=true requests=%d limit=%d",
                self.llm_requests, LLM_MAX_REQUESTS,
            )


def _is_excluded_dir(path: str) -> bool:
    """Check if a file path is inside an excluded directory."""
    parts = path.split("/")
    for part in parts[:-1]:
        if part in EXCLUDED_DIRS or part.startswith("."):
            return True
    return False


def _classify_file(path: str) -> dict:
    """Classify a file by extension into type/language."""
    ext = os.path.splitext(path)[1].lower()
    basename = os.path.basename(path).lower()

    is_test = (
        "test" in basename or "spec" in basename
        or path.startswith("tests/") or path.startswith("test/")
    )

    if ext in SOURCE_EXTENSIONS:
        lang = EXT_LANG_MAP.get(ext, "Other")
        return {"type": "source", "language": lang, "ext": ext, "is_test": is_test}
    elif ext in CONFIG_EXTENSIONS:
        return {"type": "config", "language": "Config", "ext": ext, "is_test": False}
    elif ext in DOC_EXTENSIONS:
        return {"type": "doc", "language": "Documentation", "ext": ext, "is_test": False}
    else:
        return {"type": "other", "language": "Other", "ext": ext, "is_test": is_test}


def _extract_file_metadata(path: str, content: str, classification: dict) -> dict:
    """Extract metadata from a file without LLM - imports, exports, symbols, etc."""
    lines = content.splitlines()
    line_count = len(lines)
    lang = classification["language"]

    imports = []
    exports = []
    functions = []
    classes = []

    if lang == "Python":
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                imports.append(stripped[:120])
            elif stripped.startswith("def "):
                match = re.match(r"def\s+(\w+)\s*\(", stripped)
                if match:
                    functions.append({"name": match.group(1), "line": i + 1})
            elif stripped.startswith("class "):
                match = re.match(r"class\s+(\w+)", stripped)
                if match:
                    classes.append({"name": match.group(1), "line": i + 1})
    elif lang in ("JavaScript", "TypeScript"):
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("require("):
                imports.append(stripped[:120])
            if "export " in stripped:
                exports.append(stripped[:120])
            # Functions
            func_match = re.match(
                r"(?:export\s+)?(?:async\s+)?function\s+(\w+)", stripped
            )
            if func_match:
                functions.append({"name": func_match.group(1), "line": i + 1})
            # Arrow functions assigned to const/let
            arrow_match = re.match(
                r"(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(", stripped
            )
            if arrow_match:
                functions.append({"name": arrow_match.group(1), "line": i + 1})
            # Classes
            class_match = re.match(r"(?:export\s+)?class\s+(\w+)", stripped)
            if class_match:
                classes.append({"name": class_match.group(1), "line": i + 1})
    elif lang == "Java":
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("import "):
                imports.append(stripped[:120])
            class_match = re.match(
                r"(?:public|private|protected)?\s*(?:abstract|final)?\s*class\s+(\w+)", stripped
            )
            if class_match:
                classes.append({"name": class_match.group(1), "line": i + 1})
    elif lang == "Go":
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("import "):
                imports.append(stripped[:120])
            func_match = re.match(r"func\s+(\w+)\s*\(", stripped)
            if func_match:
                functions.append({"name": func_match.group(1), "line": i + 1})

    return {
        "path": path,
        "language": lang,
        "line_count": line_count,
        "size_bytes": len(content.encode("utf-8")),
        "imports": imports[:20],
        "exports": exports[:10],
        "functions": [f["name"] for f in functions[:30]],
        "classes": [c["name"] for c in classes[:20]],
        "function_details": functions[:30],
        "class_details": classes[:20],
        "is_test": classification["is_test"],
    }


def _run_static_security_scan(files_with_content: list[dict]) -> dict:
    """Run static security scanner on all files. Returns aggregated findings."""
    t0 = time.time()
    all_findings = []
    try:
        from app.services.static_security_scanner import StaticSecurityAnalyzer
        for f in files_with_content:
            try:
                findings = StaticSecurityAnalyzer.scan(
                    code=f["content"],
                    filename=f["path"],
                    language=f["language"],
                )
                for finding in findings:
                    finding["file"] = f["path"]
                    finding["source"] = "static_analysis"
                    finding["category"] = "Security"
                all_findings.extend(findings)
            except Exception as e:
                logger.warning("Static security scan failed for %s: %s", f["path"], e)
    except Exception as e:
        logger.error("Static security scanner import failed: %s", e)
    duration = time.time() - t0
    logger.info("[FAST_SCAN] Static security scan: %d findings in %.2fs across %d files",
                len(all_findings), duration, len(files_with_content))
    return {"findings": all_findings, "duration": duration}


def _run_static_smell_scan(files_with_content: list[dict]) -> dict:
    """Run static code smell detector on all files."""
    t0 = time.time()
    all_findings = []
    try:
        from app.services.static_code_smell_detector import StaticCodeSmellDetector
        for f in files_with_content:
            try:
                findings = StaticCodeSmellDetector.scan(
                    code=f["content"],
                    filename=f["path"],
                    language=f["language"],
                )
                for finding in findings:
                    finding["file"] = f["path"]
                    finding["source"] = "static_analysis"
                    finding["category"] = "Code Smell"
                all_findings.extend(findings)
            except Exception as e:
                logger.warning("Static smell scan failed for %s: %s", f["path"], e)
    except Exception as e:
        logger.error("Static code smell detector import failed: %s", e)
    duration = time.time() - t0
    logger.info("[FAST_SCAN] Static smell scan: %d findings in %.2fs across %d files",
                len(all_findings), duration, len(files_with_content))
    return {"findings": all_findings, "duration": duration}


def _run_complexity_analysis(source_files: list[dict]) -> dict:
    """Run complexity analysis on all source files."""
    t0 = time.time()
    try:
        from app.services.complexity_analyzer import analyze_files
        result = analyze_files(source_files)
        duration = time.time() - t0
        logger.info("[FAST_SCAN] Complexity analysis: %d findings in %.2fs",
                     len(result.get("findings", [])), duration)
        return {"result": result, "duration": duration}
    except Exception as e:
        logger.error("Complexity analysis failed: %s", e, exc_info=True)
        return {"result": {"findings": [], "summary": {}}, "duration": time.time() - t0}


def _run_duplicate_detection(source_files: list[dict]) -> dict:
    """Run duplicate code detection."""
    t0 = time.time()
    try:
        from app.services.duplicate_detector import detect_duplicates
        result = detect_duplicates(source_files, min_lines=6, min_similarity=70)
        duration = time.time() - t0
        logger.info("[FAST_SCAN] Duplicate detection: %d findings in %.2fs",
                     len(result.get("findings", [])), duration)
        return {"result": result, "duration": duration}
    except Exception as e:
        logger.error("Duplicate detection failed: %s", e, exc_info=True)
        return {"result": {"findings": [], "parameters": {}}, "duration": time.time() - t0}


def _run_dependency_scan(fetcher) -> dict:
    """Run dependency scanning."""
    t0 = time.time()
    try:
        from app.services.dependency_scanner import scan_dependencies
        result = scan_dependencies(fetcher)
        duration = time.time() - t0
        logger.info("[FAST_SCAN] Dependency scan: %d findings in %.2fs",
                     result.get("summary", {}).get("total", 0), duration)
        return {"result": result, "duration": duration}
    except Exception as e:
        logger.error("Dependency scan failed: %s", e, exc_info=True)
        return {
            "result": {
                "findings": [],
                "summary": {"total": 0, "known_vulnerable": 0, "outdated": 0, "unknown": 0},
                "manifests_scanned": [],
            },
            "duration": time.time() - t0,
        }


def _run_architecture_analysis(fetcher) -> dict:
    """Run architecture analysis."""
    t0 = time.time()
    try:
        from app.services.architecture_analyzer import analyze_architecture
        result = analyze_architecture(fetcher)
        duration = time.time() - t0
        logger.info("[FAST_SCAN] Architecture analysis completed in %.2fs", duration)
        return {"result": result, "duration": duration}
    except Exception as e:
        logger.error("Architecture analysis failed: %s", e, exc_info=True)
        return {"result": {}, "duration": time.time() - t0}


def _build_compact_summary(
    inventory: list[dict],
    file_metadata: list[dict],
    security_findings: list[dict],
    smell_findings: list[dict],
    complexity_result: dict,
    duplicate_result: dict,
    dependency_result: dict,
    architecture_result: dict,
    repo_health: dict,
) -> str:
    """Build a compact structured repository summary for the LLM.

    This is the ONLY thing sent to the LLM — not every file's full content.
    """
    # Aggregate stats
    lang_counts = defaultdict(int)
    total_lines = 0
    for meta in file_metadata:
        lang_counts[meta["language"]] += 1
        total_lines += meta["line_count"]

    # Top functions/classes across repo
    all_functions = []
    all_classes = []
    for meta in file_metadata:
        for f in meta.get("function_details", []):
            all_functions.append(f"{meta['path']}:{f.get('name', '?')}")
        for c in meta.get("class_details", []):
            all_classes.append(f"{meta['path']}:{c.get('name', '?')}")

    # Architecture info
    arch = architecture_result.get("result", {})
    frameworks = arch.get("frameworks", [])
    arch_pattern = arch.get("architecture_pattern", "Unknown")
    concerns = arch.get("concerns", [])

    # Dependency info
    dep_res = dependency_result.get("result", {})
    dep_summary = dep_res.get("summary", {})
    dep_findings = dep_res.get("findings", [])[:10]  # Top 10 dep issues

    # Security summary
    sec_by_severity = defaultdict(int)
    for f in security_findings:
        sec_by_severity[f.get("severity", "Medium")] += 1
    sec_top_issues = security_findings[:15]  # Top 15 security issues

    # Smell summary
    smell_by_severity = defaultdict(int)
    for f in smell_findings:
        smell_by_severity[f.get("severity", "Medium")] += 1
    smell_top_issues = smell_findings[:10]  # Top 10 smells

    # Complexity hotspots
    cx_findings = complexity_result.get("result", {}).get("findings", [])
    cx_hotspots = sorted(cx_findings, key=lambda x: x.get("cyclomatic_complexity", 0), reverse=True)[:10]

    # Duplicate summary
    dup_findings = duplicate_result.get("result", {}).get("findings", [])

    # Build the compact text
    parts = []
    parts.append("=" * 60)
    parts.append("REPOSITORY ANALYSIS SUMMARY")
    parts.append("=" * 60)
    parts.append("")

    # File inventory
    parts.append("## FILE INVENTORY")
    parts.append(f"Total files in repository: {len(inventory)}")
    parts.append(f"Source files analyzed: {len(file_metadata)}")
    parts.append(f"Total lines of code: {total_lines}")
    parts.append("")
    parts.append("Language breakdown:")
    for lang, count in sorted(lang_counts.items(), key=lambda x: -x[1]):
        parts.append(f"  - {lang}: {count} files")
    parts.append("")

    # Architecture
    parts.append("## ARCHITECTURE")
    parts.append(f"Pattern: {arch_pattern}")
    if frameworks:
        parts.append(f"Frameworks: {', '.join(str(f) for f in frameworks[:10])}")
    if concerns:
        parts.append("Architectural concerns:")
        for c in concerns[:5]:
            parts.append(f"  - {c}")
    parts.append("")

    # Repository health
    parts.append("## REPOSITORY HEALTH")
    parts.append(f"Health score: {repo_health.get('health_score', 'N/A')}")
    if repo_health.get("deductions"):
        parts.append("Deductions:")
        for d in repo_health["deductions"]:
            parts.append(f"  - {d}")
    parts.append(f"README exists: {repo_health.get('readme_exists', False)}")
    parts.append(f"Test files: {repo_health.get('test_files_count', 0)}")
    parts.append(f"Source files: {repo_health.get('source_files_count', 0)}")
    parts.append(f"Docstring coverage: {repo_health.get('docstring_coverage', 0)}%")
    parts.append("")

    # Dependencies
    parts.append("## DEPENDENCIES")
    parts.append(f"Total packages: {dep_summary.get('total', 0)}")
    parts.append(f"Known vulnerable: {dep_summary.get('known_vulnerable', 0)}")
    parts.append(f"Outdated: {dep_summary.get('outdated', 0)}")
    if dep_findings:
        parts.append("Notable dependency issues:")
        for df in dep_findings:
            parts.append(f"  - {df.get('package_name')}: {df.get('status')} ({df.get('severity', 'info')})")
    parts.append("")

    # Security findings
    parts.append("## SECURITY FINDINGS (static analysis)")
    parts.append(f"Total: {len(security_findings)}")
    if sec_by_severity:
        parts.append(f"  Critical: {sec_by_severity.get('Critical', 0)}, "
                     f"High: {sec_by_severity.get('High', 0)}, "
                     f"Medium: {sec_by_severity.get('Medium', 0)}, "
                     f"Low: {sec_by_severity.get('Low', 0)}")
    if sec_top_issues:
        parts.append("Top security issues:")
        for si in sec_top_issues:
            parts.append(f"  - [{si.get('severity')}] {si.get('file')}:{si.get('line')} - {si.get('issue', '')[:100]}")
    parts.append("")

    # Code smells
    parts.append("## CODE QUALITY FINDINGS (static analysis)")
    parts.append(f"Total code smells: {len(smell_findings)}")
    if smell_by_severity:
        parts.append(f"  Critical: {smell_by_severity.get('Critical', 0)}, "
                     f"High: {smell_by_severity.get('High', 0)}, "
                     f"Medium: {smell_by_severity.get('Medium', 0)}, "
                     f"Low: {smell_by_severity.get('Low', 0)}")
    if smell_top_issues:
        parts.append("Top code quality issues:")
        for si in smell_top_issues:
            parts.append(f"  - [{si.get('severity')}] {si.get('file')}:{si.get('line')} - {si.get('issue', '')[:100]}")
    parts.append("")

    # Complexity
    parts.append("## COMPLEXITY HOTSPOTS")
    parts.append(f"Functions measured: {len(cx_findings)}")
    if cx_hotspots:
        parts.append("Most complex functions:")
        for ch in cx_hotspots:
            parts.append(f"  - {ch.get('file')}:{ch.get('name')} "
                        f"(complexity={ch.get('cyclomatic_complexity')}, "
                        f"lines={ch.get('length_lines', '?')})")
    parts.append("")

    # Duplicates
    parts.append("## DUPLICATE CODE")
    parts.append(f"Duplicate blocks found: {len(dup_findings)}")
    if dup_findings:
        for df in dup_findings[:5]:
            parts.append(f"  - {df.get('file_a')}:{df.get('start_line_a')}-{df.get('end_line_a')} "
                        f"≈ {df.get('file_b')}:{df.get('start_line_b')}-{df.get('end_line_b')} "
                        f"({df.get('similarity', 0)}% similar)")
    parts.append("")

    # Key file signatures (most important files by size/complexity)
    parts.append("## KEY FILE SIGNATURES")
    sorted_meta = sorted(file_metadata, key=lambda m: m.get("line_count", 0), reverse=True)
    for meta in sorted_meta[:MAX_FILES_FOR_SNIPPETS]:
        parts.append(f"\n### {meta['path']} ({meta['language']}, {meta['line_count']} lines)")
        if meta.get("classes"):
            parts.append(f"  Classes: {', '.join(meta['classes'][:10])}")
        if meta.get("functions"):
            parts.append(f"  Functions: {', '.join(meta['functions'][:15])}")
        if meta.get("imports"):
            parts.append(f"  Key imports: {'; '.join(meta['imports'][:8])}")
    parts.append("")

    # Missing tests
    if repo_health.get("missing_tests"):
        parts.append("## MISSING TESTS")
        for mt in repo_health["missing_tests"][:15]:
            parts.append(f"  - {mt}")
    parts.append("")

    return "\n".join(parts)


FAST_SCAN_SYSTEM_PROMPT = """You are an expert senior software engineer performing a comprehensive repository analysis.

You are given a COMPLETE repository summary including:
- Full file inventory with all source files
- Static security analysis findings (already detected)
- Static code quality findings (already detected)
- Complexity analysis with hotspots
- Duplicate code detection results
- Dependency analysis
- Architecture analysis
- Repository health metrics

Your job is to:
1. Synthesize all the findings into an intelligent, actionable report
2. Identify CROSS-FILE architectural issues
3. Explain the most important security and quality problems
4. Correlate findings (e.g., high complexity + no tests = high risk)
5. Produce prioritized recommendations
6. Generate a qualitative engineering assessment

IMPORTANT:
- Do NOT fabricate new findings. Work with the evidence provided.
- Focus on the MOST IMPORTANT issues, not every minor finding.
- Provide actionable, specific recommendations.
- Be concise but thorough.

Return a valid JSON object with this schema:
{
  "repository_overview": "Brief 2-3 sentence overview of the repository",
  "architecture_assessment": "Assessment of the code architecture, patterns, and structure",
  "critical_issues": [
    {
      "title": "Issue title",
      "severity": "Critical|High|Medium",
      "description": "What the issue is",
      "affected_files": ["file1.py", "file2.py"],
      "recommendation": "How to fix it"
    }
  ],
  "security_assessment": "Overall security posture assessment based on the static findings",
  "code_quality_assessment": "Overall code quality assessment",
  "technical_debt_summary": "Summary of technical debt and maintenance burden",
  "top_recommendations": [
    "Recommendation 1",
    "Recommendation 2",
    "Recommendation 3"
  ],
  "test_suggestions": "Key test suggestions for uncovered code",
  "scores": {
    "code_quality": 0-100,
    "security": 0-100,
    "maintainability": 0-100,
    "performance": 0-100,
    "technical_debt": 0-100
  },
  "qualitative_report": "Detailed markdown engineering report (2-4 paragraphs)"
}

Return ONLY the JSON. No markdown wrappers, no explanation text outside the JSON.
"""


def _call_llm_synthesis(
    client: Any,
    compact_summary: str,
    metrics: FastScanMetrics,
    model_name: str = MODEL_NAME,
) -> dict:
    """Send the compact repository summary to LLM for synthesis.

    Returns parsed JSON dict from LLM, or empty dict on failure.
    """
    if metrics.llm_requests >= LLM_MAX_REQUESTS:
        logger.warning("[FAST_SCAN] LLM request limit reached (%d). Skipping.", metrics.llm_requests)
        return {}

    if metrics.elapsed() > TIME_BUDGET_LLM_CUTOFF:
        logger.warning("[FAST_SCAN] Time budget exceeded (%.1fs). Skipping LLM.", metrics.elapsed())
        return {}

    active_model = model_name
    t0 = time.time()

    if client is None:
        logger.warning("[FAST_SCAN] No LLM client available; skipping AI synthesis (local analysis only).")
        metrics.llm_failures += 1
        return {}

    for attempt in range(LLM_MAX_ATTEMPTS_PER_REQUEST):
        try:
            logger.info(
                "[FAST_SCAN] LLM request start - attempt=%d/%d model=%s elapsed=%.1fs",
                attempt + 1, LLM_MAX_ATTEMPTS_PER_REQUEST, active_model, metrics.elapsed(),
            )
            chat_completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": FAST_SCAN_SYSTEM_PROMPT},
                    {"role": "user", "content": compact_summary},
                ],
                model=active_model,
                temperature=MODEL_TEMPERATURE,
            )
            result_text = chat_completion.choices[0].message.content
            metrics.llm_requests += 1
            metrics.llm_duration += time.time() - t0

            logger.info(
                "[FAST_SCAN] LLM request completed - duration=%.2fs response_chars=%d",
                time.time() - t0, len(result_text or ""),
            )

            # Parse the JSON response
            parsed = _parse_llm_json(result_text)
            if parsed:
                # Extract token stats
                token_stats = {"model_name": active_model, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                if hasattr(chat_completion, "usage") and chat_completion.usage:
                    token_stats["prompt_tokens"] = chat_completion.usage.prompt_tokens
                    token_stats["completion_tokens"] = chat_completion.usage.completion_tokens
                    token_stats["total_tokens"] = chat_completion.usage.total_tokens
                parsed["_token_stats"] = token_stats
                return parsed

            logger.warning("[FAST_SCAN] Failed to parse LLM JSON response")
            return {}

        except Exception as e:
            err_str = str(e).lower()
            is_rate_limit = "429" in err_str or "rate_limit" in err_str or "quota" in err_str
            is_model_error = is_model_not_found_error(e)

            if is_model_error and active_model != GROQ_FALLBACK_MODEL:
                logger.info("[FAST_SCAN] Model '%s' unavailable, falling back to %s", active_model, GROQ_FALLBACK_MODEL)
                active_model = GROQ_FALLBACK_MODEL
                continue

            if is_rate_limit and attempt < LLM_MAX_ATTEMPTS_PER_REQUEST - 1:
                metrics.llm_retries += 1
                wait_time = min(LLM_MAX_RETRY_SECONDS, 5)
                logger.warning("[FAST_SCAN] Rate limited. Waiting %ds before retry.", wait_time)
                time.sleep(wait_time)
                continue

            logger.error("[FAST_SCAN] LLM request failed: %s", e)
            metrics.llm_failures += 1
            metrics.llm_duration += time.time() - t0
            return {}

    metrics.llm_duration += time.time() - t0
    return {}


def _parse_llm_json(content: str) -> dict:
    """Parse JSON from LLM response, handling markdown wrappers."""
    if not content:
        return {}
    content = content.strip()

    # Remove markdown JSON wrapper
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
    if json_match:
        content = json_match.group(1).strip()

    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        # Try to find JSON object
        obj_match = re.search(r"\{[\s\S]*\}", content)
        if obj_match:
            try:
                data = json.loads(obj_match.group(0))
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass
    return {}


def fast_review_entire_repository(
    repo_name: str,
    github_service,
    client: Any,
    language_mapping: dict[str, str] | None = None,
    progress_callback: Any = None,
) -> dict[str, object]:
    """Fast whole-repository scan pipeline.

    Replaces the old review_entire_repository with a pipeline that:
    1. Inventories ALL files locally
    2. Runs ALL static analysis in parallel
    3. Builds a compact summary
    4. Sends 1-3 LLM requests for synthesis
    5. Returns complete results in under 2 minutes

    The return value matches the schema expected by tasks.py.
    """
    metrics = FastScanMetrics()
    start_time = time.time()

    # ═══════════════════════════════════════════════════════════════
    # PHASE 1: REPOSITORY INVENTORY (target: 0-10s)
    # ═══════════════════════════════════════════════════════════════
    if progress_callback:
        progress_callback(5, "cloning", "Fetching repository file tree...")

    t_inv = time.time()
    repo = github_service.get_repo_object(repo_name)
    default_branch = repo.default_branch

    tree_items = []
    head_sha = None
    try:
        branch = repo.get_branch(default_branch)
        head_sha = branch.commit.sha
        git_tree = repo.get_git_tree(sha=head_sha, recursive=True)
        tree_items = git_tree.tree
    except Exception as exc:
        logger.error("Error fetching repo tree: %s", exc)

    # Build complete inventory
    inventory = []
    source_file_paths = []  # Paths of files to fetch content for
    excluded_entries = []

    for item in tree_items:
        if item.type != "blob":
            continue

        path = item.path
        size = item.size or 0
        ext = os.path.splitext(path)[1].lower()
        classification = _classify_file(path)

        entry = {
            "path": path,
            "size": size,
            "ext": ext,
            "type": classification["type"],
            "language": classification["language"],
            "is_test": classification["is_test"],
            "status": "pending",
            "exclusion_reason": None,
        }

        # Check exclusions
        if should_skip_file(path):
            entry["status"] = "excluded"
            entry["exclusion_reason"] = "build artifact, dependency lock, binary or generated file"
            excluded_entries.append(entry)
            inventory.append(entry)
            continue

        if _is_excluded_dir(path):
            entry["status"] = "excluded"
            entry["exclusion_reason"] = "vendor/generated/cache directory"
            excluded_entries.append(entry)
            inventory.append(entry)
            continue

        if size > MAX_FILE_BYTES:
            entry["status"] = "excluded"
            entry["exclusion_reason"] = f"file too large ({size} bytes > {MAX_FILE_BYTES})"
            excluded_entries.append(entry)
            inventory.append(entry)
            continue

        if classification["type"] == "source" and not classification["is_test"]:
            entry["status"] = "to_analyze"
            source_file_paths.append(path)
        elif classification["type"] in ("config", "doc"):
            entry["status"] = "inventoried"
        else:
            entry["status"] = "inventoried"

        inventory.append(entry)

    metrics.inventory_duration = time.time() - t_inv
    metrics.repository_files = len(inventory)
    metrics.relevant_files = len(source_file_paths)
    metrics.excluded_files = len(excluded_entries)

    logger.info(
        "[FAST_SCAN] Inventory complete: total=%d source=%d excluded=%d in %.2fs",
        len(inventory), len(source_file_paths), len(excluded_entries),
        metrics.inventory_duration,
    )
    logger.info("[SCAN-TIMER] inventory=%.2fs repository_files=%d relevant_files=%d excluded_files=%d",
                metrics.inventory_duration, len(inventory), len(source_file_paths), len(excluded_entries))

    if progress_callback:
        progress_callback(10, "indexing", f"Repository inventory complete: {len(source_file_paths)} source files found", 0, len(source_file_paths), "")

    # ═══════════════════════════════════════════════════════════════
    # PHASE 2: FETCH FILE CONTENTS (target: 5-15s)
    # ═══════════════════════════════════════════════════════════════
    if progress_callback:
        progress_callback(15, "scanning", f"Fetching {len(source_file_paths)} source files...", 0, len(source_file_paths), "")

    t_fetch = time.time()
    files_with_content = []  # {path, content, language, lines}
    all_source_for_analysis = []  # Format needed by complexity/duplicate analyzers

    # Sort by size (smallest first) for maximum coverage
    path_sizes = {e["path"]: e["size"] for e in inventory if e["status"] == "to_analyze"}
    sorted_paths = sorted(source_file_paths, key=lambda p: path_sizes.get(p, 0))
    inventory_by_path = {e["path"]: e for e in inventory}

    # PERF: fetch all file contents IN PARALLEL instead of one-by-one.
    # The old sequential loop made ~N GitHub API calls back-to-back (~0.5s
    # each); 8 concurrent workers cut wall time to roughly N/8 calls.
    fetch_ref = head_sha or default_branch
    fetched_contents = github_service.fetch_files_parallel(
        repo_name,
        sorted_paths,
        fetch_ref,
        max_workers=8,
        progress_callback=progress_callback,
        progress_from=15,
        progress_to=25,
    )

    for path in sorted_paths:
        content = fetched_contents.get(path, "")
        if not content or not is_valid_code(content):
            # Mark as failed in inventory (O(1) dict lookup)
            entry = inventory_by_path.get(path)
            if entry is not None:
                entry["status"] = "failed"
                entry["exclusion_reason"] = "content fetch or validation failed"
            continue

        ext = os.path.splitext(path)[1].lower()
        lang = EXT_LANG_MAP.get(ext, "Python")
        if language_mapping and path in language_mapping:
            lang = language_mapping[path]

        lines = content.splitlines()
        files_with_content.append({
            "path": path,
            "content": content,
            "language": lang,
            "lines": lines,
            "line_count": len(lines),
        })

        all_source_for_analysis.append({
            "path": path,
            "content": content,
            "lines": lines,
        })

        # Update inventory status (O(1) dict lookup instead of O(N) scan)
        entry = inventory_by_path.get(path)
        if entry is not None:
            entry["status"] = "analyzed"

    metrics.fetch_duration = time.time() - t_fetch
    logger.info("[SCAN-TIMER] file_fetch=%.2fs files_fetched=%d/%d", metrics.fetch_duration, len(files_with_content), len(sorted_paths))
    logger.info("[FAST_SCAN] Fetched %d files in %.2fs", len(files_with_content), metrics.fetch_duration)

    if progress_callback:
        progress_callback(25, "scanning", f"Fetched {len(files_with_content)} files. Running analysis...", len(files_with_content), len(source_file_paths), "")

    # ═══════════════════════════════════════════════════════════════
    # PHASE 3: PARALLEL LOCAL ANALYSIS (target: 10-60s)
    # ═══════════════════════════════════════════════════════════════
    if progress_callback:
        progress_callback(30, "scanning", "Running security, quality, complexity, dependency and architecture analysis...", len(files_with_content), len(source_file_paths), "")

    t_analysis = time.time()

    # Build file metadata (fast, no I/O)
    file_metadata = []
    for f in files_with_content:
        classification = _classify_file(f["path"])
        meta = _extract_file_metadata(f["path"], f["content"], classification)
        file_metadata.append(meta)

    # Run repository health analysis (reuse existing analyze_repository)
    # Reuse the already-fetched git tree so analyze_repository does NOT make
    # its own recursive-tree GitHub call, and route all content reads through
    # the service cache (which is already primed with the fetched source files).
    def _cached_content_provider(path: str) -> str:
        return github_service.get_file_content(repo_name, path, fetch_ref)

    from app.services.repository_analyzer import analyze_repository
    try:
        repo_health = analyze_repository(
            client=client,
            github_service=github_service,
            repo_name=repo_name,
            ref=head_sha or default_branch,
            tree_items=tree_items,
            content_provider=_cached_content_provider,
            qualitative_report="PENDING",  # Don't call LLM here
        )
    except Exception as e:
        logger.error("Repository health analysis failed: %s", e)
        repo_health = {
            "health_score": 50, "deductions": ["Analysis failed"],
            "readme_exists": False, "large_files": [], "security_hotspots": [],
            "missing_tests": [], "test_files_count": 0, "source_files_count": len(files_with_content),
            "docstring_coverage": 0, "analysis_report": "PENDING",
            "directory_groups": {}, "folder_structure": "", "dependency_risks": "",
            "doc_coverage": {},
        }

    # Create a source fetcher for dependency/architecture analysis
    from app.services.source_fetcher import RepoSourceFetcher
    fetcher = RepoSourceFetcher(github_service, repo_name)

    # Run ALL independent analyses in parallel using ThreadPoolExecutor
    security_result = {}
    smell_result = {}
    complexity_result = {}
    duplicate_result = {}
    dependency_result = {}
    architecture_result = {}

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(_run_static_security_scan, files_with_content): "security",
            executor.submit(_run_static_smell_scan, files_with_content): "quality",
            executor.submit(_run_complexity_analysis, all_source_for_analysis): "complexity",
            executor.submit(_run_duplicate_detection, all_source_for_analysis): "duplicate",
            executor.submit(_run_dependency_scan, fetcher): "dependency",
            executor.submit(_run_architecture_analysis, fetcher): "architecture",
        }

        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result(timeout=60)
                if name == "security":
                    security_result = result
                    metrics.security_duration = result["duration"]
                elif name == "quality":
                    smell_result = result
                    metrics.quality_duration = result["duration"]
                elif name == "complexity":
                    complexity_result = result
                    metrics.complexity_duration = result["duration"]
                elif name == "duplicate":
                    duplicate_result = result
                    metrics.duplicate_duration = result["duration"]
                elif name == "dependency":
                    dependency_result = result
                    metrics.dependency_duration = result["duration"]
                elif name == "architecture":
                    architecture_result = result
                    metrics.architecture_duration = result["duration"]

                if progress_callback:
                    elapsed_pct = min(60, 30 + int(metrics.elapsed() / TIME_BUDGET_TOTAL * 30))
                    progress_callback(elapsed_pct, "scanning", f"Completed {name} analysis...", len(files_with_content), len(source_file_paths), "")

            except Exception as e:
                logger.error("[FAST_SCAN] %s analysis future failed: %s", name, e)

    metrics.local_analysis_duration = time.time() - t_analysis
    logger.info("[SCAN-TIMER] local_analysis=%.2fs", metrics.local_analysis_duration)
    logger.info("[FAST_SCAN] All local analyses completed in %.2fs", metrics.local_analysis_duration)

    if progress_callback:
        progress_callback(65, "scanning", "Building repository context for AI analysis...", len(files_with_content), len(source_file_paths), "")

    # ═══════════════════════════════════════════════════════════════
    # PHASE 4: BUILD COMPACT SUMMARY (target: 60-90s)
    # ═══════════════════════════════════════════════════════════════
    t_summary = time.time()

    security_findings = security_result.get("findings", [])
    smell_findings = smell_result.get("findings", [])

    compact_summary = _build_compact_summary(
        inventory=inventory,
        file_metadata=file_metadata,
        security_findings=security_findings,
        smell_findings=smell_findings,
        complexity_result=complexity_result,
        duplicate_result=duplicate_result,
        dependency_result=dependency_result,
        architecture_result=architecture_result,
        repo_health=repo_health,
    )

    metrics.summary_build_duration = time.time() - t_summary
    logger.info("[FAST_SCAN] Compact summary built in %.2fs (%d chars)",
                metrics.summary_build_duration, len(compact_summary))

    if progress_callback:
        progress_callback(70, "generating_insights", "AI analysis of complete repository...", len(files_with_content), len(source_file_paths), "")

    # ═══════════════════════════════════════════════════════════════
    # PHASE 5: LLM SYNTHESIS (target: 90-110s) — 1 request
    # ═══════════════════════════════════════════════════════════════
    llm_result = _call_llm_synthesis(client, compact_summary, metrics)

    token_stats = llm_result.pop("_token_stats", {
        "model_name": MODEL_NAME, "prompt_tokens": 0,
        "completion_tokens": 0, "total_tokens": 0,
    })

    # Determine if LLM was available
    llm_available = bool(llm_result)
    if not llm_available:
        logger.warning("[FAST_SCAN] LLM synthesis unavailable; report generated from static analysis only.")

    if progress_callback:
        progress_callback(85, "generating_insights", "Generating final report...", len(files_with_content), len(source_file_paths), "")

    # ═══════════════════════════════════════════════════════════════
    # PHASE 6: AGGREGATE RESULTS (target: 110-120s)
    # ═══════════════════════════════════════════════════════════════
    t_report = time.time()

    # Build all_findings from static analysis
    all_findings = []

    for sf in security_findings:
        all_findings.append({
            "file": sf.get("file", ""),
            "line": int(sf.get("line", 1)) if str(sf.get("line", "")).isdigit() else 1,
            "severity": sf.get("severity", "Medium"),
            "category": "Security",
            "issue": sf.get("issue", "Security issue detected"),
            "suggestion": sf.get("suggestion", "Review and fix this security issue."),
            "why_it_matters": sf.get("why_it_matters", sf.get("issue", "")),
            "risk_level": sf.get("risk_level", sf.get("severity", "Medium")),
            "before_code": sf.get("before_code", ""),
            "after_code": sf.get("after_code", ""),
            "source": "static_analysis",
            "start_line": sf.get("start_line", sf.get("line", 1)),
            "end_line": sf.get("end_line", sf.get("line", 1)),
        })

    for sf in smell_findings:
        all_findings.append({
            "file": sf.get("file", ""),
            "line": int(sf.get("line", 1)) if str(sf.get("line", "")).isdigit() else 1,
            "severity": sf.get("severity", "Low"),
            "category": "Code Smell",
            "issue": sf.get("issue", "Code quality issue detected"),
            "suggestion": sf.get("suggestion", "Refactor this code."),
            "why_it_matters": sf.get("why_it_matters", sf.get("issue", "")),
            "risk_level": sf.get("risk_level", sf.get("severity", "Low")),
            "before_code": sf.get("before_code", ""),
            "after_code": sf.get("after_code", ""),
            "source": "static_analysis",
            "start_line": sf.get("start_line", sf.get("line", 1)),
            "end_line": sf.get("end_line", sf.get("line", 1)),
        })

    # Add critical issues from LLM as findings
    if llm_result:
        for ci in llm_result.get("critical_issues", []):
            if ci.get("severity") in ("Critical", "High"):
                all_findings.append({
                    "file": (ci.get("affected_files") or [""])[0],
                    "line": 1,
                    "severity": ci.get("severity", "High"),
                    "category": "Security" if "security" in ci.get("title", "").lower() else "Code Smell",
                    "issue": ci.get("title", "Issue identified"),
                    "suggestion": ci.get("recommendation", ""),
                    "why_it_matters": ci.get("description", ""),
                    "risk_level": ci.get("severity", "High"),
                    "before_code": "",
                    "after_code": "",
                    "source": "ai_analysis",
                })

    # Severity counts
    severity_counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0, "Info": 0}
    for f in all_findings:
        sev = f.get("severity", "Medium")
        if sev in severity_counts:
            severity_counts[sev] += 1

    risk_score = min(
        100,
        25 * severity_counts["Critical"]
        + 15 * severity_counts["High"]
        + 6 * severity_counts["Medium"]
        + 1 * severity_counts["Low"],
    )

    # Build scores
    if llm_result and llm_result.get("scores"):
        scores = llm_result["scores"]
    else:
        # Compute from findings deterministically
        from app.services.reviewer import calculate_fallback_scores
        scores = calculate_fallback_scores(risk_score, severity_counts)

    # Build qualitative report
    if llm_available:
        report_parts = []
        if llm_result.get("repository_overview"):
            report_parts.append(f"## Repository Overview\n{llm_result['repository_overview']}\n")
        if llm_result.get("architecture_assessment"):
            report_parts.append(f"## Architecture Assessment\n{llm_result['architecture_assessment']}\n")
        if llm_result.get("security_assessment"):
            report_parts.append(f"## Security Assessment\n{llm_result['security_assessment']}\n")
        if llm_result.get("code_quality_assessment"):
            report_parts.append(f"## Code Quality Assessment\n{llm_result['code_quality_assessment']}\n")
        if llm_result.get("technical_debt_summary"):
            report_parts.append(f"## Technical Debt\n{llm_result['technical_debt_summary']}\n")
        if llm_result.get("top_recommendations"):
            report_parts.append("## Top Recommendations\n")
            for i, rec in enumerate(llm_result["top_recommendations"], 1):
                report_parts.append(f"{i}. {rec}")
            report_parts.append("")
        if llm_result.get("qualitative_report"):
            report_parts.append(f"## Detailed Analysis\n{llm_result['qualitative_report']}\n")
        qualitative_report = "\n".join(report_parts)
    else:
        qualitative_report = (
            "## Repository Analysis\n\n"
            "AI enrichment unavailable; report generated from complete static repository analysis.\n\n"
            f"**Files analyzed:** {len(files_with_content)}\n"
            f"**Security findings:** {len(security_findings)}\n"
            f"**Code quality findings:** {len(smell_findings)}\n"
            f"**Health score:** {repo_health.get('health_score', 'N/A')}\n"
        )

    # Build repo_analysis dict (matches what tasks.py expects)
    repo_analysis = dict(repo_health)
    repo_analysis["analysis_report"] = qualitative_report

    # Build inline_comments
    inline_comments = []
    for f in all_findings:
        body_text = (
            f"File: {f['file']}\nLine: {f['line']}\n"
            f"Issue: {f['issue']}\nSeverity: {f['severity']}\n"
            f"Recommendation: {f['suggestion']}"
        )
        inline_comments.append({
            "file": f["file"],
            "line": f["line"],
            "body": body_text,
            "patch": f"@@ -1,1 +1,{f['line']} @@\n+{f['issue']}",
        })

    # Build files_analyzed_log (complete inventory status)
    files_analyzed_log = []
    analyzed_set = {f["path"] for f in files_with_content}
    for entry in inventory:
        file_type = entry["language"]
        if entry["type"] == "config":
            file_type = "Configuration"
        elif entry["type"] == "doc":
            file_type = "Documentation"

        if entry["status"] == "analyzed":
            finding_count = sum(1 for f in all_findings if f.get("file") == entry["path"])
            files_analyzed_log.append({
                "file": entry["path"],
                "type": file_type,
                "status": "Analyzed",
                "findings": finding_count,
            })
        elif entry["status"] == "excluded":
            files_analyzed_log.append({
                "file": entry["path"],
                "type": file_type,
                "status": "Skipped",
                "reason": entry.get("exclusion_reason", "excluded"),
                "findings": 0,
            })
        elif entry["status"] == "failed":
            files_analyzed_log.append({
                "file": entry["path"],
                "type": file_type,
                "status": "Failed",
                "reason": entry.get("exclusion_reason", "content unavailable"),
                "findings": 0,
            })
        else:
            files_analyzed_log.append({
                "file": entry["path"],
                "type": file_type,
                "status": "Inventoried",
                "findings": 0,
            })

    # Build test suggestions
    test_suggestions = ""
    if llm_result and llm_result.get("test_suggestions"):
        test_suggestions = llm_result["test_suggestions"]
    elif repo_health.get("missing_tests"):
        test_suggestions = "### Missing Test Coverage\n"
        for mt in repo_health["missing_tests"][:10]:
            test_suggestions += f"- {mt}\n"

    characters_analyzed_count = sum(len(f["content"]) for f in files_with_content)
    estimated_tokens_count = characters_analyzed_count // 4

    metrics.report_generation_duration = time.time() - t_report
    latency = round(time.time() - start_time, 2)

    # Log all metrics
    metrics.log_all()

    if progress_callback:
        progress_callback(95, "scanning", "Finalizing report...", len(files_with_content), len(source_file_paths), "")

    # Store analysis results for insights orchestrator to use
    # (complexity, duplicate, dependency, architecture are passed via the result dict)
    result = {
        "repo_name": repo_name,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "risk_score": risk_score,
        "findings": all_findings,
        "inline_comments": inline_comments,
        "test_suggestions": test_suggestions,
        "repo_analysis": repo_analysis,
        "severity_counts": severity_counts,
        "latency_seconds": latency,
        "head_sha": head_sha,
        "branch": default_branch,
        "total_files_analyzed": len(files_with_content),
        "total_files_count": len(source_file_paths),
        "files_analyzed_log": files_analyzed_log,
        "files_analyzed_count": len(files_with_content),
        "characters_analyzed_count": characters_analyzed_count,
        "estimated_tokens_count": estimated_tokens_count,
        "estimated_token_usage": estimated_tokens_count,
        "groq_requests_made": metrics.llm_requests,
        "cached_results_used": 0,
        "scores": scores,
        "token_stats": token_stats,
        # Pass pre-computed analysis results for insights_orchestrator
        "_fast_scan_precomputed": {
            "security_findings": security_findings,
            "smell_findings": smell_findings,
            "complexity_result": complexity_result.get("result", {}),
            "duplicate_result": duplicate_result.get("result", {"findings": [], "parameters": {}}),
            "dependency_result": dependency_result.get("result", {}),
            "architecture_result": architecture_result.get("result", {}),
            "source_files": all_source_for_analysis,
            "metrics": {
                "total_duration": metrics.total_duration,
                "llm_requests": metrics.llm_requests,
                "local_analysis_duration": metrics.local_analysis_duration,
                "llm_duration": metrics.llm_duration,
            },
        },
    }

    logger.info(
        "[FAST_SCAN] COMPLETE: files=%d findings=%d llm_requests=%d total_duration=%.2fs",
        len(files_with_content), len(all_findings), metrics.llm_requests, latency,
    )

    return result
