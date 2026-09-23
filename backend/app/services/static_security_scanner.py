"""
Static Security Scanner — pattern-based vulnerability detection.

Runs deterministic regex scanners against source code to detect real
vulnerabilities WITHOUT relying on an LLM. Each scanner returns findings
with line numbers, severity, vulnerability type, CWE references, and
secure-code fix snippets.

Supported detection types:
  • Hardcoded Secrets / API Keys / JWT Secrets / Passwords
  • SQL Injection
  • Cross-Site Scripting (XSS)
  • Cross-Site Request Forgery (CSRF)
  • Command Injection
  • Unsafe eval / exec / Function() constructors
  • Missing Authorization
  • Insecure Storage

Usage:
    from app.services.static_security_scanner import StaticSecurityAnalyzer
    findings = StaticSecurityAnalyzer.scan(code, filename="app.py", language="python")
"""

from __future__ import annotations

import re
import os
from typing import Any


def _build_finding(
    *,
    line: int,
    severity: str,
    issue: str,
    suggestion: str,
    category: str = "Security",
    vulnerability_type: str = "Other",
    cwe: str | None = None,
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
        "vulnerability_type": vulnerability_type,
        "cwe": cwe or "",
        "suggestion": suggestion,
        "why_it_matters": why_it_matters or issue,
        "risk_level": risk_level or severity,
        "before_code": before_code or "",
        "after_code": after_code or "",
        "file": file,
        "source": "static_analysis",
    }


# ── Scanner registry ─────────────────────────────────────────────────────────

class StaticSecurityAnalyzer:
    """Run all static scanners against *code* and return a list of findings."""

    SCANNERS: list[dict] = []  # populated via @scanner decorator

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
            except Exception as e:
                import logging
                logging.getLogger("static_security").debug(f"Scanner {scanner.get('name','')} failed: {e}")
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
    def register(cls, name: str, severity: str, vulnerability_type: str, cwe: str):
        """Decorator: register a scanner function."""
        def decorator(fn):
            cls.SCANNERS.append({
                "name": name,
                "severity": severity,
                "vulnerability_type": vulnerability_type,
                "cwe": cwe,
                "fn": fn,
            })
            return fn
        return decorator


# ═════════════════════════════════════════════════════════════════════════════
# 1. HARDCODED SECRETS — API keys, JWT secrets, passwords, tokens
# ═════════════════════════════════════════════════════════════════════════════

# Patterns for variable assignments that look like hardcoded credentials.
# These fire when the value is NOT wrapped in os.getenv / os.environ / config().

_HARDCODED_SECRET_PATTERNS: list[tuple[re.Pattern, str, str, str, str]] = [
    # API keys
    (re.compile(
        r'(?:api[_-]?key|apikey|api[_-]?secret|api[_-]?token)'
        r'\s*[=:]\s*[\'"]([A-Za-z0-9_\-\.\+/=]{16,})[\'"]',
        re.IGNORECASE,
    ), "Critical", "Hardcoded API Key", "CWE-798", "Use a secrets manager or environment variable. Never commit API keys to source."),
    # JWT secrets
    (re.compile(
        r'(?:jwt[_-]?secret|jwt[_-]?key|token[_-]?secret|auth[_-]?secret)'
        r'\s*[=:]\s*[\'"]([A-Za-z0-9_\-\.\+/=]{10,})[\'"]',
        re.IGNORECASE,
    ), "Critical", "Hardcoded JWT / Auth Secret", "CWE-798", "Store JWT secrets in environment variables or a vault. Rotate immediately if exposed."),
    # Passwords
    (re.compile(
        r'(?:password|pwd|passwd|db[_-]?password|root[_-]?password)'
        r'\s*[=:]\s*[\'"]([^\'"]{6,})[\'"]',
        re.IGNORECASE,
    ), "Critical", "Hardcoded Password", "CWE-798", "Use a secrets manager or prompt for password at runtime."),
    # Generic secret / token
    (re.compile(
        r'(?:secret|secret[_-]?key|private[_-]?key|access[_-]?token|auth[_-]?token)'
        r'\s*[=:]\s*[\'"]([A-Za-z0-9_\-\.\+/=]{16,})[\'"]',
        re.IGNORECASE,
    ), "High", "Hardcoded Secret / Token", "CWE-798", "Move secrets to environment variables or a secrets vault."),
    # Connection strings with embedded credentials
    (re.compile(
        r'(?:postgresql|mysql|mongodb|redis|sqlite)'
        r'://[^\s\'"]*:[^\s\'"]*@',
        re.IGNORECASE,
    ), "High", "Connection String with Embedded Credentials", "CWE-798", "Use environment variables for credentials in connection strings."),
]

# Lines that indicate legitimate usage (env vars, settings, config)
_LEGITIMATE_CONTEXT = re.compile(
    r'(?:os\.getenv|os\.environ|config\s*\(|settings\.|environ\.get|'
    r'\.env|load_dotenv|get_config|secret_manager|vault|KeyVault|'
    r'SETTINGS\.|@dataclass|pydantic\.BaseModel|BaseSettings|'
    r'getenv\s*\(|environ\.get)',
    re.IGNORECASE,
)


