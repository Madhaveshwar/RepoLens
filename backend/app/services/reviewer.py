import os
import sys
import time
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from groq import Groq
from langsmith import Client, traceable
from app.utils.logger import get_logger

logger = get_logger("groq_service")

from app.utils.prompts import (
    SYSTEM_COMBINED_PROMPT,
    normalize_language_name,
)
from app.utils.validation import is_valid_code, should_skip_file, validate_code_snippet
from app.services.repository_analyzer import analyze_repository
from app.config import settings
from app.services.llm_client import (
    GROQ_FALLBACK_MODEL,
    friendly_llm_error,
    is_model_not_found_error,
)

# Primary review model. For Groq accounts without Enterprise access the
# create_chat_completion() fallback chain resolves an available model.
MODEL_NAME = "openai/gpt-oss-120b"
MODEL_TEMPERATURE = 0.3

class GroqAPIError(Exception):
    pass

def handle_groq_error(exc: Exception, provider: str = "groq") -> Exception:
    """Convert a raw provider exception into a friendly, user-facing message."""
    return GroqAPIError(friendly_llm_error(provider, exc))

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".reviewer_cache.json")

def get_file_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_cache(cache: dict):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"Failed to save cache: {e}")

def parse_combined_json_from_llm(content: str) -> dict:
    if not content:
        return {}
    content = content.strip()
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
    if json_match:
        content = json_match.group(1).strip()
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        object_match = re.search(r"\{\s*\"[^\"]+\"\s*:[\s\S]*\}", content)
        if object_match:
            try:
                data = json.loads(object_match.group(0))
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass
    return {}

def update_findings_file(findings: list, filename: str) -> list:
    updated = []
    for item in findings:
        if isinstance(item, dict):
            new_item = dict(item)
            new_item["file"] = filename
            updated.append(new_item)
    return updated

def validate_finding_evidence(finding: dict, code_lines: list[str]) -> bool:
    """Validate that an LLM finding has real evidence in the source code.
    
    Returns True if the finding passes evidence validation (is likely real).
    Returns False if the finding appears to be hallucinated or fabricated.
    
    Uses lenient heuristics — accepts findings unless clearly fabricated.
    """
    line_val = int(finding.get("line", 0)) if str(finding.get("line")).isdigit() else 0
    before_code = (finding.get("before_code") or "").strip()
    issue = (finding.get("issue") or "").lower()

    # Check 1: Line number must be valid
    if line_val < 1 or line_val > len(code_lines):
        logger.info(f"Evidence validation rejected: line {line_val} out of range (file has {len(code_lines)} lines)")
        return False

    actual_line = code_lines[line_val - 1].strip()
    
    # Fuzzy match: normalize whitespace and compare lowercased
    before_norm = " ".join(before_code.lower().split())
    actual_norm = " ".join(actual_line.lower().split())
    
    # If before_code exists and doesn't match at all, check deeper
    if before_code:
        # Accept if normalized strings overlap
        if before_norm in actual_norm or actual_norm in before_norm:
            return True
        
        # Accept if the issue description keywords appear in the actual line
        issue_keywords = [w for w in issue.split() if len(w) > 3]
        if issue_keywords:
            has_keyword = any(kw in actual_norm for kw in issue_keywords)
            if has_keyword:
                return True
        
        # Only reject if we're confident it's a hallucination:
        # before_code is set, doesn't match, AND line looks completely unrelated
        # Check if the actual line is a comment, blank, or import (unlikely finding target)
        if actual_line.startswith(("#", "//", "/*", "*", "import ", "from ", "package ")) or not actual_line:
            logger.info(f"Evidence validation rejected: line {line_val} looks unrelated to finding '{issue[:50]}'")
            return False
        
        # Lenient default: accept findings for code lines even if before_code doesn't match exactly
        # The LLM may have formatted the before_code differently
        return True

    # No before_code provided — still accept if line is valid and not clearly unrelated
    issue_keywords = [w for w in issue.split() if len(w) > 3]
    if issue_keywords:
        actual_lower = actual_line.lower()
        has_keyword = any(kw in actual_lower for kw in issue_keywords)
        if has_keyword:
            return True
    
    # Lenient: accept findings even without before_code if the line is code (not comment/blank)
    if not actual_line.startswith(("#", "//", "/*", "*")) and actual_line.strip():
        return True
    
    return False


def apply_static_scanners(filename: str, code: str, language: str) -> dict[str, list]:
    """Run static security and code smell scanners on source code.
    Returns dict with 'security_findings' and 'code_smells' keys."""
    sec_findings = []
    smell_findings = []

    try:
        from app.services.static_security_scanner import StaticSecurityAnalyzer
        sec_findings = StaticSecurityAnalyzer.scan(code=code, filename=filename, language=language)
        logger.info(f"Static security scanner: {len(sec_findings)} findings for {filename}")
    except Exception as e:
        logger.warning(f"Static security scanner failed for {filename}: {e}")

    try:
        from app.services.static_code_smell_detector import StaticCodeSmellDetector
        smell_findings = StaticCodeSmellDetector.scan(code=code, filename=filename, language=language)
        logger.info(f"Static code smell detector: {len(smell_findings)} findings for {filename}")
    except Exception as e:
        logger.warning(f"Static code smell detector failed for {filename}: {e}")

    return {
        "security_findings": sec_findings,
        "code_smells": smell_findings,
    }

