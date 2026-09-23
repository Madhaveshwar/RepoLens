import json
import re
from typing import Any
from langsmith import traceable
from app.utils.prompts import SYSTEM_SECURITY_PROMPT, build_security_prompt
from app.utils.logger import get_logger
from app.services.static_security_scanner import StaticSecurityAnalyzer
from app.services.llm_client import GROQ_FALLBACK_MODEL, is_model_not_found_error

logger = get_logger("security_scanner")

MODEL_NAME = "openai/gpt-oss-120b"

CONFIDENCE_THRESHOLD = 0.75

# Valid security categories
# NOTE: "Security" is the top-level category the LLM is instructed to return.
# The subcategories below are available for future prompt refinement.
VALID_CATEGORIES = {
    "Security",  # ← LLM always returns this per SYSTEM_SECURITY_PROMPT
    "Authentication", "Authorization", "Secrets", "Injection",
    "Input Validation", "Dependency Risks", "Cryptography",
    "File Upload", "Session Security", "API Security"
}

def parse_json_from_llm(content: str) -> list[dict]:
    if not content:
        return []
    content = content.strip()
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
    if json_match:
        content = json_match.group(1).strip()
    try:
        data = json.loads(content)
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            return [data]
    except json.JSONDecodeError:
        array_match = re.search(r"\[\s*\{[\s\S]*\}\s*\]", content)
        if array_match:
            try:
                data = json.loads(array_match.group(0))
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass
        dict_match = re.search(r"\{\s*\"file\"[\s\S]*\}", content)
        if dict_match:
            try:
                data = json.loads(dict_match.group(0))
                return [data]
            except json.JSONDecodeError:
                pass
    return []

def is_potential_secret_default(line: str) -> bool:
    match = re.search(r",\s*(['\"])(.*?)\1\s*\)", line)
    if match:
        fallback_val = match.group(2)
        safe_defaults = {
            "dev", "development", "prod", "production", "local", "localhost",
            "test", "testing", "default", "sqlite:///test.db", "postgresql://",
            "mysql://", "mongodb://", "redis://", "0.0.0.0", "127.0.0.1", "", "none"
        }
        if fallback_val.lower() in safe_defaults or len(fallback_val) <= 6:
            return False
        if any(kw in fallback_val.lower() for kw in ["key", "secret", "password", "token", "auth", "pwd"]):
            return True
        if re.match(r"^[A-Za-z0-9_\-\+]{8,}$", fallback_val):
            return True
    return False

# ── False positive patterns (issue text to reject) ──────────────
_FP_ISSUE_KEYWORDS = [
    "missing error handling", "missing authentication",
    "hardcoded secret", "hardcoded api key", "hardcoded key",
    "insecure cryptography", "weak cryptography",
]

# ── Code patterns that are NOT security issues ──────────────────
_FP_CODE_PATTERNS = [
    # Config/settings classes
    (r"BaseSettings|pydantic\.BaseModel|@dataclass", ["missing auth", "hardcoded secret", "hardcoded api", "missing auth"]),
    # Settings/SETTINGS/Config object references (e.g. DB_PATH = SETTINGS.db_path) — NOT hardcoded secrets
    (r"\.SETTINGS\.|settings\.|SETTINGS\.|Config\.|config\.", ["hardcoded secret", "hardcoded api", "exposed credential", "credential leak", "hardcoded path", "hardcoded database"]),
    # Environment variable reads
    (r"os\.getenv|os\.environ\.get|os\.environ\[", ["hardcoded secret", "hardcoded api", "exposed credential", "credential leak"]),
    # Import statements
    (r"^import\s+|^from\s+", ["missing auth", "missing auth", "missing authentic", "insecure", "missing input validation"]),
    # load_dotenv
    (r"load_dotenv\(\)", ["missing error handling", "hardcoded", "security risk"]),
    # print/logging statements
    (r"print\(|logger\.|logging\.", ["information disclosure", "information leak", "sensitive data"]),
]

def compute_confidence(item: dict, code_lines: list[str]) -> float:
    """Compute confidence score 0.0–1.0 for a security finding.
    Returns 0.0 for confident false positives, >= 0.75 for valid findings.
    """
    issue_lower = (item.get("issue") or "").lower()
    suggestion_lower = (item.get("suggestion") or "").lower()
    combined_text = issue_lower + " " + suggestion_lower

    line_val = int(item.get("line", 1)) if str(item.get("line")).isdigit() else 1
    line_idx = line_val - 1
    target_line = code_lines[line_idx].strip() if 0 <= line_idx < len(code_lines) else ""
    before_code = (item.get("before_code") or "").lower()

    # ── Check false positive issue keywords ──
    fp_issue_match = any(kw in combined_text for kw in _FP_ISSUE_KEYWORDS)

    # ── Check code patterns that indicate false positive ──
    fp_code_match = False
    for pattern, trigger_keywords in _FP_CODE_PATTERNS:
        if re.search(pattern, target_line, re.IGNORECASE) or re.search(pattern, before_code, re.IGNORECASE):
            # If the issue text matches the trigger keywords, it's a false positive
            if any(kw in combined_text for kw in trigger_keywords):
                fp_code_match = True
                break

    if fp_code_match and fp_issue_match:
        return 0.0
    if fp_code_match:
        return 0.5  # Possibly valid but suspicious

    # ── Category validation ──
    category = item.get("category", "")
    if category and category not in VALID_CATEGORIES:
        return 0.3  # Unrecognized category → low confidence

    # ── Severity-based confidence boost ──
    severity = item.get("severity", "Low")
    severity_score = {"Critical": 0.95, "High": 0.85, "Medium": 0.75, "Low": 0.60, "Info": 0.30}
    base_conf = severity_score.get(severity, 0.50)

    # ── Penalize vague issues ──
    if len(issue_lower) < 20:
        base_conf -= 0.15
    if not item.get("suggestion") or len(suggestion_lower) < 30:
        base_conf -= 0.10

    return max(0.0, min(1.0, base_conf))