@StaticSecurityAnalyzer.register(
    "hardcoded_secrets", "Critical", "Hardcoded Secret", "CWE-798"
)
def _scan_hardcoded_secrets(
    code: str, filename: str, language: str
) -> list[dict]:
    findings = []
    lines = code.splitlines()

    for pattern, severity, issue, cwe, suggestion in _HARDCODED_SECRET_PATTERNS:
        for m in pattern.finditer(code):
            # Compute line number
            line_no = code[: m.start()].count("\n") + 1

            # Get the surrounding context (this line and previous)
            context_start = max(0, line_no - 3)
            context_lines = lines[context_start: line_no]

            # Skip if the assignment is inside an os.getenv / os.environ call
            # or is legitimately reading from config/settings
            context_text = "\n".join(context_lines)
            if _LEGITIMATE_CONTEXT.search(context_text):
                continue

            # Skip if the value looks like a placeholder or example
            val = m.group(1) if m.lastindex and m.groups() else m.group(0)
            if re.match(
                r'^(your[_\-]?(key|secret|token|password)|placeholder|'
                r'changeme|example|demo|test|dummy|none|xxxx)',
                val,
                re.IGNORECASE,
            ):
                continue

            # Capture the insecure line as before_code
            before_line = lines[line_no - 1].strip() if line_no <= len(lines) else ""

            # Build the after_code suggestion
            var_match = re.match(r'\s*(\w+)\s*[=:]', before_line)
            var_name = var_match.group(1) if var_match else "SECRET"
            env_var_name = var_name.upper().replace("-", "_").replace(" ", "_")
            after_code = f'{var_name} = os.getenv("{env_var_name}")'

            findings.append(_build_finding(
                line=line_no,
                severity=severity,
                issue=issue,
                vulnerability_type="Hardcoded Secret",
                cwe=cwe,
                suggestion=suggestion,
                before_code=before_line,
                after_code=after_code,
                why_it_matters=(
                    f"Hardcoded {issue.lower()} in source code. If the repository "
                    f"is compromised, this credential is immediately exposed. "
                    f"Attackers scan public repos for these patterns."
                ),
                risk_level=severity,
            ))

    return findings


# ═════════════════════════════════════════════════════════════════════════════
# 2. SQL INJECTION — String concatenation / f-strings in SQL queries
# ═════════════════════════════════════════════════════════════════════════════

# Detect unsafe SQL construction — f-strings, % formatting, .format(), +
# inside SQL-related function calls (execute, query, raw, cursor)

_SQL_KEYWORDS = re.compile(
    r'(?:execute|executemany|query|raw_query|cursor|session\.execute|'
    r'db\.execute|conn\.execute|run\s*query|text\s*\(|SQL\s*\))',
    re.IGNORECASE,
)

_SQL_CONCAT_PATTERNS = [
    re.compile(r"""['"]\s*\+\s*(?!\s*['"])"""),  # '...' + variable
    re.compile(r"""f['"][^'"]*\{[^}]+\}"""),    # f"...{variable}"
    re.compile(r"""['"]\s*%\s*[srd]"""),         # '... %s' % var
    re.compile(r"""['"]\s*\.format\s*\("""),     # '...'.format(
]

# Parameterized query examples for after_code fix
_PARAMETERIZED_EXAMPLES: dict[str, str] = {
    "python": """# Use parameterized queries:
cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))""",
    "javascript": """// Use parameterized queries:
db.query('SELECT * FROM users WHERE id = $1', [userId])""",
    "typescript": """// Use parameterized queries:
db.query('SELECT * FROM users WHERE id = $1', [userId])""",
    "java": """// Use PreparedStatement:
PreparedStatement stmt = conn.prepareStatement("SELECT * FROM users WHERE id = ?");
stmt.setString(1, userId);""",
    "csharp": """// Use parameterized queries:
using var cmd = new SqlCommand("SELECT * FROM users WHERE id = @id", conn);
cmd.Parameters.AddWithValue("@id", userId);""",
    "go": """// Use parameterized queries:
db.Query("SELECT * FROM users WHERE id = $1", userId)""",
}


@StaticSecurityAnalyzer.register(
    "sql_injection", "Critical", "SQL Injection", "CWE-89"
)
def _scan_sql_injection(
    code: str, filename: str, language: str
) -> list[dict]:
    findings = []
    lines = code.splitlines()

    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()
        # Skip comments and non-executable lines
        if stripped.startswith(("#", "//", "--", "*", "/*")):
            continue

        # Check if line contains SQL keyword AND string concatenation
        if not _SQL_KEYWORDS.search(stripped):
            continue

        for pattern in _SQL_CONCAT_PATTERNS:
            if pattern.search(stripped):
                fix_example = _PARAMETERIZED_EXAMPLES.get(
                    language.lower(), _PARAMETERIZED_EXAMPLES["python"]
                )
                findings.append(_build_finding(
                    line=line_no,
                    severity="Critical",
                    issue="SQL Injection — String Concatenation in Query",
                    vulnerability_type="SQL Injection",
                    cwe="CWE-89",
                    suggestion="Use parameterized queries / prepared statements instead of string concatenation.",
                    before_code=stripped,
                    after_code=fix_example,
                    why_it_matters=(
                        "String concatenation in SQL queries allows an attacker to "
                        "inject arbitrary SQL commands by supplying crafted input. "
                        "This can lead to data exfiltration, deletion, or privilege escalation."
                    ),
                    risk_level="Critical",
                ))
                break  # one finding per concatenated line

    return findings