SYSTEM_MULTI_FILE_PROMPT = """You are an expert senior software engineer, application security (AppSec) specialist, QA automation engineer, and code quality coach.
Your job is to perform a comprehensive code review of multiple source files and (optionally) generate a repository-level qualitative engineering report.

CRITICAL EVIDENCE RULES — YOU MUST FOLLOW THESE:
1. The `before_code` field MUST contain the EXACT source code from the file at the reported line number. Copy it character-for-character. Do NOT paraphrase, summarize, or fabricate code.
2. The `line` field MUST be the exact line number where the issue occurs in the provided file content.
3. If you cannot find a real issue at a specific line, do NOT report a finding for that line. Only report findings where you can point to concrete evidence in the source code.
4. Do NOT report generic/template findings like 'Hardcoded secrets' on lines that contain os.getenv(), load_dotenv(), or configuration classes.
5. Do NOT report 'Insecure deserialization' for json.loads() — that is safe. Only report for pickle.loads(), yaml.load(), etc.
6. Do NOT report 'Magic numbers' for list comprehensions, variable references, or named constants.
7. Do NOT report 'Importing unnecessary modules' unless the import is clearly never used anywhere in the file.
8. Do NOT report 'Complex class' for simple exception classes or data containers.
9. Do NOT report 'Duplicate code' without verifying the same code block appears twice.
10. Only report issues you are CERTAIN about. If unsure, return an empty list for that category.

For each file, you must identify:
1. Security Findings:
   Identify vulnerabilities (OWASP Top 10 aligned like SQL Injection, Command Injection, XSS, CSRF, SSRF, weak cryptography, weak authentication, insecure deserialization, directory traversal).
   Specifically detect hardcoded secrets, API keys, credentials, tokens, and dangerous functions (e.g., eval, exec, child_process execution, system commands).
2. Code Smells:
   Identify maintainability and code quality concerns such as long methods/functions, complex classes, duplicate/dead code, excessive nesting, magic numbers/strings, poor naming conventions, or missing error handling.
3. Inline Comments (General Review / Performance):
   Identify logic bugs, functional defects, performance inefficiencies (such as inefficient loops, O(N^2) complexity, expensive operations, redundant I/O), resource leaks, or violations of language-specific best practices.
4. Test Suggestions:
   Proposing Unit Tests, Integration Tests, Edge Cases, and Negative Tests for the file.
5. Severity Score:
   A number between 0 and 100 representing the overall risk/severity of the issues found in this file (0 meaning perfectly clean/no issues, 100 meaning extremely critical security or functional bugs).
6. Quality Scores:
   Scores out of 100 representing dimensions of code quality, security, maintainability, performance, and technical debt.

If requested, you must also generate:
- Repository Qualitative Report:
  An overall qualitative engineering report based on the repository folder structure, dependency risks, large files, security hotspots, and docstring coverage provided.

Return ONLY a valid JSON object. Do not include any markdown wrapper (like ```json ... ```) or explanation, just the raw JSON.

The JSON response MUST match this schema exactly:
{
  "files_reviews": {
    "<filename>": {
      "security_findings": [
        {
          "line": line_number,
          "severity": "Critical|High|Medium|Low|Info",
          "issue": "Brief description of the security vulnerability",
          "why_it_matters": "Explanation of WHY this is a problem and its risk impact (OWASP-aligned context)",
          "risk_level": "Critical|High|Medium|Low|Info",
          "suggestion": "Detailed instructions on how to secure the code and provide a safe alternative",
          "before_code": "EXACT COPY of the source code line from the file at the reported line number",
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
          "before_code": "EXACT COPY of the source code line from the file at the reported line number",
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
          "before_code": "EXACT COPY of the source code line from the file at the reported line number",
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
  },
  "repository_insights": "Qualitative engineering report markdown string (or null if not requested)"
}

Where:
- severity_score_value is a number between 0 and 100 representing the overall risk/severity of the issues found in this file (0 meaning perfectly clean/no issues, 100 meaning extremely critical security or functional bugs).
- code_quality_value, security_value, maintainability_value, performance_value are values from 0 to 100 representing dimensions of quality (100 being excellent, 0 being terrible).
- technical_debt_value is from 0 to 100 (0 meaning no technical debt, 100 meaning severe technical debt).
"""

def build_multi_file_prompt(files_to_review: list[dict], repo_metadata: dict | None = None) -> str:
    prompt_parts = []
    prompt_parts.append("Please perform a review for the following files:")
    for f in files_to_review:
        prompt_parts.append(f"--- File: {f['filename']} ---")
        prompt_parts.append(f"Language: {f['language']}")
        prompt_parts.append("Diff Patch (what was changed):")
        prompt_parts.append("```diff")
        prompt_parts.append(f["patch"])
        prompt_parts.append("```")
        prompt_parts.append("Full file content (truncated, for context):")
        prompt_parts.append("```")
        prompt_parts.append(f["content"])
        prompt_parts.append("```")
        prompt_parts.append("")
    
    if repo_metadata:
        prompt_parts.append("--- Repository Metadata (for Repository Qualitative Report) ---")
        prompt_parts.append(f"Folder Structure:\n{repo_metadata.get('folder_structure')}")
        prompt_parts.append(f"Dependency Risks / Files:\n{repo_metadata.get('dependency_risks')}")
        prompt_parts.append(f"Large Files:\n{json.dumps(repo_metadata.get('large_files'), indent=2)}")
        prompt_parts.append(f"Security Hotspots:\n{json.dumps(repo_metadata.get('security_hotspots'), indent=2)}")
        prompt_parts.append(f"Documentation Coverage Info:\n{json.dumps(repo_metadata.get('doc_coverage'), indent=2)}")
        prompt_parts.append("\nPlease generate the qualitative engineering report under the 'repository_insights' JSON key based on the metadata above.")
    else:
        prompt_parts.append("Do not generate repository qualitative report. Keep 'repository_insights' key as null.")

    return "\n".join(prompt_parts)

