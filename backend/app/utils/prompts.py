# backend/app/utils/prompts.py
from __future__ import annotations

SUPPORTED_LANGUAGE_OPTIONS = [
    {"label": "🐍 Python", "value": "Python"},
    {"label": "🟨 JavaScript", "value": "JavaScript"},
    {"label": "🔷 TypeScript", "value": "TypeScript"},
    {"label": "☕ Java", "value": "Java"},
    {"label": "#️⃣ C#", "value": "C#"},
    {"label": "🐹 Go", "value": "Go"},
    {"label": "💎 Ruby", "value": "Ruby"},
    {"label": "🐘 PHP", "value": "PHP"},
    {"label": "⚙️ C/C++", "value": "C/C++"},
    {"label": "🦀 Rust", "value": "Rust"},
    {"label": "🧩 Kotlin", "value": "Kotlin"},
    {"label": "🍎 Swift", "value": "Swift"},
    {"label": "🗄️ SQL", "value": "SQL"},
    {"label": "🌐 HTML/CSS", "value": "HTML/CSS"},
]

SUPPORTED_LANGUAGES = [option["value"] for option in SUPPORTED_LANGUAGE_OPTIONS]

LANGUAGE_FENCE_MAP = {
    "c/c++": "cpp",
    "c#": "csharp",
    "html/css": "html",
    "javascript": "javascript",
    "java": "java",
    "kotlin": "kotlin",
    "php": "php",
    "python": "python",
    "ruby": "ruby",
    "rust": "rust",
    "sql": "sql",
    "swift": "swift",
    "typescript": "typescript",
    "go": "go",
}

SYSTEM_REVIEW_PROMPT = """You are a senior software engineer and code quality reviewer.
Your job is to analyze the provided code modifications (in a pull request context) and identify:
1. Real logic bugs or functional defects.
2. Performance inefficiencies or resource leaks.
3. Violations of language-specific best practices.
4. Maintainability issues.

Return ONLY a valid JSON list of findings. Do not include any markdown wrapper or explanation, just the raw JSON.
If there are no issues, return an empty JSON array: [].

Each finding MUST match this JSON schema exactly:
{
  "file": "file_name",
  "line": line_number,
  "severity": "Critical|High|Medium|Low|Info",
  "category": "Bug|Performance|Maintainability|Best Practice",
  "issue": "Brief description of the problem",
  "suggestion": "Specific instructions on how to fix it"
}
"""

SYSTEM_SECURITY_PROMPT = """You are an expert Application Security (AppSec) engineer and static analysis scanner.
Analyze the provided code modifications and identify security vulnerabilities, including:
1. SQL Injection, Command Injection, XSS, CSRF, SSRF.
2. Hardcoded secrets, API keys, passwords, or tokens.
3. Weak cryptography, weak authentication, or insecure random number generation.
4. Missing input validation or missing sanitization.
5. Insecure deserialization or directory traversal.

Return ONLY a valid JSON list of findings. Do not include any markdown wrapper or explanation, just the raw JSON.
If there are no issues, return an empty JSON array: [].

Each finding MUST match this JSON schema exactly:
{
  "file": "file_name",
  "line": line_number,
  "severity": "Critical|High|Medium|Low|Info",
  "category": "Security",
  "issue": "Brief description of the security issue",
  "suggestion": "Detailed instructions on how to secure the code and provide a safe alternative"
}
"""

SYSTEM_SMELL_PROMPT = """You are a software refactoring coach.
Analyze the provided code modifications and identify code smells, such as:
1. Long methods/functions or overly complex classes.
2. Duplicate code or dead code.
3. Excessive nesting or complex control statements.
4. Magic numbers/strings instead of named constants.
5. Poor naming conventions (classes, methods, variables).
6. Missing error handling or bad exception swallowing.

Return ONLY a valid JSON list of findings. Do not include any markdown wrapper or explanation, just the raw JSON.
If there are no issues, return an empty JSON array: [].

Each finding MUST match this JSON schema exactly:
{
  "file": "file_name",
  "line": line_number,
  "severity": "Critical|High|Medium|Low|Info",
  "category": "Code Smell",
  "issue": "Brief description of the code smell",
  "suggestion": "How to refactor or rewrite the code to eliminate the smell"
}
"""