# ═════════════════════════════════════════════════════════════════════════════
# 3. CROSS-SITE SCRIPTING (XSS) — innerHTML, dangerouslySetInnerHTML, etc.
# ═════════════════════════════════════════════════════════════════════════════

_XSS_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r'\.innerHTML\s*=', re.IGNORECASE), "innerHTML Assignment", "Use textContent or innerText instead of innerHTML to prevent XSS."),
    (re.compile(r'dangerouslySetInnerHTML', re.IGNORECASE), "dangerouslySetInnerHTML", "Avoid dangerouslySetInnerHTML in React. Use safe rendering or sanitize with DOMPurify."),
    (re.compile(r'document\.write\s*\(', re.IGNORECASE), "document.write()", "Avoid document.write(). Use DOM manipulation APIs instead."),
    (re.compile(r'\.insertAdjacentHTML\s*\(', re.IGNORECASE), "insertAdjacentHTML", "Use insertAdjacentText or safe DOM methods instead."),
    (re.compile(r'v-html\s*=', re.IGNORECASE), "v-html (Vue)", "Use v-text or {{ }} interpolation instead of v-html to prevent XSS."),
    (re.compile(r'\{{\{.*\}\}\}', re.IGNORECASE), "Unescaped Template Variable", "Use escaped template output (e.g., {{ }} in Angular, {{ }} in Django auto-escapes)."),
]


@StaticSecurityAnalyzer.register("xss", "High", "XSS", "CWE-79")
def _scan_xss(code: str, filename: str, language: str) -> list[dict]:
    findings = []
    lines = code.splitlines()

    for pattern, issue, suggestion in _XSS_PATTERNS:
        for m in pattern.finditer(code):
            line_no = code[: m.start()].count("\n") + 1
            before_line = lines[line_no - 1].strip() if line_no <= len(lines) else ""

            # Determine fix example
            if "innerHTML" in before_line:
                var_match = re.search(r'([\w.]+)\s*\.innerHTML\s*=', before_line)
                var_name = var_match.group(1) if var_match else "element"
                after_code = f"{var_name}.textContent = safeValue;  // or use DOMPurify.sanitize()"
            elif "dangerouslySetInnerHTML" in before_line:
                after_code = "// Use a sanitizer: <div>{DOMPurify.sanitize(userContent)}</div>"
            else:
                after_code = "// Sanitize user input before inserting into the DOM"

            findings.append(_build_finding(
                line=line_no,
                severity="High",
                issue=f"Cross-Site Scripting (XSS) — {issue}",
                vulnerability_type="XSS",
                cwe="CWE-79",
                suggestion=suggestion,
                before_code=before_line,
                after_code=after_code,
                why_it_matters=(
                    "XSS allows attackers to inject malicious scripts into web pages "
                    "viewed by other users. This can lead to session hijacking, "
                    "credential theft, and defacement."
                ),
                risk_level="High",
            ))

    return findings


# ═════════════════════════════════════════════════════════════════════════════
# 4. CSRF — Missing CSRF protection
# ═════════════════════════════════════════════════════════════════════════════

_CSRF_PATTERNS = [
    # Django
    re.compile(r'@csrf_exempt', re.IGNORECASE),
    re.compile(r'csrf_exempt\s*='),
    # Flask-WTF / general
    re.compile(r'@csrf\.exempt', re.IGNORECASE),
    # ASP.NET
    re.compile(r'\[IgnoreAntiforgeryToken\]', re.IGNORECASE),
]


@StaticSecurityAnalyzer.register("csrf", "High", "CSRF", "CWE-352")
def _scan_csrf(code: str, filename: str, language: str) -> list[dict]:
    findings = []
    lines = code.splitlines()

    # Pattern 1: explicit csrf_exempt decorators
    for pattern in _CSRF_PATTERNS[:4]:
        for m in pattern.finditer(code):
            line_no = code[: m.start()].count("\n") + 1
            before_line = lines[line_no - 1].strip() if line_no <= len(lines) else ""
            findings.append(_build_finding(
                line=line_no,
                severity="High",
                issue="CSRF Protection Disabled",
                vulnerability_type="CSRF",
                cwe="CWE-352",
                suggestion="Do not disable CSRF protection on production endpoints. Use CSRF tokens for state-changing requests.",
                before_code=before_line,
                after_code="# Remove @csrf_exempt and ensure CSRF middleware is active",
                why_it_matters=(
                    "Disabling CSRF protection allows attackers to forge requests "
                    "on behalf of authenticated users, potentially leading to "
                    "unauthorized state changes."
                ),
                risk_level="High",
            ))

    return findings


# ═════════════════════════════════════════════════════════════════════════════
# 5. COMMAND INJECTION — os.system, subprocess with shell=True, etc.
# ═════════════════════════════════════════════════════════════════════════════

