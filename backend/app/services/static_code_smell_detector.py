"""
Static Code Smell Detector — pattern-based code quality detection.

Runs deterministic scanners against source code to detect common code smells
WITHOUT relying on an LLM. Each scanner returns findings with line numbers,
severity, issue type, and refactoring suggestions.

Supported detection types:
  • Magic Numbers / Magic Strings
  • Long Functions / Methods
  • Duplicate Code Blocks
  • Unused Imports
  • Deep Nesting
  • Long Parameter Lists

Usage:
    from app.services.static_code_smell_detector import StaticCodeSmellDetector
    findings = StaticCodeSmellDetector.scan(code, filename="app.py", language="python")
"""

from __future__ import annotations

import re
import hashlib
from typing import Any
from collections import Counter


def _build_finding(
    *,
    line: int,
    severity: str,
    issue: str,
    suggestion: str,
    category: str = "Code Smell",
    before_code: str | None = None,
    after_code: str | None = None,
    file: str = "",
    why_it_matters: str | None = None,
    risk_level: str | None = None,
) -> dict[str, Any]:
    return {
        "line": line,
        "severity": severity,
        "category": category,
        "issue": issue,
        "suggestion": suggestion,
        "why_it_matters": why_it_matters or issue,
        "risk_level": risk_level or severity,
        "before_code": before_code or "",
        "after_code": after_code or "",
        "file": file,
        "source": "static_analysis",
    }


class StaticCodeSmellDetector:
    """Run all static smell scanners against *code* and return a list of findings."""

    SCANNERS: list[dict] = []

    @classmethod
    def scan(
        cls,
        code: str,
        filename: str = "",
        language: str = "",
    ) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for scanner in cls.SCANNERS:
            try:
                result = scanner["fn"](code, filename, language)
                if isinstance(result, list):
                    for f in result:
                        f["file"] = f.get("file") or filename
                    findings.extend(result)
            except Exception:
                continue
        # Deduplicate by (line, issue)
        seen = set()
        unique = []
        for f in findings:
            key = (f["line"], f["issue"][:60])
            if key not in seen:
                seen.add(key)
                unique.append(f)
        return unique

    @classmethod
    def register(cls, name: str, severity: str):
        def decorator(fn):
            cls.SCANNERS.append({
                "name": name,
                "severity": severity,
                "fn": fn,
            })
            return fn
        return decorator


# ═════════════════════════════════════════════════════════════════════════════
# 1. MAGIC NUMBERS — numeric literals used directly in code
# ═════════════════════════════════════════════════════════════════════════════

_MAGIC_NUMBER_EXCEPTIONS = {
    0, 1, -1, 2,  # common constants
    100,  # percentage
    0.0, 1.0, -1.0,
    10,  # base-10
}

@StaticCodeSmellDetector.register("magic_numbers", "Medium")
def _scan_magic_numbers(code: str, filename: str, language: str) -> list[dict]:
    findings = []
    lines = code.splitlines()

    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith(("#", "//", "--", "*", "/*")):
            continue

        # Find numeric literals in the code (not in strings/comments)
        # Remove string contents to avoid false positives
        cleaned = re.sub(r'"[^"]*"', '""', stripped)
        cleaned = re.sub(r"'[^']*'", "''", cleaned)
        cleaned = re.sub(r"#[^#]*$", "", cleaned)  # remove inline comments

        for m in re.finditer(r'(?<![A-Za-z_])(\d+\.?\d*)(?![A-Za-z_])', cleaned):
            val_str = m.group(1)
            try:
                if "." in val_str:
                    val = float(val_str)
                else:
                    val = int(val_str)
            except ValueError:
                continue

            if val in _MAGIC_NUMBER_EXCEPTIONS:
                continue
            if val > 10000 or val < -10000:
                continue  # likely a line number or large constant

            var_match = re.match(r'\s*(\w+)\s*[=]', stripped)
            var_name = var_match.group(1) if var_match else None
            if var_name and var_name.upper() == var_name:
                continue  # likely already a constant

            # Skip if it's in a range() call or similar
            if re.search(r'range\s*\(', stripped):
                continue

            findings.append(_build_finding(
                line=line_no,
                severity="Medium",
                issue=f"Magic Number: {val_str}",
                suggestion=f"Extract the magic number {val_str} into a named constant for better readability and maintainability.",
                before_code=stripped,
                after_code=f"# Define a named constant\nCONSTANT_NAME = {val_str}\n# Then use CONSTANT_NAME in the code",
                why_it_matters=(
                    f"Magic number {val_str} makes the code harder to understand. "
                    "Named constants explain the purpose and make the code self-documenting."
                ),
            ))

    # Deduplicate: one finding per line, limit to top 5
    seen_lines = set()
    deduped = []
    for f in findings:
        if f["line"] not in seen_lines:
            seen_lines.add(f["line"])
            deduped.append(f)
    return deduped[:5]