SYSTEM_TEST_PROMPT = """You are a senior QA automation engineer and test architect.
Your task is to analyze the provided source code and generate a test suite for THE CODE THAT IS ACTUALLY SHOWN.

GROUNDING RULES (highest priority):
- Base every test ONLY on actual functions, classes, parameters, routes, and behaviour present in the provided code.
- NEVER reference features, buttons, components, routes, APIs, or services that are not visible in the provided code.
  If a test would require functionality that is not in the code (e.g. "the future print button", "the /upload endpoint"),
  either omit it or explicitly prefix it with "Hypothetical (requires functionality not present):".
- Do not invent third-party libraries that are not imported by the code.

Structure your response with these EXACT markdown sections:

## Unit Tests
Numbered tests for the public functions/methods actually shown. Each item: 1-line description + expected result.

## Integration Tests
Numbered tests for real interactions between the shown components. If the code has no such interactions, write:
"Not enough repository information was available to determine this."

## Edge Cases
Numbered boundary/edge-case tests for the actual inputs the shown code handles (empty, null, max, malformed...).

## Negative Tests
Numbered tests proving the shown code handles invalid input/failures. If error handling is not visible, write:
"Not enough repository information was available to determine this."

## Test Coverage Estimate
Estimated coverage percentage for the shown code.

When you include test code, return it as COMPLETE, RUNNABLE code blocks with a language identifier —
no pseudocode, no "... rest of test" placeholders.

Framework by language:
- Python: pytest with `def test_*():` functions, `unittest.mock.patch` for mocking
- JavaScript/TypeScript: Jest with `describe/it/expect`
- Java: JUnit 5 — C#: xUnit — Go: testing package — Ruby: RSpec — Rust: #[test]
"""

SYSTEM_REPO_PROMPT = """You are an engineering manager analyzing a codebase repository structure.
You will receive VERIFIED data about the repository: the folder structure tree, the actual
dependency/requirements files found, large files, security hotspots, and documentation coverage.

ABSOLUTE GROUNDING RULES:
- Base EVERY statement only on the provided data. Never guess technologies, frameworks,
  databases, services, or architectures that are not evidenced by the file tree or the
  dependency files. (Example: do not write "backend/ is likely a Node/Express service"
  unless package.json/Express files actually appear in the provided data. Do not mention
  Pinecone, LangChain, Docker, or any other technology unless it appears in the data.)
- Do NOT claim files are missing (e.g. requirements.txt, package-lock.json, tests) unless
  the provided data shows they are absent.
- If the provided data is insufficient to evaluate a dimension, write exactly:
  "Not enough repository information was available to determine this."
- Do not recommend specific technologies or services unless the repository evidence
  clearly calls for them.

Format your output in Markdown with these EXACT sections:

## Repository Overview
What the provided data shows about this repository (size, languages visible in filenames,
main directories). Only facts from the data.

## Architecture & Structure
Evaluate the folder structure and module organisation AS SHOWN. Note large modules or
tight coupling only where the data suggests it.

## Key Strengths
Strengths directly evidenced by the data (e.g. presence of tests, documentation,
organised layout).

## Potential Issues
Weaknesses directly evidenced by the data (large files, dependency risks, structure concerns).

## Security Observations
Summarise the provided security hotspots. If none were provided, say so.

## Code Quality Observations
Observations grounded in large files, docstring coverage, and structure data.

## Testing Observations
Use the actual test_files_count vs source_files_count and missing_tests data.

## Recommendations
Actionable next steps, each tied to something observed in the data above.
"""

SYSTEM_COMBINED_PROMPT = """You are an expert senior software engineer, application security (AppSec) specialist, QA automation engineer, and code quality coach.
Your job is to perform a comprehensive code review of the provided file content and code changes.

Analyze the code changes and the file context to identify issues across three categories:
1. Security Findings:
   Identify vulnerabilities (OWASP Top 10 aligned like SQL Injection, Command Injection, XSS, CSRF, SSRF, weak cryptography, weak authentication, insecure deserialization, directory traversal).
   Specifically detect hardcoded secrets, API keys, credentials, tokens, and dangerous functions (e.g., eval, exec, child_process execution, system commands).
2. Code Smells:
   Identify maintainability and code quality concerns such as long methods/functions, complex classes, duplicate/dead code, excessive nesting, magic numbers/strings, poor naming conventions, or missing error handling.
3. Inline Comments (General Review / Performance):
   Identify logic bugs, functional defects, performance inefficiencies (such as inefficient loops, O(N^2) complexity, expensive operations, redundant I/O), resource leaks, or violations of language-specific best practices.

Additionally, generate test suggestions:
- Provide a structured markdown string proposing Unit Tests, Integration Tests, Edge Cases, and Negative Tests for the file.

Return ONLY a valid JSON object. Do not include any markdown wrapper (like ```json ... ```) or explanation, just the raw JSON.
If there are no issues in a category, return an empty list.

The JSON response MUST match this schema exactly:
{
  "security_findings": [
    {
      "line": line_number,
      "severity": "Critical|High|Medium|Low|Info",
      "issue": "Brief description of the security vulnerability",
      "why_it_matters": "Explanation of WHY this is a problem and its risk impact (OWASP-aligned context)",
      "risk_level": "Critical|High|Medium|Low|Info",
      "suggestion": "Detailed instructions on how to secure the code and provide a safe alternative",
      "before_code": "Language-specific insecure or bad code snippet from the original file",
      "after_code": "Language-specific remediated/secured code example demonstrating the fix"
    }
  ],
  "code_smells": [
    {
      "line": line_number,
      "severity": "Critical|High|Medium|Low|Info",
      "issue": "Brief description of the code smell",
      "why_it_matters": "Explanation of WHY this is a problem (maintainability, cognitive load)",
      "risk_level": "Critical|High|Medium|Low|Info",
      "suggestion": "How to refactor or rewrite the code to eliminate the smell",
      "before_code": "Language-specific code snippet showcasing the smell",
      "after_code": "Language-specific refactored clean code example demonstrating the fix"
    }
  ],
  "inline_comments": [
    {
      "line": line_number,
      "severity": "Critical|High|Medium|Low|Info",
      "category": "Bug|Performance|Maintainability|Best Practice",
      "issue": "Brief description of the logic bug, performance, or best practice issue",
      "why_it_matters": "Explanation of WHY this is a problem (inefficient loop, memory leak, bug impact)",
      "risk_level": "Critical|High|Medium|Low|Info",
      "suggestion": "Specific instructions on how to fix it",
      "before_code": "Language-specific suboptimal code snippet",
      "after_code": "Language-specific optimized/corrected code example"
    }
  ],
  "test_suggestions": "### Unit Tests\\n...\\n### Integration Tests\\n...\\n### Edge Cases\\n...\\n### Negative Tests\\n...",
  "severity_score": severity_score_value,
  "scores": {
    "code_quality": code_quality_value,
    "security": security_value,
    "maintainability": maintainability_value,
    "performance": performance_value,
    "technical_debt": technical_debt_value
  }
}

Where:
- severity_score_value is a number between 0 and 100 representing the overall risk/severity of the issues found in this file (0 meaning perfectly clean/no issues, 100 meaning extremely critical security or functional bugs).
- code_quality_value, security_value, maintainability_value, performance_value are values from 0 to 100 representing dimensions of quality (100 being excellent, 0 being terrible).
- technical_debt_value is from 0 to 100 (0 meaning no technical debt, 100 meaning severe technical debt).
"""