_COMMAND_INJECTION_PATTERNS: list[tuple[re.Pattern, str, str, str]] = [
    (re.compile(r'os\.system\s*\(', re.IGNORECASE), "os.system() call", "Critical",
     "Use subprocess.run() with a list of arguments instead of shell strings."),
    (re.compile(r'subprocess\..*shell\s*=\s*True', re.IGNORECASE), "subprocess with shell=True", "Critical",
     "Avoid shell=True. Pass command arguments as a list."),
    (re.compile(r'subprocess\.Popen\s*\(', re.IGNORECASE), "subprocess.Popen() (check shell)", "High",
     "Ensure shell=False (default). Pass args as a list, not a string."),
    (re.compile(r'child_process\.exec\s*\(', re.IGNORECASE), "child_process.exec()", "Critical",
     "Use child_process.execFile() or spawn() with argument array."),
    (re.compile(r'child_process\.execSync\s*\(', re.IGNORECASE), "child_process.execSync()", "Critical",
     "Use execFileSync() or spawnSync() with argument array."),
    (re.compile(r'Runtime\.getRuntime\(\)\.exec\s*\(', re.IGNORECASE), "Runtime.exec()", "Critical",
     "Use ProcessBuilder with separate command and arguments."),
    (re.compile(r'(?<!os\.)(?<!subprocess\.)(?<!child_process\.)(?<!Runtime\.getRuntime\(\)\.)\bexec\s*\(', re.IGNORECASE), "exec() in PHP/Node (or generic)", "High",
     "Avoid exec() with user input. Use safer alternatives."),
    (re.compile(r'\bsystem\s*\(', re.IGNORECASE), "system() in PHP/C", "Critical",
     "Avoid system(). Use safer process execution APIs."),
    (re.compile(r'\bpassthru\s*\(', re.IGNORECASE), "passthru() in PHP", "Critical",
     "Avoid passthru(). Use safer process execution APIs."),
    (re.compile(r'`[^`]*\$\{?[^`]+`', re.IGNORECASE), "Shell command substitution with user input", "Critical",
     "Avoid command substitution with unsanitized input."),
]


@StaticSecurityAnalyzer.register(
    "command_injection", "Critical", "Command Injection", "CWE-78"
)
def _scan_command_injection(
    code: str, filename: str, language: str
) -> list[dict]:
    findings = []
    lines = code.splitlines()

    for pattern, issue, severity, suggestion in _COMMAND_INJECTION_PATTERNS:
        for m in pattern.finditer(code):
            line_no = code[: m.start()].count("\n") + 1
            before_line = lines[line_no - 1].strip() if line_no <= len(lines) else ""

            fix_line = before_line
            if "shell=True" in before_line:
                fix_line = before_line.replace("shell=True", "shell=False")
                # Also convert string to list
                fix_line = re.sub(
                    r'"([^"]*)"', r'["\1".split()]', fix_line
                ) if '"' in fix_line else fix_line

            findings.append(_build_finding(
                line=line_no,
                severity=severity,
                issue=f"Command Injection — {issue}",
                vulnerability_type="Command Injection",
                cwe="CWE-78",
                suggestion=suggestion,
                before_code=before_line,
                after_code=fix_line,
                why_it_matters=(
                    "Command injection allows an attacker to execute arbitrary "
                    "system commands on the server, leading to full compromise."
                ),
                risk_level=severity,
            ))

    return findings


# ═════════════════════════════════════════════════════════════════════════════
# 6. UNSAFE EVAL — eval(), exec(), Function() constructor
# ═════════════════════════════════════════════════════════════════════════════

_UNSAFE_EVAL_PATTERNS: list[tuple[re.Pattern, str, str, str]] = [
    (re.compile(r'\beval\s*\(', re.IGNORECASE), "eval()", "Critical",
     "Avoid eval() entirely. Use safer alternatives like JSON.parse() or ast.literal_eval()."),
    (re.compile(r'\bexec\s*\(', re.IGNORECASE), "exec() (Python/JS)", "Critical",
     "Avoid exec(). Use safer alternatives or restrict input."),
    (re.compile(r'new\s+Function\s*\(', re.IGNORECASE), "new Function() constructor", "Critical",
     "Avoid the Function constructor. Use safer alternatives."),
    (re.compile(r'setTimeout\s*\(["\']', re.IGNORECASE), "setTimeout with string argument", "High",
     "Pass a function reference instead of a string to setTimeout."),
    (re.compile(r'setInterval\s*\(["\']', re.IGNORECASE), "setInterval with string argument", "High",
     "Pass a function reference instead of a string to setInterval."),
]


@StaticSecurityAnalyzer.register(
    "unsafe_eval", "Critical", "Unsafe Eval", "CWE-95"
)
def _scan_unsafe_eval(code: str, filename: str, language: str) -> list[dict]:
    findings = []
    lines = code.splitlines()

    for pattern, issue, severity, suggestion in _UNSAFE_EVAL_PATTERNS:
        for m in pattern.finditer(code):
            line_no = code[: m.start()].count("\n") + 1
            before_line = lines[line_no - 1].strip() if line_no <= len(lines) else ""

            # For Python eval/exec, suggest ast.literal_eval
            after_code = before_line
            if "eval(" in before_line and language.lower() in ("python", ""):
                after_code = before_line.replace("eval(", "ast.literal_eval(")
                after_code = "import ast\n" + after_code
            elif "exec(" in before_line:
                after_code = f"# WARNING: exec() usage — consider refactoring\n{before_line}"

            findings.append(_build_finding(
                line=line_no,
                severity=severity,
                issue=f"Unsafe Eval / Dynamic Code Execution — {issue}",
                vulnerability_type="Unsafe Eval",
                cwe="CWE-95",
                suggestion=suggestion,
                before_code=before_line,
                after_code=after_code,
                why_it_matters=(
                    "Dynamic code execution functions (eval, exec, Function) "
                    "can execute arbitrary code supplied by an attacker, "
                    "leading to full remote code execution."
                ),
                risk_level=severity,
            ))

    return findings


