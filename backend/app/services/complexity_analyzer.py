"""
Code Complexity Analysis — deterministic static analysis.

Python functions are measured with a real AST-based cyclomatic complexity
(1 base + 1 per decision point: if/elif/for/while/except/with-guard/
boolean-op/ternary/comprehension-if/assert/match-case).
JavaScript/TypeScript functions are measured with a conservative
delimiter/keyword counter on the real source text.

No complexity value is ever invented: unsupported languages are skipped.
"""

from __future__ import annotations

import ast
import re
from typing import Any

from app.utils.logger import get_logger

logger = get_logger("complexity_analyzer")

MAX_FINDINGS = 80

# Severity thresholds for cyclomatic complexity (deterministic categories).
SEVERITY_THRESHOLDS = {
    "High": 15,     # CC >= 15
    "Medium": 10,   # CC >= 10
    # everything below is Low (not reported)
}
LOW_REPORT_THRESHOLD = 8  # report CC >= 8 so users see emerging hotspots


def _py_decision_points(node: ast.AST) -> int:
    """Count decision points in a Python AST node subtree."""
    points = 0
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While,
                              ast.ExceptHandler, ast.IfExp)):
            points += 1
        elif isinstance(child, ast.BoolOp):
            points += max(0, len(child.values) - 1)
        elif isinstance(child, ast.comprehension):
            points += 1 + len(child.ifs)
        elif isinstance(child, ast.Assert):
            points += 1
        elif hasattr(ast, "match_case") and isinstance(child, ast.match_case):
            points += 1
    return points


def _py_max_nesting(node: ast.AST) -> int:
    """Maximum nesting depth of compound statements."""
    max_depth = 0

    def visit(node: ast.AST, depth: int):
        nonlocal max_depth
        compound = isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While,
                                     ast.With, ast.AsyncWith, ast.Try))
        new_depth = depth + (1 if compound else 0)
        max_depth = max(max_depth, new_depth)
        for child in ast.iter_child_nodes(node):
            visit(child, new_depth)

    visit(node, 0)
    return max_depth


def analyze_python(content: str) -> list[dict]:
    """Analyze Python source; returns per-function metrics."""
    results = []
    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        logger.debug(f"Python parse failed (skipping file): {exc}")
        return results

    lines = content.splitlines()

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.class_stack: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef):
            self.class_stack.append(node.name)
            for child in node.body:
                self.visit(child)
            self.class_stack.pop()

        def _handle_function(self, node):
            name = node.name
            if self.class_stack:
                name = f"{self.class_stack[-1]}.{name}"
            length = (node.end_lineno or node.lineno) - node.lineno + 1
            results.append({
                "name": name,
                "kind": "method" if self.class_stack else "function",
                "line_start": node.lineno,
                "line_end": node.end_lineno or node.lineno,
                "cyclomatic_complexity": 1 + _py_decision_points(node),
                "nesting_depth": _py_max_nesting(node),
                "length_lines": length,
                "language": "Python",
                "signature_line": lines[node.lineno - 1].strip() if node.lineno <= len(lines) else "",
            })
            for child in node.body:
                self.visit(child)

        visit_FunctionDef = _handle_function
        visit_AsyncFunctionDef = _handle_function

    Visitor().visit(tree)
    return results


# ── JavaScript / TypeScript ───────────────────────────────────────────

_JS_FUNC_PATTERNS = [
    # function name(...) {...}
    re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\("),
    # const/let/var name = (...) => / name = function(...)
    re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"),
    re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?function\b"),
    # class methods: name(...) { — heuristic: indented identifier + ( ) {
    re.compile(r"^\s+(?:async\s+)?([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{", re.MULTILINE),
]

_JS_DECISION_KEYWORDS = re.compile(
    r"\b(if|for|while|case|catch)\b|\?\?|\|\||&&|\?.*:|\bdefault:",
)
_JS_OPEN_BRACES = "{"
_JS_CLOSE_BRACES = "}"


def _strip_js_noise(text: str) -> str:
    """Remove string literals and comments so brace counting is accurate."""
    text = re.sub(r"`(?:\\.|[^`\\])*`", "``", text)          # template literals
    text = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', text)        # double-quoted
    text = re.sub(r"'(?:\\.|[^'\\\n])*'", "''", text)        # single-quoted
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)   # block comments
    text = re.sub(r"//[^\n]*", "", text)                      # line comments
    return text


