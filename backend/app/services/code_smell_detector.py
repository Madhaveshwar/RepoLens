from typing import Any
import re
from langsmith import traceable
from app.utils.prompts import SYSTEM_SMELL_PROMPT, build_smell_prompt
from app.services.security_scanner import parse_json_from_llm
from app.utils.logger import get_logger
from app.services.llm_client import GROQ_FALLBACK_MODEL

logger = get_logger("code_smell_detector")

MODEL_NAME = "openai/gpt-oss-120b"
CONFIDENCE_THRESHOLD = 0.75

# ── Only these smell types are valid ───────────────────────────
VALID_SMELL_TYPES = {
    "Long Function", "Long Method",
    "Long Class",
    "Duplicate Code",
    "High Complexity", "Excessive Complexity",
    "Unused Variable",
    "Unused Import",
    "Dead Code",
    "Magic Number", "Magic String",
    "Deep Nesting", "Excessive Nesting",
    "God Object",
    "Large File",
    "Large Parameter List", "Too Many Parameters",
    "Long Parameter List",
}

# ── Fake smell patterns to reject ──────────────────────────────
_FAKE_SMELL_ISSUES = [
    "long import list", "long list of imports", "too many imports",
    "missing error handling", "poor naming", "bad naming",
    "comment smell", "too many comments", "missing comments",
    "line too long", "long line", "long lines",
    "inconsistent indentation", "trailing whitespace",
    "missing docstring", "missing type hint", "missing type annotation",
    "unnecessary import",
]

# ── Code patterns that make a smell likely fake ────────────────
_FAKE_SMELL_CODE_PATTERNS = [
    (r"^import\s+|^from\s+", ["long import", "too many import"]),
    (r"load_dotenv\(\)", ["missing error handling", "error handling"]),
    (r"#\s*TODO|#\s*FIXME", ["comment", "todo"]),
]

def compute_smell_confidence(item: dict, code_lines: list[str]) -> float:
    """Compute confidence score 0.0–1.0 for a code smell finding."""
    issue_lower = (item.get("issue") or "").lower()
    suggestion_lower = (item.get("suggestion") or "").lower()
    combined_text = issue_lower + " " + suggestion_lower

    line_val = int(item.get("line", 1)) if str(item.get("line")).isdigit() else 1
    line_idx = line_val - 1
    target_line = code_lines[line_idx].strip() if 0 <= line_idx < len(code_lines) else ""
    before_code = (item.get("before_code") or "").lower()

    # ── Check for fake smell keywords ──
    if any(kw in combined_text for kw in _FAKE_SMELL_ISSUES):
        return 0.0

    # ── Check code patterns that indicate fake smells ──
    for pattern, trigger_keywords in _FAKE_SMELL_CODE_PATTERNS:
        if re.search(pattern, target_line, re.IGNORECASE) or re.search(pattern, before_code, re.IGNORECASE):
            if any(kw in combined_text for kw in trigger_keywords):
                return 0.0

    # ── Check against valid smell types ──
    type_match = any(vt.lower() in combined_text for vt in VALID_SMELL_TYPES)
    if not type_match:
        return 0.3  # Not a recognized smell type

    # ── Severity-based confidence ──
    severity = item.get("severity", "Low")
    severity_score = {"Critical": 0.90, "High": 0.85, "Medium": 0.75, "Low": 0.55, "Info": 0.30}
    base_conf = severity_score.get(severity, 0.50)

    # ── Penalize vague issues ──
    if len(issue_lower) < 20:
        base_conf -= 0.15
    if not item.get("suggestion") or len(suggestion_lower) < 30:
        base_conf -= 0.10

    return max(0.0, min(1.0, base_conf))


@traceable(name="Code Smell Detection")
def detect_code_smells(
    client: Any,
    filename: str,
    code: str,
    patch: str,
    language: str,
    model_name: str = MODEL_NAME,
    temperature: float = 0.2,
) -> list[dict[str, object]]:
    logger.info(f"Triggered code smell detection for file: {filename} ({language})")
    prompt = build_smell_prompt(filename, code, patch, language)
    active_model = MODEL_NAME
    try:
        logger.info(f"Sending code smell analysis request with model={active_model}")
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_SMELL_PROMPT},
                {"role": "user", "content": prompt}
            ],
            model=active_model,
            temperature=temperature,
        )
        result_text = chat_completion.choices[0].message.content
        logger.info("Retrieved code smell scan completion from LLM API.")
    except Exception as e:
        logger.warning(f"LLM query failed for code smell scan using {active_model}: {e}")
        try:
            logger.info(f"Attempting fallback code smell query using model={GROQ_FALLBACK_MODEL}")
            chat_completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": SYSTEM_SMELL_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                model=GROQ_FALLBACK_MODEL,
                temperature=temperature,
            )
            result_text = chat_completion.choices[0].message.content
            logger.info("Successfully retrieved fallback code smell scan completion.")
        except Exception as fallback_e:
            logger.error("Fallback code smell query failed.", exc_info=True)
            from app.services.reviewer import handle_groq_error
            raise handle_groq_error(fallback_e)

    findings = parse_json_from_llm(result_text)
    validated_findings = []
    code_lines = code.splitlines()
    rejected_count = 0
    for item in findings:
        if isinstance(item, dict):
            # ── Compute confidence score ──
            confidence = compute_smell_confidence(item, code_lines)

            if confidence < CONFIDENCE_THRESHOLD:
                rejected_count += 1
                logger.info(
                    f"Rejected code smell (confidence={confidence:.2f}): "
                    f"{item.get('issue', '')[:60]}"
                )
                continue

            validated_findings.append({
                "file": item.get("file", filename),
                "line": int(item.get("line", 1)) if str(item.get("line")).isdigit() else 1,
                "severity": item.get("severity", "Low"),
                "category": "Code Smell",
                "issue": item.get("issue", "Code quality smell detected"),
                "why_it_matters": item.get("why_it_matters", "No explanation provided."),
                "risk_level": item.get("risk_level", item.get("severity", "Low")),
                "suggestion": item.get("suggestion", "Please refactor this code to clean it up."),
                "before_code": item.get("before_code", ""),
                "after_code": item.get("after_code", ""),
            })
    logger.info(
        f"Completed code smell detection for {filename}. "
        f"Accepted: {len(validated_findings)}, Rejected: {rejected_count}"
    )
    return validated_findings