# ═════════════════════════════════════════════════════════════════════════════
# 2. LONG FUNCTIONS — functions exceeding a reasonable line count
# ═════════════════════════════════════════════════════════════════════════════

_LONG_FUNC_THRESHOLD = {
    "python": 50,
    "javascript": 60,
    "typescript": 60,
    "java": 60,
    "go": 60,
}

_FUNC_DEF_PATTERNS = {
    "python": re.compile(r'^(\s*)def\s+(\w+)\s*\(', re.MULTILINE),
    "javascript": re.compile(r'^(\s*)(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:function|\([^)]*\)\s*=>))', re.MULTILINE),
    "typescript": re.compile(r'^(\s*)(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*[=:])', re.MULTILINE),
    "java": re.compile(r'^(\s*)(?:public|private|protected|static|final|async)*\s*\w+(?:<[^>]+>)?\s+(\w+)\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{', re.MULTILINE),
    "go": re.compile(r'^(\s*)func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(', re.MULTILINE),
}


@StaticCodeSmellDetector.register("long_function", "Medium")
def _scan_long_functions(code: str, filename: str, language: str) -> list[dict]:
    findings = []
    lines = code.splitlines()
    lang = language.lower() if language else "python"
    threshold = _LONG_FUNC_THRESHOLD.get(lang, 50)

    # Find function definitions and their approximate end points
    func_starts = []

    pattern = _FUNC_DEF_PATTERNS.get(lang)
    if not pattern:
        # Fallback: detect Python-style def
        pattern = _FUNC_DEF_PATTERNS["python"]

    for m in pattern.finditer(code):
        line_no = code[:m.start()].count("\n") + 1
        func_name = m.group(2) or m.group(3) or "anonymous"
        func_starts.append((line_no, func_name))

    # Simple heuristic: estimate function length by looking at indentation
    for start_line, func_name in func_starts:
        func_end = start_line
        if start_line <= len(lines):
            base_indent = len(lines[start_line - 1]) - len(lines[start_line - 1].lstrip())
            for check_line in range(start_line, len(lines)):
                check_stripped = lines[check_line].strip()
                if check_stripped == "":
                    func_end = check_line + 1
                    continue
                check_indent = len(lines[check_line]) - len(lines[check_line].lstrip())
                if check_indent <= base_indent and check_stripped and check_line > start_line:
                    func_end = check_line
                    break
                func_end = check_line + 1

        func_length = func_end - start_line
        if func_length > threshold:
            findings.append(_build_finding(
                line=start_line,
                severity="High" if func_length > threshold * 2 else "Medium",
                issue=f"Long Function: {func_name} ({func_length} lines)",
                suggestion=(
                    f"Function '{func_name}' is {func_length} lines long (threshold: {threshold}). "
                    "Break it into smaller, focused functions that each do one thing well."
                ),
                before_code=lines[start_line - 1].strip() if start_line <= len(lines) else "",
                after_code=f"# Break {func_name} into smaller helper functions:\n# def {func_name}_step1(...):\n#     ...\n# def {func_name}_step2(...):\n#     ...\n# def {func_name}(...):\n#     step1_result = {func_name}_step1(...)\n#     return {func_name}_step2(step1_result)",
                why_it_matters=(
                    f"Long functions are harder to understand, test, and maintain. "
                    "They violate the Single Responsibility Principle and increase cognitive load."
                ),
            ))

    return findings[:3]