def review_files_combined(
    client: Any,
    files_to_review: list[dict],
    repo_metadata: dict | None = None,
    repo_name: str | None = None,
    model_name: str = MODEL_NAME,
    temperature: float = MODEL_TEMPERATURE,
) -> tuple[dict[str, dict], int, str | None, int, int, dict]:
    logger.info(f"Starting combined files review for {len(files_to_review)} files (repo: {repo_name})")
    
    from app.config import settings
    force_groq = settings.FORCE_GROQ_ANALYSIS
    if force_groq:
        logger.info("Cache bypass enabled via FORCE_GROQ_ANALYSIS=true")
        logger.info("Cache bypass enabled")
        
    cache = load_cache()
    files_reviews_map = {}
    uncached_files = []
    
    for f in files_to_review:
        fname = f["filename"]
        content = f["content"]
        if len(content) > 1000:
            content = content[:1000]
        
        content_hash = get_file_hash(content)
        f["hash"] = content_hash
        f["truncated_content"] = content
        
        logger.info(f"Cache key generated for file {fname}: {content_hash}")
        
        if not force_groq and content_hash in cache:
            logger.info(f"Cache lookup result for file {fname}: HIT")
            logger.info(f"Cache HIT for file: {fname}")
            cached_result = cache[content_hash]
            files_reviews_map[fname] = {
                "security_findings": update_findings_file(cached_result.get("security_findings", []), fname),
                "code_smells": update_findings_file(cached_result.get("code_smells", []), fname),
                "inline_comments": update_findings_file(cached_result.get("inline_comments", []), fname),
                "test_suggestions": cached_result.get("test_suggestions", ""),
                "severity_score": cached_result.get("severity_score", 0),
                "scores": cached_result.get("scores", {})
            }
        else:
            if force_groq:
                logger.info(f"Cache lookup result for file {fname}: BYPASS (forced scan)")
                logger.info(f"Cache bypass enabled for file: {fname}")
            else:
                logger.info(f"Cache lookup result for file {fname}: MISS")
                logger.info(f"Cache MISS for file: {fname}")
            uncached_files.append(f)

    scanned_files_hash = hashlib.sha256("".join(sorted(get_file_hash(f["content"][:1000]) for f in files_to_review)).encode()).hexdigest()
    repo_report_key = f"repo_report_{repo_name}_{scanned_files_hash}" if repo_name else None
    if repo_report_key:
        logger.info(f"Cache key generated for repository report: {repo_report_key}")
    
    repo_insights = None
    if not force_groq and repo_report_key and repo_report_key in cache:
        logger.info(f"Cache lookup result for repository report: HIT")
        logger.info(f"Cache HIT for repository report: {repo_report_key}")
        repo_insights = cache[repo_report_key]
    else:
        if repo_report_key:
            if force_groq:
                logger.info(f"Cache lookup result for repository report: BYPASS (forced scan)")
                logger.info(f"Cache bypass enabled for repository report: {repo_report_key}")
            else:
                logger.info(f"Cache lookup result for repository report: MISS")
                logger.info(f"Cache MISS for repository report: {repo_report_key}")
        
    need_repo_insights = (repo_metadata is not None) and (repo_insights is None)
    
    requests_made = 0
    characters_sent = 0
    
    active_model = model_name or MODEL_NAME
    token_stats = {
        "model_name": active_model,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0
    }
    
    if uncached_files or need_repo_insights:
        # 1. Chunking logic
        chunks = []
        current_chunk = []
        current_chunk_chars = 0
        
        for f in uncached_files:
            file_chars = len(f.get("patch", "")) + len(f.get("content", ""))
            # Max 4 files or 15000 characters per chunk
            if (current_chunk and len(current_chunk) >= 4) or (current_chunk_chars + file_chars > 15000):
                chunks.append(current_chunk)
                current_chunk = [f]
                current_chunk_chars = file_chars
            else:
                current_chunk.append(f)
                current_chunk_chars += file_chars
        if current_chunk:
            chunks.append(current_chunk)
            
        if not chunks and need_repo_insights:
            chunks = [[]]
            
        logger.info(f"Diff chunking enabled: Split {len(uncached_files)} files into {len(chunks)} chunk(s) for LLM API.")
        
        total_sec = 0
        total_smells = 0
        
        for chunk_idx, files_chunk in enumerate(chunks):
            # For each chunk, determine if repo insights should be fetched (only on the first chunk)
            chunk_need_insights = need_repo_insights and (chunk_idx == 0)
            prompt = build_multi_file_prompt(files_chunk, repo_metadata if chunk_need_insights else None)
            prompt_len = len(prompt)
            
            logger.info(f"Chunk {chunk_idx+1}/{len(chunks)}: Prompt size={prompt_len} chars, files={len(files_chunk)}")
            
            max_retries = 4
            backoff = 10
            result_text = ""
            
            for attempt in range(max_retries):
                logger.info(f"LLM request start - Chunk {chunk_idx+1}/{len(chunks)}, attempt {attempt+1}/{max_retries} using model={active_model}")
                try:
                    start_time = time.time()
                    chat_completion = client.chat.completions.create(
                        messages=[
                            {"role": "system", "content": SYSTEM_MULTI_FILE_PROMPT},
                            {"role": "user", "content": prompt}
                        ],
                        model=active_model,
                        temperature=temperature,
                    )
                    duration = time.time() - start_time
                    result_text = chat_completion.choices[0].message.content
                    requests_made += 1
                    characters_sent += prompt_len
                    logger.info(f"Groq response received for Chunk {chunk_idx+1}")
                    logger.info(f"Groq request success - Chunk {chunk_idx+1} attempt {attempt+1} succeeded in {duration:.2f}s. Size: {len(result_text)} chars")
                    
                    if hasattr(chat_completion, "usage") and chat_completion.usage:
                        token_stats["prompt_tokens"] += chat_completion.usage.prompt_tokens
                        token_stats["completion_tokens"] += chat_completion.usage.completion_tokens
                        token_stats["total_tokens"] += chat_completion.usage.total_tokens
                    token_stats["model_name"] = active_model
                    break
                except Exception as e:
                    err_msg_lower = str(e).lower()
                    logger.warning(f"LLM request failure - Chunk {chunk_idx+1} attempt {attempt+1} failed: {e}")
                    is_quota_error = "429" in err_msg_lower or "rate_limit" in err_msg_lower or "quota" in err_msg_lower or "limit exceeded" in err_msg_lower
                    if not is_quota_error and is_model_not_found_error(e) and active_model != GROQ_FALLBACK_MODEL:
                        logger.info(f"Model '{active_model}' unavailable. Falling back to {GROQ_FALLBACK_MODEL}.")
                        active_model = GROQ_FALLBACK_MODEL
                        token_stats["model_name"] = active_model
                        continue
                    if is_quota_error and attempt < max_retries - 1:
                        retry_after = 10
                        if hasattr(e, "response") and e.response is not None:
                            headers = getattr(e.response, "headers", {})
                            if "retry-after" in headers:
                                try:
                                    retry_after = int(headers.get("retry-after"))
                                except:
                                    pass
                        wait_time = max(backoff, retry_after)
                        logger.info(f"Quota error (rate limit). Backing off for {wait_time} seconds...")
                        time.sleep(wait_time)
                        backoff *= 2
                    else:
                        logger.error(f"All Groq API retry attempts failed for chunk {chunk_idx+1}.", exc_info=True)
                        raise handle_groq_error(e)
            
            # Parse this chunk's response
            parsed = parse_combined_json_from_llm(result_text)
            if not parsed:
                logger.error(f"Failed to parse a valid JSON structure from LLM response for Chunk {chunk_idx+1}.")
                continue
                
            files_reviews_data = parsed.get("files_reviews", {})
            for f in files_chunk:
                fname = f["filename"]
                fhash = f["hash"]
                
                file_parsed = files_reviews_data.get(fname, {})
                total_sec += len(file_parsed.get("security_findings", []))
                total_smells += len(file_parsed.get("code_smells", []))
                
                cache[fhash] = {
                    "security_findings": file_parsed.get("security_findings", []),
                    "code_smells": file_parsed.get("code_smells", []),
                    "inline_comments": file_parsed.get("inline_comments", []),
                    "test_suggestions": file_parsed.get("test_suggestions", ""),
                    "severity_score": file_parsed.get("severity_score", 0),
                    "scores": file_parsed.get("scores", {})
                }
                
                files_reviews_map[fname] = {
                    "security_findings": update_findings_file(file_parsed.get("security_findings", []), fname),
                    "code_smells": update_findings_file(file_parsed.get("code_smells", []), fname),
                    "inline_comments": update_findings_file(file_parsed.get("inline_comments", []), fname),
                    "test_suggestions": file_parsed.get("test_suggestions", ""),
                    "severity_score": file_parsed.get("severity_score", 0),
                    "scores": file_parsed.get("scores", {})
                }
                
            if chunk_need_insights:
                repo_insights = parsed.get("repository_insights") or ""
                if repo_report_key is not None:
                    cache[repo_report_key] = repo_insights
                    
        logger.info(f"Security findings generated across chunks: {total_sec}")
        logger.info(f"Code smells generated across chunks: {total_smells}")
        save_cache(cache)
        
    cache_hits = len(files_to_review) - len(uncached_files)
    logger.info(f"Combined files review completed. Cache Hits: {cache_hits}/{len(files_to_review)}, Requests Made: {requests_made}")
    return files_reviews_map, cache_hits, repo_insights, requests_made, characters_sent, token_stats