@traceable(name="Security Scan")
def scan_security(
    client: Any,
    filename: str,
    code: str,
    patch: str,
    language: str,
    model_name: str = MODEL_NAME,
    temperature: float = 0.2,
) -> list[dict[str, object]]:
    logger.info(f"Triggered security scan for file: {filename} ({language})")
    prompt = build_security_prompt(filename, code, patch, language)
    active_model = MODEL_NAME
    try:
        logger.info(f"Sending security analysis request with model={active_model}")
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_SECURITY_PROMPT},
                {"role": "user", "content": prompt}
            ],
            model=active_model,
            temperature=temperature,
        )
        result_text = chat_completion.choices[0].message.content
        logger.info("Retrieved security scan completion from LLM API.")
    except Exception as e:
        logger.warning(f"LLM query failed for security scan using {active_model}: {e}")
        try:
            logger.info(f"Attempting fallback security query using model={GROQ_FALLBACK_MODEL}")
            chat_completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": SYSTEM_SECURITY_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                model=GROQ_FALLBACK_MODEL,
                temperature=temperature,
            )
            result_text = chat_completion.choices[0].message.content
            logger.info("Successfully retrieved fallback security scan completion.")
        except Exception as fallback_e:
            logger.error("Fallback security query failed.", exc_info=True)
            from app.services.reviewer import handle_groq_error
            raise handle_groq_error(fallback_e)

    findings = parse_json_from_llm(result_text)
    validated_findings = []
    code_lines = code.splitlines()
    rejected_count = 0

    # ── Run Static Security Analyzer (pattern-based, deterministic) ──
    static_findings = StaticSecurityAnalyzer.scan(
        code=code,
        filename=filename,
        language=language,
    )
    logger.info(
        f"Static security analyzer returned {len(static_findings)} findings "
        f"for {filename}"
    )

    for item in findings:
        if isinstance(item, dict):
            line_val = int(item.get("line", 1)) if str(item.get("line")).isdigit() else 1
            line_idx = line_val - 1
            target_line_text = ""
            if 0 <= line_idx < len(code_lines):
                target_line_text = code_lines[line_idx].strip()

            # ── Compute confidence score ──
            confidence = compute_confidence(item, code_lines)

            if confidence < CONFIDENCE_THRESHOLD:
                rejected_count += 1
                logger.info(
                    f"Rejected security finding (confidence={confidence:.2f}): "
                    f"line {line_val} | {item.get('issue', '')[:60]}"
                )
                continue

            # ── Legacy false positive filters (backward compat) ──
            before_code = item.get("before_code", "") or ""
            is_false_positive = False

            if "os.getenv" in target_line_text or "os.environ" in target_line_text or "os.getenv" in before_code or "os.environ" in before_code:
                all_text = target_line_text + " " + before_code
                if not is_potential_secret_default(all_text):
                    is_false_positive = True

            if "BaseSettings" in target_line_text or "BaseSettings" in before_code:
                is_false_positive = True

            if "class" in target_line_text and ("Settings" in target_line_text or "Settings" in before_code):
                is_false_positive = True

            if is_false_positive:
                rejected_count += 1
                logger.info(f"Filtering out false positive security finding on line {line_val}: {target_line_text}")
                continue

            validated_findings.append({
                "file": item.get("file", filename),
                "line": line_val,
                "severity": item.get("severity", "Medium"),
                "category": item.get("category", "Security"),
                "issue": item.get("issue", "Potential vulnerability found"),
                "why_it_matters": item.get("why_it_matters", "No explanation provided."),
                "risk_level": item.get("risk_level", item.get("severity", "Medium")),
                "suggestion": item.get("suggestion", "Please verify and secure this code."),
                "before_code": before_code,
                "after_code": item.get("after_code", ""),
            })
    logger.info(
        f"Completed security scan for {filename}. "
        f"LLM accepted: {len(validated_findings)}, Rejected: {rejected_count}, "
        f"Static findings: {len(static_findings)}"
    )
    # Merge static findings with LLM findings (deduplicate by line + issue)
    merged = list(validated_findings)
    seen_issues = set()
    for f in validated_findings:
        seen_issues.add((f["line"], f["issue"][:80]))
    for sf in static_findings:
        key = (sf["line"], sf["issue"][:80])
        if key not in seen_issues:
            seen_issues.add(key)
            merged.append(sf)
            logger.info(f"Static finding added: L{sf['line']} {sf['issue'][:60]}")
    return merged