def analyze_js(content: str, language: str) -> list[dict]:
    """Analyze JavaScript/TypeScript source with conservative heuristics."""
    results = []
    stripped = _strip_js_noise(content)
    lines = content.splitlines()

    matches = []
    seen_positions = set()
    for pattern in _JS_FUNC_PATTERNS:
        for m in pattern.finditer(stripped):
            # Avoid duplicate hits at the same position from different patterns
            key = (m.start(1), m.group(1))
            if key in seen_positions:
                continue
            seen_positions.add(key)
            matches.append(m)

    matches.sort(key=lambda m: m.start(1))

    for m in matches:
        name = m.group(1)
        if name in ("if", "for", "while", "switch", "catch", "return", "function"):
            continue
        start_line = stripped[: m.start()].count("\n") + 1

        # Find the function body via balanced braces starting after the params
        # Locate first { after the match, then balance
        brace_start = stripped.find("{", m.end() - 1)
        if brace_start == -1:
            # Arrow without braces (single expression) — use until blank line
            end_line = start_line
            body = ""
            depth_cc = 0
        else:
            depth = 0
            end_pos = brace_start
            for i in range(brace_start, len(stripped)):
                if stripped[i] == _JS_OPEN_BRACES:
                    depth += 1
                elif stripped[i] == _JS_CLOSE_BRACES:
                    depth -= 1
                    if depth == 0:
                        end_pos = i
                        break
            body = stripped[brace_start:end_pos]
            end_line = stripped[:end_pos].count("\n") + 1

        cc = 1 + len(_JS_DECISION_KEYWORDS.findall(body))
        # Nesting depth inside the body
        nesting = 0
        max_nesting = 0
        for ch in body:
            if ch == "{":
                nesting += 1
                max_nesting = max(max_nesting, nesting)
            elif ch == "}":
                nesting = max(0, nesting - 1)

        results.append({
            "name": name,
            "kind": "function",
            "line_start": start_line,
            "line_end": end_line,
            "cyclomatic_complexity": cc,
            "nesting_depth": max_nesting,
            "length_lines": end_line - start_line + 1,
            "language": language,
            "signature_line": lines[start_line - 1].strip() if start_line <= len(lines) else "",
        })

    return results


def severity_for(cc: int, length: int) -> str:
    if cc >= SEVERITY_THRESHOLDS["High"] or length > 150:
        return "High"
    if cc >= SEVERITY_THRESHOLDS["Medium"] or length > 100:
        return "Medium"
    return "Low"


def _explanation(name: str, cc: int, length: int, depth: int, language: str) -> str:
    parts = [
        f"'{name}' has a measured cyclomatic complexity of {cc} "
        f"(1 base decision path + {cc - 1} branching points) and spans {length} lines."
    ]
    if depth >= 4:
        parts.append(f"Nesting reaches {depth} levels deep, which makes control flow hard to follow.")
    if cc >= SEVERITY_THRESHOLDS["High"]:
        parts.append("Complexity this high is strongly associated with hidden defects and hard-to-maintain code.")
    elif cc >= SEVERITY_THRESHOLDS["Medium"]:
        parts.append("Complexity at this level warrants review: each branch doubles the number of paths to test.")
    return " ".join(parts)


def _suggestion(name: str, cc: int, depth: int) -> str:
    if depth >= 4:
        return (
            f"Reduce nesting in '{name}' with early returns/guard clauses and extract "
            "the inner logic into focused helper functions."
        )
    return (
        f"Split '{name}' into smaller single-purpose functions, replacing branch "
        "chains with lookup tables or polymorphism where appropriate."
    )


def analyze_files(files: list[dict], max_findings: int = MAX_FINDINGS) -> dict:
    """Analyze real fetched source files.

    files: [{path, content, lines}]
    Returns {"findings": [...], "files_analyzed": n, "languages": {...},
             "summary": {...}, "skipped_files": [...]}
    """
    all_results: list[dict] = []
    skipped: list[dict] = []
    languages: dict[str, int] = {"Python": 0, "JavaScript": 0, "TypeScript": 0}
    files_analyzed = 0

    for f in files:
        path = f["path"]
        content = f.get("content", "")
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        language = None
        if ext == "py":
            language = "Python"
        elif ext in ("js", "jsx", "mjs", "cjs"):
            language = "JavaScript"
        elif ext in ("ts", "tsx"):
            language = "TypeScript"
        if language is None:
            continue

        files_analyzed += 1
        languages[language] = languages.get(language, 0) + 1

        if language == "Python":
            results = analyze_python(content)
            if results == [] and content.strip() and not content.strip().startswith(("#", '"""', "'''")):
                # Only record a skip when the file has code-like content
                pass
        else:
            results = analyze_js(content, language)

        for r in results:
            r["file"] = path
        all_results.extend(results)

    # Report only functions at/above the low threshold
    reportable = [r for r in all_results if r["cyclomatic_complexity"] >= LOW_REPORT_THRESHOLD]
    for r in reportable:
        r["severity"] = severity_for(r["cyclomatic_complexity"], r["length_lines"])
        r["explanation"] = _explanation(
            r["name"], r["cyclomatic_complexity"], r["length_lines"], r["nesting_depth"] or 0, r["language"]
        )
        r["suggestion"] = _suggestion(r["name"], r["cyclomatic_complexity"], r["nesting_depth"] or 0)

    reportable.sort(key=lambda r: (-r["cyclomatic_complexity"], -r["length_lines"]))
    capped = len(reportable) > max_findings
    reportable = reportable[:max_findings]

    high = sum(1 for r in reportable if r["severity"] == "High")
    medium = sum(1 for r in reportable if r["severity"] == "Medium")

    return {
        "findings": reportable,
        "files_analyzed": files_analyzed,
        "languages": languages,
        "summary": {
            "total_functions_measured": len(all_results),
            "reported": len(reportable),
            "high": high,
            "medium": medium,
            "average_complexity": (
                round(sum(r["cyclomatic_complexity"] for r in all_results) / len(all_results), 2)
                if all_results else 0.0
            ),
            "capped": capped,
        },
    }