def review_file_combined(
    client: Any,
    filename: str,
    content: str,
    patch: str,
    language: str,
    model_name: str = MODEL_NAME,
    temperature: float = MODEL_TEMPERATURE,
) -> tuple[dict, bool]:
    files_to_review = [{
        "filename": filename,
        "content": content,
        "patch": patch,
        "language": language
    }]
    results_map, was_cached, _, _, _, token_stats = review_files_combined(
        client=client,
        files_to_review=files_to_review,
        repo_metadata=None,
        model_name=model_name,
        temperature=temperature
    )
    return results_map.get(filename, {}), was_cached

def build_groq_client(api_key: str) -> Groq:
    if not api_key:
        logger.error("Failed to build Groq client: api_key is missing.")
        raise RuntimeError("GROQ_API_KEY is not configured.")
    logger.info("Successfully built Groq client.")
    return Groq(api_key=api_key)

def build_langsmith_client() -> Client | None:
    api_key = settings.LANGCHAIN_API_KEY
    if not api_key:
        return None
    return Client(api_key=api_key)

def calculate_fallback_scores(risk_score: int, severity_counts: dict) -> dict[str, int]:
    security_penalty = (
        50 * severity_counts.get("Critical", 0)
        + 30 * severity_counts.get("High", 0)
        + 12 * severity_counts.get("Medium", 0)
        + 2 * severity_counts.get("Low", 0)
    )
    maintainability_penalty = (
        20 * severity_counts.get("Critical", 0)
        + 15 * severity_counts.get("High", 0)
        + 8 * severity_counts.get("Medium", 0)
        + 3 * severity_counts.get("Low", 0)
    )
    performance_penalty = (
        15 * severity_counts.get("Critical", 0)
        + 10 * severity_counts.get("High", 0)
        + 6 * severity_counts.get("Medium", 0)
        + 2 * severity_counts.get("Low", 0)
    )
    
    code_quality = max(0, min(100, 100 - risk_score))
    security = max(0, min(100, 100 - security_penalty))
    maintainability = max(0, min(100, 100 - maintainability_penalty))
    performance = max(0, min(100, 100 - performance_penalty))
    technical_debt = max(0, min(100, risk_score))
    
    return {
        "code_quality": code_quality,
        "security": security,
        "maintainability": maintainability,
        "performance": performance,
        "technical_debt": technical_debt
    }

def resolve_scores(file_scores_list: list[dict], risk_score: int, severity_counts: dict) -> dict[str, int]:
    fallback = calculate_fallback_scores(risk_score, severity_counts)
    if not file_scores_list:
        return fallback
    
    avg_scores = {}
    keys = ["code_quality", "security", "maintainability", "performance", "technical_debt"]
    for k in keys:
        vals = [s.get(k) for s in file_scores_list if isinstance(s, dict) and s.get(k) is not None]
        if vals:
            avg_scores[k] = int(sum(vals) / len(vals))
        else:
            avg_scores[k] = fallback[k]
    return avg_scores