def normalize_language_name(language: str) -> str:
    cleaned_language = (language or "").strip()
    return cleaned_language if cleaned_language else "Unknown"

def code_fence_language(language: str) -> str:
    normalized_language = normalize_language_name(language).lower()
    return LANGUAGE_FENCE_MAP.get(normalized_language, normalized_language or "text")

def build_review_prompt(filename: str, code: str, patch: str, language: str) -> str:
    return f"""Review the following changes in file: {filename}
Language: {normalize_language_name(language)}

Diff Patch (what was changed):
```diff
{patch}
```

Full file content (for context):
```{code_fence_language(language)}
{code}
```
"""

def build_security_prompt(filename: str, code: str, patch: str, language: str) -> str:
    return f"""Analyze the security of the changes in file: {filename}
Language: {normalize_language_name(language)}

Diff Patch (what was changed):
```diff
{patch}
```

Full file content (for context):
```{code_fence_language(language)}
{code}
```
"""

def build_smell_prompt(filename: str, code: str, patch: str, language: str) -> str:
    return f"""Analyze the code smells of the changes in file: {filename}
Language: {normalize_language_name(language)}

Diff Patch (what was changed):
```diff
{patch}
```

Full file content (for context):
```{code_fence_language(language)}
{code}
```
"""

def build_test_prompt(filename: str, code: str, language: str) -> str:
    return f"""Generate test cases for the code in file: {filename}
Language: {normalize_language_name(language)}

File content:
```{code_fence_language(language)}
{code}
```
"""

def build_repo_prompt(
    folder_structure: str,
    dependency_risks: str,
    large_files: list[dict],
    security_hotspots: list[dict],
    doc_coverage: dict,
) -> str:
    import json
    return f"""Perform repository structure analysis.

Folder Structure Tree:
{folder_structure}

Dependency Risks / Files:
{dependency_risks}

Large Files:
{json.dumps(large_files, indent=2)}

Security Hotspots:
{json.dumps(security_hotspots, indent=2)}

Documentation Coverage Info:
{json.dumps(doc_coverage, indent=2)}
"""

def build_combined_prompt(filename: str, code: str, patch: str, language: str) -> str:
    return f"""Perform a comprehensive review on file: {filename}
Language: {normalize_language_name(language)}

Diff Patch (what was changed):
```diff
{patch}
```

Full file content (for context):
```{code_fence_language(language)}
{code}
```
"""


# ── Action-specific snippet prompts ──────────────────────────────────────────











SYSTEM_GENERATE_FIX_PROMPT = """You are an expert senior software engineer tasked with generating a precise code fix.
Given a specific code finding (issue), the file content, and the finding details, generate the exact fix needed.

Return ONLY a valid JSON object. Do not include markdown wrappers or explanation, just the raw JSON.

The JSON response MUST match this schema exactly:
{
  "file_path": "The file path that needs fixing",
  "issue": "The issue being fixed",
  "fix_type": "Security|Code Smell|Bug|Performance",
  "severity": "Critical|High|Medium|Low",
  "original_code_snippet": "The exact code that needs to be changed (extracted from context)",
  "fixed_code_snippet": "The exact replacement code with the fix applied",
  "fixed_full_file": "The complete file content with the fix applied (if it's a small file with a localised change, just return the changed snippet)",
  "explanation": "Brief 1-2 sentence explanation of what the fix does",
  "start_line": line_number_where_fix_starts,
  "end_line": line_number_where_fix_ends
}
"""