# ═════════════════════════════════════════════════════════════════════════════
# 3. DUPLICATE CODE — detect repeated code blocks
# ═════════════════════════════════════════════════════════════════════════════

@StaticCodeSmellDetector.register("duplicate_code", "Medium")
def _scan_duplicate_code(code: str, filename: str, language: str) -> list[dict]:
    findings = []
    lines = code.splitlines()

    if len(lines) < 6:
        return findings

    # Normalize lines for comparison (strip whitespace, skip comments/blank)
    normalized = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith(("#", "//", "--", "/*")):
            normalized.append((i + 1, stripped))

    # Look for repeated blocks of 3+ lines
    block_size = 3
    seen_blocks: dict[str, list[int]] = {}

    for i in range(len(normalized) - block_size + 1):
        block_lines = tuple(normalized[j][1] for j in range(i, i + block_size))
        block_hash = hashlib.md5("|".join(block_lines).encode()).hexdigest()

        if block_hash not in seen_blocks:
            seen_blocks[block_hash] = []
        seen_blocks[block_hash].append(normalized[i][0])

    for block_hash, line_numbers in seen_blocks.items():
        if len(line_numbers) >= 2:
            # Check if the duplicates are far enough apart to be meaningful
            unique_starts = sorted(set(line_numbers))
            for start in unique_starts[:1]:
                findings.append(_build_finding(
                    line=start,
                    severity="Medium",
                    issue=f"Duplicate Code Block ({len(line_numbers)} occurrences)",
                    suggestion=(
                        "This code block appears multiple times. "
                        "Extract it into a shared function or utility method."
                    ),
                    before_code="\n".join(lines[start - 1:start + block_size - 1]),
                    after_code="# Extract this into a shared function:\n# def shared_function():\n#     ...\n# Then call shared_function() at each location",
                    why_it_matters=(
                        "Duplicate code increases maintenance burden. When one copy is "
                        "updated, the others may be forgotten, leading to inconsistencies."
                    ),
                ))
                break  # one per block

    return findings[:3]


# ═════════════════════════════════════════════════════════════════════════════
# 4. UNUSED IMPORTS — detect imports that are never referenced
# ═════════════════════════════════════════════════════════════════════════════

@StaticCodeSmellDetector.register("unused_import", "Low")
def _scan_unused_imports(code: str, filename: str, language: str) -> list[dict]:
    findings = []
    lines = code.splitlines()
    lang = language.lower() if language else "python"

    if lang != "python":
        return findings  # only Python for now

    import_lines = []
    rest_lines = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            # Extract imported names
            if stripped.startswith("from "):
                m = re.match(r'from\s+\S+\s+import\s+(.+)', stripped)
                if m:
                    names = [n.strip().split(" as ")[0].strip() for n in m.group(1).split(",")]
                    import_lines.append((i + 1, stripped, names))
            else:
                m = re.match(r'import\s+(.+)', stripped)
                if m:
                    names = [n.strip().split(" as ")[0].strip() for n in m.group(1).split(",")]
                    import_lines.append((i + 1, stripped, names))
        else:
            rest_lines.append(line)

    rest_text = "\n".join(rest_lines)

    for line_no, import_line, names in import_lines:
        for name in names:
            if name == "*":
                continue
            # Check if the imported name is used anywhere in the rest of the code
            if not re.search(r'\b' + re.escape(name) + r'\b', rest_text):
                findings.append(_build_finding(
                    line=line_no,
                    severity="Low",
                    issue=f"Unused Import: '{name}'",
                    suggestion=f"Remove the unused import '{name}' to keep the code clean and reduce cognitive load.",
                    before_code=import_line,
                    after_code=f"# Remove: {import_line}",
                    why_it_matters=(
                        f"'{name}' is imported but never used in the code. "
                        "Unused imports increase cognitive load and can mask missing functionality."
                    ),
                ))

    return findings[:5]


# ═════════════════════════════════════════════════════════════════════════════
# 5. DEEP NESTING — detect excessive indentation levels
# ═════════════════════════════════════════════════════════════════════════════