# ═════════════════════════════════════════════════════════════════════════════
# 7. MISSING AUTHORIZATION — Routes/endpoints without auth guards
# ═════════════════════════════════════════════════════════════════════════════

# Detect FastAPI/Flask route decorators that don't have an auth dependency
_AUTH_DECORATOR_PATTERNS = [
    re.compile(r'@router\.(?:get|post|put|delete|patch)\b', re.IGNORECASE),
    re.compile(r'@app\.(?:get|post|put|delete|patch|route)\b', re.IGNORECASE),
    re.compile(r'@(?:blueprint|bp)\.(?:get|post|put|delete|patch|route)\b', re.IGNORECASE),
]

# Function decorators / parameters that indicate auth protection
_AUTH_INDICATORS = re.compile(
    r'(?:login_required|auth_required|authenticated|get_current_user|'
    r'@roles_allowed|@permission_required|@jwt_required|'
    r'oauth2_scheme|Depends\(get_current_user|'
    r'\[Authorize\]|\[Authenticate\]|AuthorizeAttribute|'
    r'EnsureAuthenticated|requireAuth|isAuthenticated)',
    re.IGNORECASE,
)


@StaticSecurityAnalyzer.register(
    "missing_authorization", "High", "Missing Authorization", "CWE-862"
)
def _scan_missing_authorization(
    code: str, filename: str, language: str
) -> list[dict]:
    findings = []
    lines = code.splitlines()

    for pattern in _AUTH_DECORATOR_PATTERNS:
        for m in pattern.finditer(code):
            line_no = code[: m.start()].count("\n") + 1
            idx = line_no - 1  # 0-based

            # Look at the next few lines for auth indicators
            surrounding = "\n".join(
                lines[max(0, idx - 2): min(len(lines), idx + 5)]
            )

            # Check if the function definition or its decorators have auth
            if _AUTH_INDICATORS.search(surrounding):
                continue

            # Check if it's a static file route or health check (acceptable without auth)
            route_line = lines[idx].strip() if idx < len(lines) else ""
            if any(
                kw in route_line.lower()
                for kw in ["health", "ping", "static", "favicon", "webhook"]
            ):
                continue

            before_line = lines[idx].strip() if idx < len(lines) else ""
            findings.append(_build_finding(
                line=line_no,
                severity="High",
                issue="Missing Authorization Guard on API Endpoint",
                vulnerability_type="Missing Authorization",
                cwe="CWE-862",
                suggestion="Add authentication/authorization check to this endpoint (e.g., Depends(get_current_user) in FastAPI).",
                before_code=before_line,
                after_code=(
                    "# Add auth dependency, e.g. in FastAPI:\n"
                    f"{before_line}\n"
                    "async def endpoint(current_user: User = Depends(get_current_user)):"
                ),
                why_it_matters=(
                    "Endpoints without authorization checks expose sensitive "
                    "operations to unauthenticated or unauthorized users, "
                    "potentially leading to data breaches."
                ),
                risk_level="High",
            ))

    return findings


# ═════════════════════════════════════════════════════════════════════════════
# 8. INSECURE STORAGE — localStorage/sessionStorage for sensitive data, etc.
# ═════════════════════════════════════════════════════════════════════════════

_INSECURE_STORAGE_PATTERNS: list[tuple[re.Pattern, str, str, str]] = [
    (re.compile(
        r'(?:localStorage|sessionStorage)\s*\.\s*setItem\s*\(', re.IGNORECASE
    ), "Sensitive data in Web Storage (localStorage/sessionStorage)",
     "High", "Do not store JWT tokens, passwords, or sensitive data in localStorage. Use httpOnly cookies instead."),
    (re.compile(
        r'(?:localStorage|sessionStorage)\s*\.\s*getItem\s*\(', re.IGNORECASE
    ), "Reading sensitive data from Web Storage", "Medium",
     "Ensure you are not reading tokens or secrets from localStorage. Prefer httpOnly cookies."),
    (re.compile(r'IndexedDB.*(?:password|secret|token|key)', re.IGNORECASE),
     "Sensitive data in IndexedDB", "Medium",
     "Ensure sensitive data stored in IndexedDB is properly encrypted."),
    (re.compile(r'cookie.*(?:password|secret|token|jwt)(?!.*httponly)', re.IGNORECASE),
     "Cookie without httpOnly/Secure flags for sensitive data", "High",
     "Set httpOnly, Secure, and SameSite=Strict flags on cookies containing sensitive data."),
    (re.compile(r'File\.write.*(?:password|secret|key|token)', re.IGNORECASE),
     "Writing secrets to a file", "Critical",
     "Never write secrets, passwords, or tokens to files in plaintext."),
    (re.compile(r'(?:pickle\.dump|pickle\.load|joblib\.dump|joblib\.load)', re.IGNORECASE),
     "Insecure deserialization (pickle/joblib)", "Critical",
     "Pickle can execute arbitrary code during deserialization. Use safer formats like JSON or schema-validated serialization."),
    (re.compile(r'yaml\.load\s*\(', re.IGNORECASE),
     "Unsafe YAML deserialization", "Critical",
     "Use yaml.safe_load() instead of yaml.load() to prevent code execution during deserialization."),
]


