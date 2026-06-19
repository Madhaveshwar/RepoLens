"""Security scanner module using LLM to detect vulnerabilities in code changes."""

from __future__ import annotations

import json
import sys
import os
import re
from typing import Any
from langsmith import traceable

# Ensure the parent directory is on the search path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.prompts import SYSTEM_SECURITY_PROMPT, build_security_prompt

MODEL_NAME = "llama-3.3-70b-versatile"


def parse_json_from_llm(content: str) -> list[dict]:
    """Helper to parse a list of JSON findings from raw LLM output."""
    if not content:
        return []

    content = content.strip()
    # Check for markdown code fence
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
        # Fallback regex search for JSON array
        array_match = re.search(r"\[\s*\{[\s\S]*\}\s*\]", content)
        if array_match:
            try:
                data = json.loads(array_match.group(0))
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass

        # Fallback regex search for a single dict
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
    """Scan code changes for security vulnerabilities using Groq."""
    prompt = build_security_prompt(filename, code, patch, language)

    active_model = "llama-3.3-70b-versatile"
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_SECURITY_PROMPT},
                {"role": "user", "content": prompt}
            ],
            model=active_model,
            temperature=temperature,
        )
        result_text = chat_completion.choices[0].message.content
    except Exception as e:
        try:
            chat_completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": SYSTEM_SECURITY_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                model="llama-3.1-8b-instant",
                temperature=temperature,
            )
            result_text = chat_completion.choices[0].message.content
        except Exception as fallback_e:
            from reviewer import handle_groq_error
            raise handle_groq_error(fallback_e)

    findings = parse_json_from_llm(result_text)

    # Ensure findings match target schema and have valid properties
    validated_findings = []
    code_lines = code.splitlines()
    for item in findings:
        if isinstance(item, dict):
            line_val = int(item.get("line", 1)) if str(item.get("line")).isdigit() else 1
            line_idx = line_val - 1
            target_line_text = ""
            if 0 <= line_idx < len(code_lines):
                target_line_text = code_lines[line_idx].strip()

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
                continue

            # Normalize fields
            validated_findings.append({
                "file": item.get("file", filename),
                "line": line_val,
                "severity": item.get("severity", "Medium"),
                "category": "Security",
                "issue": item.get("issue", "Potential vulnerability found"),
                "suggestion": item.get("suggestion", "Please verify and secure this code."),
            })

    return validated_findings