@traceable(name="PR Review Analysis Pipeline", run_type="chain")
def review_pull_request(
    repo_name: str,
    pr_number: int,
    github_service,
    client: Any,
    language_mapping: dict[str, str] | None = None,
    progress_callback: Any = None,
) -> dict[str, object]:
    start_time = time.time()
    if progress_callback:
        progress_callback(10, "cloning", "Fetching pull request info from GitHub...")
    pr_details = github_service.get_pr_details(repo_name, pr_number)
    
    if progress_callback:
        progress_callback(20, "indexing", "Indexing modified pull request files...")
    changed_files = github_service.get_pr_files(repo_name, pr_number)

    all_findings = []
    test_suggestions_by_file = {}
    files_analyzed_log = []
    
    files_to_review = []
    if not language_mapping:
        language_mapping = {}

    total_files = len(changed_files)
    for idx, f in enumerate(changed_files):
        filename = f["filename"]
        patch = f["patch"]
        status = f["status"]
        
        if progress_callback:
            prog = 30 + int((idx / max(1, total_files)) * 40)
            progress_callback(
                prog,
                "scanning",
                f"Fetching & scanning changed file {idx+1}/{total_files}...",
                idx,
                total_files,
                filename
            )
            
        ext = os.path.splitext(filename)[1].lower()

        ext_map = {
            ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript",
            ".ts": "TypeScript", ".tsx": "TypeScript", ".java": "Java",
            ".cs": "C#", ".go": "Go", ".rb": "Ruby", ".php": "PHP",
            ".cpp": "C/C++", ".c": "C/C++", ".h": "C/C++", ".rs": "Rust",
            ".kt": "Kotlin", ".swift": "Swift",
        }
        detected_lang = ext_map.get(ext, "Other")
        file_type = detected_lang
        if ext in [".md", ".txt"]:
            file_type = "Documentation"
        elif ext in [".json", ".yaml", ".yml", ".ini", ".cfg", ".toml", ".xml"]:
            file_type = "Configuration"

        is_source_ext = detected_lang != "Other"

        if should_skip_file(filename) or status == "removed" or not patch:
            files_analyzed_log.append({
                "file": filename, "type": file_type, "status": "Skipped", "findings": 0
            })
            continue

        if not is_source_ext:
            files_analyzed_log.append({
                "file": filename, "type": file_type, "status": "Scanned", "findings": 0
            })
            continue

        content = github_service.get_file_content(repo_name, filename, pr_details["head_sha"])
        if not content or not is_valid_code(content):
            files_analyzed_log.append({
                "file": filename, "type": file_type, "status": "Skipped", "findings": 0
            })
            continue

        if len(content) > 1000:
            content = content[:1000]

        lang = language_mapping.get(filename, detected_lang)
        files_to_review.append({
            "filename": filename, "content": content, "patch": patch, "language": lang
        })

    if progress_callback:
        progress_callback(70, "generating_tests", "Generating test suggestions...", total_files, total_files, "")

    if progress_callback:
        progress_callback(85, "generating_insights", "Generating insights with AI...", total_files, total_files, "")

    files_reviews_map, cache_hits, _, requests_made, characters_sent, token_stats = review_files_combined(
        client=client,
        files_to_review=files_to_review,
        repo_metadata=None,
        repo_name=None,
        model_name=MODEL_NAME
    )

    files_analyzed_count = len(files_to_review)
    cached_results_used = cache_hits
    groq_requests_made = requests_made
    characters_analyzed_count = characters_sent

    for f in changed_files:
        filename = f["filename"]
        patch = f["patch"]
        if filename not in files_reviews_map:
            continue

        res_dict = files_reviews_map[filename]
        modified_lines = github_service.get_modified_lines(patch)

        general_issues = []
        for item in res_dict.get("inline_comments", []):
            if isinstance(item, dict):
                general_issues.append({
                    "file": filename,
                    "line": int(item.get("line", 1)) if str(item.get("line")).isdigit() else 1,
                    "severity": item.get("severity", "Medium"),
                    "category": item.get("category", "Bug"),
                    "issue": item.get("issue", "Quality or logic concern"),
                    "suggestion": item.get("suggestion", "Please verify this code."),
                    "why_it_matters": item.get("why_it_matters", "No explanation provided."),
                    "risk_level": item.get("risk_level", item.get("severity", "Medium")),
                    "before_code": item.get("before_code", ""),
                    "after_code": item.get("after_code", ""),
                })

        security_issues = []
        for item in res_dict.get("security_findings", []):
            if isinstance(item, dict):
                security_issues.append({
                    "file": filename,
                    "line": int(item.get("line", 1)) if str(item.get("line")).isdigit() else 1,
                    "severity": item.get("severity", "Medium"),
                    "category": "Security",
                    "issue": item.get("issue", "Potential vulnerability found"),
                    "suggestion": item.get("suggestion", "Please verify and secure this code."),
                    "why_it_matters": item.get("why_it_matters", "No explanation provided."),
                    "risk_level": item.get("risk_level", item.get("severity", "Medium")),
                    "before_code": item.get("before_code", ""),
                    "after_code": item.get("after_code", ""),
                })

        smell_issues = []
        for item in res_dict.get("code_smells", []):
            if isinstance(item, dict):
                smell_issues.append({
                    "file": filename,
                    "line": int(item.get("line", 1)) if str(item.get("line")).isdigit() else 1,
                    "severity": item.get("severity", "Low"),
                    "category": "Code Smell",
                    "issue": item.get("issue", "Code quality smell detected"),
                    "suggestion": item.get("suggestion", "Please refactor this code to clean it up."),
                    "why_it_matters": item.get("why_it_matters", "No explanation provided."),
                    "risk_level": item.get("risk_level", item.get("severity", "Low")),
                    "before_code": item.get("before_code", ""),
                    "after_code": item.get("after_code", ""),
                })

        combined = general_issues + security_issues + smell_issues
        file_findings = []
        for issue in combined:
            line_num = issue["line"]
            if line_num in modified_lines or not modified_lines:
                file_findings.append(issue)

        all_findings.extend(file_findings)

        ext = os.path.splitext(filename)[1].lower()
        detected_lang = ext_map.get(ext, "Other")
        file_type = detected_lang
        if ext in [".md", ".txt"]:
            file_type = "Documentation"
        elif ext in [".json", ".yaml", ".yml", ".ini", ".cfg", ".toml", ".xml"]:
            file_type = "Configuration"

        files_analyzed_log.append({
            "file": filename, "type": file_type, "status": "Analyzed", "findings": len(file_findings)
        })

        if len(test_suggestions_by_file) < 3 and res_dict.get("test_suggestions"):
            test_suggestions_by_file[filename] = res_dict["test_suggestions"]

    severity_counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0, "Info": 0}
    for f in all_findings:
        sev = f["severity"]
        if sev in severity_counts:
            severity_counts[sev] += 1

    risk_score = min(
        100,
        25 * severity_counts["Critical"]
        + 15 * severity_counts["High"]
        + 6 * severity_counts["Medium"]
        + 1 * severity_counts["Low"]
    )

    inline_comments = []
    for f in all_findings:
        file_patch = next((item["patch"] for item in changed_files if item["filename"] == f["file"]), "")
        body_text = f"File: {f['file']}\nLine: {f['line']}\nIssue: {f['issue']}\nSeverity: {f['severity']}\nRecommendation: {f['suggestion']}"
        inline_comments.append({
            "file": f["file"],
            "line": f["line"],
            "body": body_text,
            "patch": file_patch,
        })

    test_suggestions_md = []
    for fn, tests in test_suggestions_by_file.items():
        test_suggestions_md.append(f"### File: {fn}\n{tests}\n")
    test_suggestions_compiled = "\n".join(test_suggestions_md)

    latency = round(time.time() - start_time, 2)
    estimated_tokens_count = characters_analyzed_count // 4

    file_scores_list = [res_dict.get("scores", {}) for res_dict in files_reviews_map.values() if isinstance(res_dict, dict) and "scores" in res_dict]
    overall_scores = resolve_scores(file_scores_list, risk_score, severity_counts)

    return {
        "repo_name": repo_name,
        "pr_number": pr_number,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "risk_score": risk_score,
        "findings": all_findings,
        "inline_comments": inline_comments,
        "test_suggestions": test_suggestions_compiled,
        "severity_counts": severity_counts,
        "latency_seconds": latency,
        "estimated_token_usage": len(all_findings) * 350 + 500,
        "files_analyzed_log": files_analyzed_log,
        "files_analyzed_count": files_analyzed_count,
        "characters_analyzed_count": characters_analyzed_count,
        "estimated_tokens_count": estimated_tokens_count,
        "groq_requests_made": groq_requests_made,
        "cached_results_used": cached_results_used,
        "scores": overall_scores,
        "token_stats": token_stats,
    }