@StaticCodeSmellDetector.register("deep_nesting", "Medium")
def _scan_deep_nesting(code: str, filename: str, language: str) -> list[dict]:
    findings = []
    lines = code.splitlines()
    max_depth_threshold = 4  # 4 levels of nesting

    deepest_line = 0
    deepest_depth = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//", "--", "/*")):
            continue

        indent = len(line) - len(line.lstrip())
        # Use 4 spaces or 1 tab as one level
        depth = indent // 4 if indent >= 4 else (indent if "\t" in line[:indent] else 0)

        if depth > deepest_depth:
            deepest_depth = depth
            deepest_line = i + 1

    if deepest_depth > max_depth_threshold:
        findings.append(_build_finding(
            line=deepest_line,
            severity="Medium",
            issue=f"Deep Nesting: {deepest_depth} levels deep (threshold: {max_depth_threshold})",
            suggestion=(
                "Refactor to reduce nesting depth using early returns, guard clauses, "
                "or extracting nested logic into helper functions."
            ),
            before_code=lines[deepest_line - 1].strip() if deepest_line <= len(lines) else "",
            after_code="# Use guard clauses / early returns:\n# if not valid_input:\n#     return error\n# # Continue with main logic at lower nesting",
            why_it_matters=(
                f"Code nested {deepest_depth} levels deep is hard to read and test. "
                "Deep nesting increases cognitive load and makes bugs harder to spot."
            ),
        ))

    return findings


# ═════════════════════════════════════════════════════════════════════════════
# 6. LONG PARAMETER LISTS — functions with too many parameters
# ═════════════════════════════════════════════════════════════════════════════

_LONG_PARAM_THRESHOLD = 5

_PARAM_PATTERNS = {
    "python": re.compile(r'def\s+(\w+)\s*\(([^)]*)\)', re.DOTALL),
    "javascript": re.compile(r'(?:function\s+(\w+)|(\w+)\s*=\s*(?:async\s+)?function)\s*\(([^)]*)\)', re.DOTALL),
    "typescript": re.compile(r'(?:function\s+(\w+)|(\w+)\s*[:=]\s*(?:async\s+)?(?:function|\([^)]*\)\s*=>))\s*\(([^)]*)\)', re.DOTALL),
    "java": re.compile(r'(?:public|private|protected|static|final|async)*\s*\w+(?:<[^>]+>)?\s+(\w+)\s*\(([^)]*)\)', re.DOTALL),
    "go": re.compile(r'func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(([^)]*)\)', re.DOTALL),
}


@StaticCodeSmellDetector.register("long_parameter_list", "Medium")
def _scan_long_params(code: str, filename: str, language: str) -> list[dict]:
    findings = []
    lang = language.lower() if language else "python"

    pattern = _PARAM_PATTERNS.get(lang) or _PARAM_PATTERNS.get("python")
    if not pattern:
        return findings

    for m in pattern.finditer(code):
        func_name = m.group(1) or "anonymous"
        params_str = m.group(2) if m.lastindex >= 2 else m.group(3) if m.lastindex >= 3 else ""

        if not params_str or not params_str.strip():
            continue

        # Count parameters
        params = [p.strip() for p in params_str.split(",") if p.strip()]
        if len(params) > _LONG_PARAM_THRESHOLD:
            line_no = code[:m.start()].count("\n") + 1
            findings.append(_build_finding(
                line=line_no,
                severity="Medium",
                issue=f"Long Parameter List: {func_name}({len(params)} params)",
                suggestion=(
                    f"Function '{func_name}' has {len(params)} parameters. "
                    "Consider grouping related parameters into a configuration object, data class, or using keyword arguments."
                ),
                before_code=f"def {func_name}({', '.join(params[:3])}, ...)",
                after_code=f"# Group related params into a config/dataclass:\nclass {func_name.title().replace('_', '')}Config:\n" + "\n".join(f"    {p.split(':')[0].split('=')[0].strip()}: ..." for p in params[:4]),
                why_it_matters=(
                    f"Functions with {len(params)}+ parameters are hard to call correctly "
                    "and difficult to maintain. Grouping related parameters improves API design."
                ),
            ))

    return findings[:3]