@StaticSecurityAnalyzer.register(
    "insecure_storage", "High", "Insecure Storage", "CWE-922"
)
def _scan_insecure_storage(
    code: str, filename: str, language: str
) -> list[dict]:
    findings = []
    lines = code.splitlines()

    for pattern, issue, severity, suggestion in _INSECURE_STORAGE_PATTERNS:
        for m in pattern.finditer(code):
            line_no = code[: m.start()].count("\n") + 1
            before_line = lines[line_no - 1].strip() if line_no <= len(lines) else ""

            # For localStorage, suggest httpOnly cookie
            after_code = before_line
            if "localStorage" in before_line:
                after_code = "// Use httpOnly cookies instead of localStorage for sensitive data\n"
                after_code += "// document.cookie = `token=${encodeURIComponent(token)}; path=/; Secure; HttpOnly; SameSite=Strict`;"
            elif "pickle" in before_line:
                after_code = before_line.replace("pickle.load", "json.load").replace("pickle.dump", "json.dump")
            elif "yaml.load(" in before_line:
                after_code = before_line.replace("yaml.load(", "yaml.safe_load(")

            findings.append(_build_finding(
                line=line_no,
                severity=severity,
                issue=f"Insecure Storage / Deserialization — {issue}",
                vulnerability_type="Insecure Storage",
                cwe="CWE-922" if "deserialization" not in issue.lower() else "CWE-502",
                suggestion=suggestion,
                before_code=before_line,
                after_code=after_code,
                why_it_matters=(
                    "Insecure storage of sensitive data or unsafe deserialization "
                    "can lead to data exposure, remote code execution, or "
                    "full application compromise."
                ),
                risk_level=severity,
            ))

    return findings


# ═════════════════════════════════════════════════════════════════════════════
# 9. JWT MISCONFIGURATION — weak algorithm, missing expiration, hardcoded secret
# ═════════════════════════════════════════════════════════════════════════════

_JWT_MISCONFIG_PATTERNS: list[tuple[re.Pattern, str, str, str, str]] = [
    # Weak algorithm (none, HS256)
    (re.compile(
        r'(?:algorithm|alg)\s*[=:]\s*[\'"]*(?:none|HS256|HS128)[\'"]*',
        re.IGNORECASE,
    ), "Critical", "Weak JWT Algorithm", "CWE-327",
     "Use RS256 or ES256. Never use 'none' algorithm."),
    # Hardcoded JWT secret in code
    (re.compile(
        r'(?:jwt[_-]?secret|jwt[_-]?key|token[_-]?secret|signing[_-]?key)'
        r'\s*[=:]\s*[\'"]([^\'"]{16,})[\'"]',
        re.IGNORECASE,
    ), "Critical", "Hardcoded JWT Secret", "CWE-798",
     "Never hardcode JWT signing secrets. Use environment variables or a vault."),
    # JWT without expiration check
    (re.compile(
        r'jwt\.(?:decode|verify|verifyToken)\s*\([^)]*\)',
        re.IGNORECASE,
    ), "High", "JWT Decode Without Explicit Expiration Check", "CWE-613",
     "Ensure JWT expiration (exp claim) is validated during token verification."),
    # Missing algorithm restriction in decode
    (re.compile(
        r'jwt\.decode\s*\([^)]*verify\s*=\s*False',
        re.IGNORECASE,
    ), "Critical", "JWT Decode With Verification Disabled", "CWE-327",
     "Never disable JWT signature verification. This allows token forgery."),
]


@StaticSecurityAnalyzer.register(
    "jwt_misconfiguration", "High", "JWT Misconfiguration", "CWE-613"
)
def _scan_jwt_misconfiguration(
    code: str, filename: str, language: str
) -> list[dict]:
    findings = []
    lines = code.splitlines()

    for pattern, severity, issue, cwe, suggestion in _JWT_MISCONFIG_PATTERNS:
        for m in pattern.finditer(code):
            line_no = code[: m.start()].count("\n") + 1
            before_line = lines[line_no - 1].strip() if line_no <= len(lines) else ""

            after_code = before_line
            if "none" in before_line.lower() and "algorithm" in before_line.lower():
                after_code = before_line.replace("none", "RS256")
            elif "verify\s*=\s*False" in before_line.lower():
                after_code = before_line.replace("verify=False", "verify=True").replace("verify = False", "verify = True")

            findings.append(_build_finding(
                line=line_no,
                severity=severity,
                issue=f"JWT Misconfiguration — {issue}",
                vulnerability_type="JWT Misconfiguration",
                cwe=cwe,
                suggestion=suggestion,
                before_code=before_line,
                after_code=after_code,
                why_it_matters=(
                    "JWT misconfigurations can allow token forgery, unauthorized access, "
                    "and privilege escalation."
                ),
                risk_level=severity,
            ))

    return findings


# ═════════════════════════════════════════════════════════════════════════════
# 10. SSRF — Server-Side Request Forgery
# ═════════════════════════════════════════════════════════════════════════════