@traceable(name="Single Code Snippet Scan", run_type="chain")
def review_single_code_snippet(
    code: str,
    language: str,
    client: Any,
) -> dict[str, object]:
    start_time = time.time()
    
    is_valid, validation_msg, detected_lang = validate_code_snippet(code, language)
    
    if not is_valid:
        latency = round(time.time() - start_time, 2)
        return {
            "risk_score": 0,
            "findings": [],
            "inline_comments": [],
            "test_suggestions": "",
            "severity_counts": {"Critical": 0, "High": 0, "Medium": 0, "Low": 0, "Info": 0},
            "latency_seconds": latency,
            "estimated_token_usage": 0,
            "files_analyzed_count": 0,
            "characters_analyzed_count": 0,
            "estimated_tokens_count": 0,
            "groq_requests_made": 0,
            "cached_results_used": 0,
            "scores": {
                "code_quality": 100,
                "security": 100,
                "maintainability": 100,
                "performance": 100,
                "technical_debt": 0
            },
            "is_valid_code": False,
            "detected_language": "Unknown",
            "optimization_required": False,
            "optimized_code": None,
            "validation_message": validation_msg
        }

    truncated_code = code
    if len(truncated_code) > 1000:
        truncated_code = truncated_code[:1000]

    filename = "snippet.py" if detected_lang == "Python" else f"snippet.{detected_lang[:3].lower()}"
    dummy_patch = f"@@ -1,1 +1,{len(truncated_code.splitlines())} @@\n" + "\n".join(f"+{line}" for line in truncated_code.splitlines())

    user_prompt = f"""Review the following code snippet.
Language: {detected_lang}

Code Snippet content:
```{detected_lang.lower()}
{truncated_code}
```
"""

    groq_requests_made = 0
    cached_results_used = 0
    
    content_hash = get_file_hash(truncated_code)
    cache = load_cache()
    
    force_groq = settings.FORCE_GROQ_ANALYSIS
    res_dict = {}
    was_cached = False
    
    if not force_groq and content_hash in cache:
        res_dict = cache[content_hash]
        was_cached = True
        cached_results_used += 1
    else:
        active_model = MODEL_NAME
        result_text = ""
        max_retries = 4
        backoff = 10
        
        for attempt in range(max_retries):
            try:
                chat_completion = client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": SYSTEM_COMBINED_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    model=active_model,
                    temperature=MODEL_TEMPERATURE,
                )
                result_text = chat_completion.choices[0].message.content
                groq_requests_made += 1
                break
            except Exception as e:
                err_msg_lower = str(e).lower()
                is_quota_error = "429" in err_msg_lower or "rate_limit" in err_msg_lower or "quota" in err_msg_lower or "limit exceeded" in err_msg_lower
                if not is_quota_error and is_model_not_found_error(e) and active_model != GROQ_FALLBACK_MODEL:
                    logger.info(f"Model '{active_model}' unavailable. Falling back to {GROQ_FALLBACK_MODEL}.")
                    active_model = GROQ_FALLBACK_MODEL
                    continue
                if is_quota_error and attempt < max_retries - 1:
                    time.sleep(backoff)
                    backoff *= 2
                else:
                    raise handle_groq_error(e)
                    
        res_dict = parse_combined_json_from_llm(result_text)
        if res_dict:
            cache[content_hash] = res_dict
            save_cache(cache)

    general_issues = []
    for item in res_dict.get("inline_comments", []):
        if isinstance(item, dict):
            general_issues.append({
                "file": filename,
                "line": int(item.get("line", 1)) if str(item.get("line")).isdigit() else 1,
                "severity": item.get("severity", "Medium"),
                "category": item.get("category", "Bug"),
                "issue": item.get("issue", "Quality or logic concern"),
                "suggestion": item.get("suggestion", "Please verify this code."),
                "why_it_matters": item.get("why_it_matters", "No explanation provided."),
                "risk_level": item.get("risk_level", item.get("severity", "Medium")),
                "before_code": item.get("before_code", ""),
                "after_code": item.get("after_code", ""),
            })

    security_issues = []
    for item in res_dict.get("security_findings", []):
        if isinstance(item, dict):
            security_issues.append({
                "file": filename,
                "line": int(item.get("line", 1)) if str(item.get("line")).isdigit() else 1,
                "severity": item.get("severity", "Medium"),
                "category": "Security",
                "issue": item.get("issue", "Potential vulnerability found"),
                "suggestion": item.get("suggestion", "Please verify and secure this code."),
                "why_it_matters": item.get("why_it_matters", "No explanation provided."),
                "risk_level": item.get("risk_level", item.get("severity", "Medium")),
                "before_code": item.get("before_code", ""),
                "after_code": item.get("after_code", ""),
            })

    smell_issues = []
    for item in res_dict.get("code_smells", []):
        if isinstance(item, dict):
            smell_issues.append({
                "file": filename,
                "line": int(item.get("line", 1)) if str(item.get("line")).isdigit() else 1,
                "severity": item.get("severity", "Low"),
                "category": "Code Smell",
                "issue": item.get("issue", "Code quality smell detected"),
                "suggestion": item.get("suggestion", "Please refactor this code to clean it up."),
                "why_it_matters": item.get("why_it_matters", "No explanation provided."),
                "risk_level": item.get("risk_level", item.get("severity", "Low")),
                "before_code": item.get("before_code", ""),
                "after_code": item.get("after_code", ""),
            })

    findings = general_issues + security_issues + smell_issues
    severity_counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0, "Info": 0}
    for f in findings:
        sev = f["severity"]
        if sev in severity_counts:
            severity_counts[sev] += 1

    risk_score = min(
        100,
        25 * severity_counts["Critical"]
        + 15 * severity_counts["High"]
        + 6 * severity_counts["Medium"]
        + 1 * severity_counts["Low"]
    )

    tests = res_dict.get("test_suggestions", "Failed to generate test suggestions.")

    inline_comments = []
    for f in findings:
        body_text = f"File: {f['file']}\nLine: {f['line']}\nIssue: {f['issue']}\nSeverity: {f['severity']}\nRecommendation: {f['suggestion']}"
        inline_comments.append({
            "file": f["file"],
            "line": f["line"],
            "body": body_text,
            "patch": dummy_patch,
        })

    latency = round(time.time() - start_time, 2)
    files_analyzed_count = 1
    characters_analyzed_count = 0 if was_cached else len(truncated_code)
    estimated_tokens_count = characters_analyzed_count // 4

    snippet_scores = resolve_scores([res_dict.get("scores", {})], risk_score, severity_counts)
    quality_score = snippet_scores.get("code_quality", 100)
    
    optimization_required = res_dict.get("optimization_required", False)
    optimized_code = res_dict.get("optimized_code", None)
    
    if not optimization_required:
        optimized_code = None

    validation_message = "Code snippet is valid."
    if not findings:
        validation_message = "No issues found."

    return {
        "repo_name": "Local Snippet",
        "pr_number": None,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "risk_score": risk_score,
        "findings": findings,
        "inline_comments": inline_comments,
        "test_suggestions": tests,
        "severity_counts": severity_counts,
        "latency_seconds": latency,
        "estimated_token_usage": len(findings) * 350 + 500,
        "files_analyzed_count": files_analyzed_count,
        "characters_analyzed_count": characters_analyzed_count,
        "estimated_tokens_count": estimated_tokens_count,
        "groq_requests_made": groq_requests_made,
        "cached_results_used": cached_results_used,
        "scores": snippet_scores,
        "is_valid_code": True,
        "detected_language": detected_lang,
        "optimization_required": optimization_required,
        "optimized_code": optimized_code,
        "quality_score": quality_score,
        "validation_message": validation_message
    }

@traceable(name="Full Repository Analysis Pipeline", run_type="chain")
def review_entire_repository(
    repo_name: str,
    github_service,
    client: Any,
    language_mapping: dict[str, str] | None = None,
    progress_callback: Any = None,
) -> dict[str, object]:
    start_time = time.time()
    if progress_callback:
        progress_callback(10, "cloning", "Fetching repository file tree from GitHub...")
    repo = github_service.client.get_repo(repo_name)
    default_branch = repo.default_branch
 
    tree_items = []
    try:
        branch = repo.get_branch(default_branch)
        sha = branch.commit.sha
        git_tree = repo.get_git_tree(sha=sha, recursive=True)
        tree_items = git_tree.tree
    except Exception as exc:
        print(f"Error fetching repo tree: {exc}")
 
    if progress_callback:
        progress_callback(20, "indexing", "Indexing and prioritizing source files...")
        
    source_files_with_sizes = []
    for item in tree_items:
        if item.type == "blob":
            path = item.path
            if should_skip_file(path):
                continue
            is_source = any(
                path.endswith(ext)
                for ext in [
                    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".cs",
                    ".go", ".rb", ".php", ".cpp", ".c", ".rs", ".kt", ".swift"
                ]
            )
            basename = os.path.basename(path).lower()
            is_test = (
                "test" in basename or "spec" in basename
                or path.startswith("tests/") or path.startswith("test/")
            )
            if is_source and not is_test:
                source_files_with_sizes.append((path, item.size or 0))
 
    source_files_with_sizes.sort(key=lambda x: x[1], reverse=True)
    scanned_files = [path for path, size in source_files_with_sizes[:5]]
    source_files = [path for path, size in source_files_with_sizes]
    
    files_to_review = []
    if not language_mapping:
        language_mapping = {}
 
    total_files = len(scanned_files)
    for idx, filename in enumerate(scanned_files):
        if progress_callback:
            prog = 30 + int((idx / max(1, total_files)) * 40)
            progress_callback(
                prog,
                "scanning",
                f"Fetching & scanning repository file {idx+1}/{total_files}...",
                idx,
                total_files,
                filename
            )
            
        content = github_service.get_file_content(repo_name, filename, default_branch)
        if not content or not is_valid_code(content):
            continue
 
        if len(content) > 1000:
            content = content[:1000]
 
        ext = os.path.splitext(filename)[1].lower()
        ext_map = {
            ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript",
            ".ts": "TypeScript", ".tsx": "TypeScript", ".java": "Java",
            ".cs": "C#", ".go": "Go", ".rb": "Ruby", ".php": "PHP",
            ".cpp": "C/C++", ".c": "C/C++", ".h": "C/C++", ".rs": "Rust",
            ".kt": "Kotlin", ".swift": "Swift",
        }
        detected_lang = ext_map.get(ext, "Python")
        lang = language_mapping.get(filename, detected_lang)
 
        dummy_patch = f"@@ -1,1 +1,{len(content.splitlines())} @@\n" + "\n".join(f"+{line}" for line in content.splitlines())
 
        files_to_review.append({
            "filename": filename, "content": content, "patch": dummy_patch, "language": lang
        })
 
    try:
        repo_metadata = analyze_repository(
            client=client,
            github_service=github_service,
            repo_name=repo_name,
            qualitative_report="PENDING"
        )
    except Exception as e:
        raise handle_groq_error(e)
 
    if progress_callback:
        progress_callback(70, "generating_tests", "Generating test suggestions...", total_files, total_files, "")
 
    if progress_callback:
        progress_callback(85, "generating_insights", "Analyzing repository qualitative health report...", total_files, total_files, "")
 
    files_reviews_map, cache_hits, repo_insights, requests_made, characters_sent, token_stats = review_files_combined(
        client=client,
        files_to_review=files_to_review,
        repo_metadata=repo_metadata,
        repo_name=repo_name,
        model_name=MODEL_NAME
    )

    all_findings = []
    test_suggestions_by_file = {}
    files_analyzed_count = len(files_to_review)
    cached_results_used = cache_hits
    groq_requests_made = requests_made
    characters_analyzed_count = characters_sent

    for filename, res_dict in files_reviews_map.items():
        # ── Get source lines for evidence validation ──
        source_content = ""
        for f in files_to_review:
            if f["filename"] == filename:
                source_content = f.get("content", f.get("truncated_content", ""))
                break
        source_lines = source_content.splitlines() if source_content else []
        validated_count = 0
        rejected_count = 0

        general_issues = []
        for item in res_dict.get("inline_comments", []):
            if isinstance(item, dict):
                if source_lines and not validate_finding_evidence(item, source_lines):
                    rejected_count += 1
                    logger.info(f"Rejected LLM finding (no evidence): {filename}:{item.get('line')} - {item.get('issue','')[:60]}")
                    continue
                validated_count += 1
                general_issues.append({
                    "file": filename,
                    "line": int(item.get("line", 1)) if str(item.get("line")).isdigit() else 1,
                    "severity": item.get("severity", "Medium"),
                    "category": item.get("category", "Bug"),
                    "issue": item.get("issue", "Quality or logic concern"),
                    "suggestion": item.get("suggestion", "Please verify this code."),
                    "why_it_matters": item.get("why_it_matters", "No explanation provided."),
                    "risk_level": item.get("risk_level", item.get("severity", "Medium")),
                    "before_code": item.get("before_code", ""),
                    "after_code": item.get("after_code", ""),
                    "source": "ai_analysis",
                })

        security_issues = []
        for item in res_dict.get("security_findings", []):
            if isinstance(item, dict):
                if source_lines and not validate_finding_evidence(item, source_lines):
                    rejected_count += 1
                    logger.info(f"Rejected LLM security finding (no evidence): {filename}:{item.get('line')} - {item.get('issue','')[:60]}")
                    continue
                validated_count += 1
                security_issues.append({
                    "file": filename,
                    "line": int(item.get("line", 1)) if str(item.get("line")).isdigit() else 1,
                    "severity": item.get("severity", "Medium"),
                    "category": "Security",
                    "issue": item.get("issue", "Potential vulnerability found"),
                    "suggestion": item.get("suggestion", "Please verify and secure this code."),
                    "why_it_matters": item.get("why_it_matters", "No explanation provided."),
                    "risk_level": item.get("risk_level", item.get("severity", "Medium")),
                    "before_code": item.get("before_code", ""),
                    "after_code": item.get("after_code", ""),
                    "source": "ai_analysis",
                })

        smell_issues = []
        for item in res_dict.get("code_smells", []):
            if isinstance(item, dict):
                if source_lines and not validate_finding_evidence(item, source_lines):
                    rejected_count += 1
                    logger.info(f"Rejected LLM smell finding (no evidence): {filename}:{item.get('line')} - {item.get('issue','')[:60]}")
                    continue
                validated_count += 1
                smell_issues.append({
                    "file": filename,
                    "line": int(item.get("line", 1)) if str(item.get("line")).isdigit() else 1,
                    "severity": item.get("severity", "Low"),
                    "category": "Code Smell",
                    "issue": item.get("issue", "Code quality smell detected"),
                    "suggestion": item.get("suggestion", "Please refactor this code to clean it up."),
                    "why_it_matters": item.get("why_it_matters", "No explanation provided."),
                    "risk_level": item.get("risk_level", item.get("severity", "Low")),
                    "before_code": item.get("before_code", ""),
                    "after_code": item.get("after_code", ""),
                    "source": "ai_analysis",
                })

        # ── Run static scanners to supplement/correct LLM findings ──
        # Detect language from file extension
        ext = os.path.splitext(filename)[1].lower()
        lang_ext_map = {".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
                         ".jsx": "JavaScript", ".tsx": "TypeScript", ".java": "Java",
                         ".go": "Go", ".rb": "Ruby", ".php": "PHP"}
        detected_lang = lang_ext_map.get(ext, "Python")
        static_results = apply_static_scanners(filename, source_content, detected_lang)
        static_sec = static_results.get("security_findings", [])
        static_smells = static_results.get("code_smells", [])

        # Merge static findings (avoid duplicates with LLM findings)
        llm_keys = set()
        for f in security_issues + smell_issues:
            llm_keys.add((f["line"], f["issue"][:60]))

        for sf in static_sec:
            key = (sf["line"], sf["issue"][:60])
            if key not in llm_keys:
                llm_keys.add(key)
                security_issues.append({
                    "file": filename,
                    "line": sf["line"],
                    "severity": sf.get("severity", "Medium"),
                    "category": "Security",
                    "issue": sf["issue"],
                    "suggestion": sf.get("suggestion", ""),
                    "why_it_matters": sf.get("why_it_matters", sf["issue"]),
                    "risk_level": sf.get("risk_level", sf.get("severity", "Medium")),
                    "before_code": sf.get("before_code", ""),
                    "after_code": sf.get("after_code", ""),
                    "source": "static_analysis",
                })
                validated_count += 1

        for sf in static_smells:
            key = (sf["line"], sf["issue"][:60])
            if key not in llm_keys:
                llm_keys.add(key)
                smell_issues.append({
                    "file": filename,
                    "line": sf["line"],
                    "severity": sf.get("severity", "Medium"),
                    "category": "Code Smell",
                    "issue": sf["issue"],
                    "suggestion": sf.get("suggestion", ""),
                    "why_it_matters": sf.get("why_it_matters", sf["issue"]),
                    "risk_level": sf.get("risk_level", sf.get("severity", "Medium")),
                    "before_code": sf.get("before_code", ""),
                    "after_code": sf.get("after_code", ""),
                    "source": "static_analysis",
                })
                validated_count += 1

        logger.info(f"Evidence validation for {filename}: {validated_count} accepted, {rejected_count} rejected (hallucinations), static: {len(static_sec)}+{len(static_smells)}")
        all_findings.extend(security_issues + smell_issues + general_issues)

        if len(test_suggestions_by_file) < 1 and res_dict.get("test_suggestions"):
            test_suggestions_by_file[filename] = res_dict["test_suggestions"]

    repo_analysis = analyze_repository(
        client=client,
        github_service=github_service,
        repo_name=repo_name,
        qualitative_report=repo_insights or "No qualitative report available."
    )

    severity_counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0, "Info": 0}
    for f in all_findings:
        sev = f["severity"]
        if sev in severity_counts:
            severity_counts[sev] += 1

    risk_score = min(
        100,
        25 * severity_counts["Critical"]
        + 15 * severity_counts["High"]
        + 6 * severity_counts["Medium"]
        + 1 * severity_counts["Low"]
    )

    inline_comments = []
    for f in all_findings:
        body_text = f"File: {f['file']}\nLine: {f['line']}\nIssue: {f['issue']}\nSeverity: {f['severity']}\nRecommendation: {f['suggestion']}"
        inline_comments.append({
            "file": f["file"],
            "line": f["line"],
            "body": body_text,
            "patch": f"@@ -1,1 +1,{f['line']} @@\n+{f['issue']}",
        })

    files_analyzed_log = []
    for item in tree_items:
        if item.type == "blob":
            path = item.path
            ext = os.path.splitext(path)[1].lower()
            ext_map = {
                ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript",
                ".ts": "TypeScript", ".tsx": "TypeScript", ".java": "Java",
                ".cs": "C#", ".go": "Go", ".rb": "Ruby", ".php": "PHP",
                ".cpp": "C/C++", ".c": "C/C++", ".h": "C/C++", ".rs": "Rust",
                ".kt": "Kotlin", ".swift": "Swift",
            }
            detected_lang = ext_map.get(ext, "Other")
            file_type = detected_lang
            if ext in [".md", ".txt"]:
                file_type = "Documentation"
            elif ext in [".json", ".yaml", ".yml", ".ini", ".cfg", ".toml", ".xml"]:
                file_type = "Configuration"

            is_source = detected_lang != "Other"
            
            if should_skip_file(path):
                files_analyzed_log.append({
                    "file": path, "type": file_type, "status": "Skipped", "findings": 0
                })
            elif path in scanned_files:
                file_findings_count = len([fn for fn in all_findings if fn["file"] == path])
                files_analyzed_log.append({
                    "file": path, "type": file_type, "status": "Analyzed", "findings": file_findings_count
                })
            elif is_source:
                files_analyzed_log.append({
                    "file": path, "type": file_type, "status": "Scanned", "findings": 0
                })
            else:
                files_analyzed_log.append({
                    "file": path, "type": file_type, "status": "Skipped", "findings": 0
                })

    test_suggestions_md = []
    for fn, tests in test_suggestions_by_file.items():
        test_suggestions_md.append(f"### File: {fn}\n{tests}\n")
    test_suggestions_compiled = "\n".join(test_suggestions_md)

    latency = round(time.time() - start_time, 2)
    estimated_tokens_count = characters_analyzed_count // 4

    repo_file_scores = [res_dict.get("scores", {}) for res_dict in files_reviews_map.values() if isinstance(res_dict, dict) and "scores" in res_dict]
    overall_repo_scores = resolve_scores(repo_file_scores, risk_score, severity_counts)

    return {
        "repo_name": repo_name,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "risk_score": risk_score,
        "findings": all_findings,
        "inline_comments": inline_comments,
        "test_suggestions": test_suggestions_compiled,
        "repo_analysis": repo_analysis,
        "severity_counts": severity_counts,
        "latency_seconds": latency,
        "total_files_analyzed": len(scanned_files),
        "total_files_count": len(source_files),
        "files_analyzed_log": files_analyzed_log,
        "files_analyzed_count": files_analyzed_count,
        "characters_analyzed_count": characters_analyzed_count,
        "estimated_tokens_count": estimated_tokens_count,
        "groq_requests_made": groq_requests_made,
        "cached_results_used": cached_results_used,
        "scores": overall_repo_scores,
        "token_stats": token_stats,
    }