_SSRF_PATTERNS: list[tuple[re.Pattern, str, str, str]] = [
    (re.compile(r'requests\.(?:get|post|put|delete|patch|head|options)\s*\([^)]*url\s*=', re.IGNORECASE),
     "requests call with user-controlled URL", "High",
     "Validate and sanitize user-supplied URLs. Restrict to allow-listed domains and prevent access to internal services."),
    (re.compile(r'urllib\.request\.urlopen\s*\(', re.IGNORECASE),
     "urllib request with potential user input", "High",
     "Avoid passing user input directly to urlopen. Validate the URL against an allow-list first."),
    (re.compile(r'httpx\.(?:get|post|put|delete|patch|head|options)\s*\([^)]*url\s*=', re.IGNORECASE),
     "httpx call with user-controlled URL", "High",
     "Validate and restrict user-supplied URLs to prevent SSRF attacks against internal services."),
    (re.compile(r'aiohttp\.ClientSession.*\.(?:get|post|put|delete)\s*\(', re.IGNORECASE),
     "aiohttp request with potential user input", "High",
     "Ensure user-supplied URLs are validated against an allow-list before making async HTTP requests."),
    (re.compile(r'axios\.(?:get|post|put|delete|patch)\s*\([^)]*url', re.IGNORECASE),
     "axios call with user-controlled URL", "High",
     "Validate user-supplied URLs against an allow-list to prevent SSRF."),
    (re.compile(r'fetch\s*\([^)]*url', re.IGNORECASE),
     "fetch call with potential user-controlled URL", "Medium",
     "Ensure user-supplied URLs passed to fetch() are validated against an allow-list."),
    (re.compile(r'curl\s+[^-]', re.IGNORECASE),
     "shell curl command with potential user input", "High",
     "Avoid constructing curl commands with user input. Use a proper HTTP client library with URL validation."),
    (re.compile(r'guzzle|HttpClient|HttpClient\.(?:get|post|send)', re.IGNORECASE),
     "HTTP client call with potential user input", "Medium",
     "Validate URLs against an allow-list before making requests."),
]


@StaticSecurityAnalyzer.register(
    "ssrf", "High", "Server-Side Request Forgery", "CWE-918"
)
def _scan_ssrf(code: str, filename: str, language: str) -> list[dict]:
    findings = []
    lines = code.splitlines()

    for pattern, issue, severity, suggestion in _SSRF_PATTERNS:
        for m in pattern.finditer(code):
            line_no = code[:m.start()].count("\n") + 1
            before_line = lines[line_no - 1].strip() if line_no <= len(lines) else ""

            findings.append(_build_finding(
                line=line_no,
                severity=severity,
                issue=f"Server-Side Request Forgery (SSRF) — {issue}",
                vulnerability_type="SSRF",
                cwe="CWE-918",
                suggestion=suggestion,
                before_code=before_line,
                after_code=(
                    "# Validate URL against allow-list before making requests:\n"
                    "# ALLOWED_DOMAINS = {'api.example.com', 'internal.service.com'}\n"
                    "# parsed = urlparse(user_url)\n"
                    "# if parsed.netloc not in ALLOWED_DOMAINS:\n"
                    "#     raise ValueError('URL not allowed')"
                ),
                why_it_matters=(
                    "Server-Side Request Forgery (SSRF) allows an attacker to make requests "
                    "from the server to internal services (e.g., 169.254.169.254 for cloud metadata, "
                    "internal databases, or other services). This can lead to data exfiltration, "
                    "remote code execution, or privilege escalation."
                ),
                risk_level=severity,
            ))

    return findings


# ═════════════════════════════════════════════════════════════════════════════
# 11. PATH TRAVERSAL — Unsanitized file path usage
# ═════════════════════════════════════════════════════════════════════════════

_PATH_TRAVERSAL_PATTERNS: list[tuple[re.Pattern, str, str, str]] = [
    (re.compile(r'open\s*\([^)]*\+[^)]*', re.IGNORECASE),
     "open() with concatenated path", "High",
     "Use os.path.abspath() and validate the resolved path is within an allowed directory."),
    (re.compile(r'(?:os\.path\.join|pathlib\.Path)\([^)]*user|input|request|param|query[^)]*\)', re.IGNORECASE),
     "File path construction with user input", "High",
     "Sanitize user input used in file paths. Validate that the resolved path stays within an allowed base directory."),
    (re.compile(r'send_file\s*\([^)]*user|input|request|param', re.IGNORECASE),
     "send_file() with user-controlled path", "Critical",
     "Do NOT pass user input directly to send_file(). Use a file ID lookup table instead."),
    (re.compile(r'StaticHandler|static_file|file_path.*user|input|request', re.IGNORECASE),
     "Static file handler with user-controlled path", "High",
     "Use a mapping dictionary to translate user-supplied identifiers to file paths."),
    (re.compile(r'zipfile|tarfile|shutil\.unpack|extractall', re.IGNORECASE),
     "Archive extraction with potential path traversal", "High",
     "Validate member paths in archives to prevent zip slip / path traversal during extraction."),
    (re.compile(r'os\.(?:remove|unlink|rename|chmod|chown)\s*\(', re.IGNORECASE),
     "File operation with potential user-controlled path", "High",
     "Validate the resolved absolute path is within an allowed directory before performing operations."),
    (re.compile(r'(?:File|StreamWriter|StreamReader)\s*\([^)]*\+', re.IGNORECASE),
     "File I/O with concatenated path", "High",
     "Resolve and validate the normalized path before opening files with user-influenced paths."),
]


@StaticSecurityAnalyzer.register(
    "path_traversal", "High", "Path Traversal", "CWE-22"
)
def _scan_path_traversal(code: str, filename: str, language: str) -> list[dict]:
    findings = []
    lines = code.splitlines()

    for pattern, issue, severity, suggestion in _PATH_TRAVERSAL_PATTERNS:
        for m in pattern.finditer(code):
            line_no = code[:m.start()].count("\n") + 1
            before_line = lines[line_no - 1].strip() if line_no <= len(lines) else ""

            findings.append(_build_finding(
                line=line_no,
                severity=severity,
                issue=f"Path Traversal — {issue}",
                vulnerability_type="Path Traversal",
                cwe="CWE-22",
                suggestion=suggestion,
                before_code=before_line,
                after_code=(
                    "# Validate the resolved path:\n"
                    "# import os\n"
                    "# BASE_DIR = '/app/data/'\n"
                    "# safe_path = os.path.normpath(os.path.join(BASE_DIR, user_input))\n"
                    "# if not safe_path.startswith(os.path.abspath(BASE_DIR)):\n"
                    "#     raise ValueError('Path traversal detected')"
                ),
                why_it_matters=(
                    "Path traversal allows an attacker to read or write files outside the "
                    "intended directory, potentially exposing sensitive system files, "
                    "source code, or configuration data."
                ),
                risk_level=severity,
            ))

    return findings


# ═════════════════════════════════════════════════════════════════════════════
# 12. UNSAFE DESERIALIZATION — Pickle, YAML, Marshal, etc.
# ═════════════════════════════════════════════════════════════════════════════

_UNSAFE_DESERIALIZATION_PATTERNS: list[tuple[re.Pattern, str, str, str]] = [
    (re.compile(r'pickle\.loads?\s*\(', re.IGNORECASE),
     "pickle.load/loads()", "Critical",
     "Avoid pickle for untrusted data. Use JSON or schema-validated formats instead."),
    (re.compile(r'marshal\.loads?\s*\(', re.IGNORECASE),
     "marshal.load/loads()", "Critical",
     "Marshal can execute arbitrary code during deserialization. Use safer formats."),
    (re.compile(r'shelve\.open\s*\(', re.IGNORECASE),
     "shelve.open()", "High",
     "Shelve uses pickle internally and is unsafe for untrusted data."),
    (re.compile(r'yaml\.load\s*\([^)]*Loader\s*=\s*yaml\.(?:FullLoader|UnsafeLoader|CLoader)', re.IGNORECASE),
     "Unsafe YAML loader", "Critical",
     "Use yaml.safe_load() to prevent arbitrary code execution during YAML parsing."),
    (re.compile(r'XMLParser|lxml\(|xml\.etree|ElementTree|etree\.\(|parse\s*\(', re.IGNORECASE),
     "XML parser with potential XXE risk", "High",
     "Disable external entity resolution in XML parsers to prevent XXE attacks. Use defusedxml."),
    (re.compile(r'jsonpickle\.(?:loads?|decode)', re.IGNORECASE),
     "jsonpickle deserialization", "High",
     "jsonpickle can deserialize arbitrary Python objects. Use plain json.loads() instead."),
    (re.compile(r'numpy\.load\s*\(', re.IGNORECASE),
     "numpy.load() with potential pickle", "High",
     "numpy.load() can load pickled objects. Set allow_pickle=False if possible."),
    (re.compile(r'joblib\.load\s*\(', re.IGNORECASE),
     "joblib.load() deserialization", "High",
     "joblib can execute arbitrary code during deserialization. Use safer formats."),
    (re.compile(r'ObjectInputStream|readObject\s*\(', re.IGNORECASE),
     "Java ObjectInputStream deserialization", "Critical",
     "Java deserialization of untrusted data can lead to RCE. Use a safe serialization framework."),
    (re.compile(r'Unmarshal\s*\(|json\.Unmarshal|encoding/json\.Unmarshal', re.IGNORECASE),
     "Go deserialization with potential type confusion", "Medium",
     "Ensure strict type checking after deserialization to prevent type confusion attacks."),
]


@StaticSecurityAnalyzer.register(
    "unsafe_deserialization", "Critical", "Unsafe Deserialization", "CWE-502"
)
def _scan_unsafe_deserialization(code: str, filename: str, language: str) -> list[dict]:
    findings = []
    lines = code.splitlines()

    for pattern, issue, severity, suggestion in _UNSAFE_DESERIALIZATION_PATTERNS:
        for m in pattern.finditer(code):
            line_no = code[:m.start()].count("\n") + 1
            before_line = lines[line_no - 1].strip() if line_no <= len(lines) else ""

            # Provide language-specific after_code
            after_code = before_line
            lower_line = before_line.lower()
            if "pickle" in lower_line:
                after_code = before_line.replace("pickle.load", "json.load").replace("pickle.loads", "json.loads")
            elif "yaml.load(" in lower_line:
                after_code = before_line.replace("yaml.load(", "yaml.safe_load(")
            elif "xml" in lower_line or "etree" in lower_line:
                after_code = f"# Use defusedxml to prevent XXE:\n# from defusedxml import ElementTree\n# tree = ElementTree.parse(trusted_file)"
            elif "joblib" in lower_line:
                after_code = before_line.replace("joblib.load", "json.load")

            findings.append(_build_finding(
                line=line_no,
                severity=severity,
                issue=f"Unsafe Deserialization — {issue}",
                vulnerability_type="Unsafe Deserialization",
                cwe="CWE-502",
                suggestion=suggestion,
                before_code=before_line,
                after_code=after_code,
                why_it_matters=(
                    "Unsafe deserialization allows an attacker to inject arbitrary objects "
                    "that can execute code during the deserialization process, leading to "
                    "remote code execution (RCE), denial of service, or data tampering."
                ),
                risk_level=severity,
            ))

    return findings
