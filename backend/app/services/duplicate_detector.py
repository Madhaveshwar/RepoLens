"""
Duplicate Code Detection — deterministic cross-file clone detection.

Uses a rolling-hash approach over normalized 5-line blocks, then refines
candidates with exact block extension. Only real fetched source content is
compared — nothing invented. Trivial duplicates (1-2 line imports, braces)
are excluded by the minimum block size, and a file is never compared with
itself.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from app.utils.logger import get_logger

logger = get_logger("duplicate_detector")

DEFAULT_MIN_LINES = 6          # a block shorter than this is trivial
DEFAULT_MIN_SIMILARITY = 70    # percent
MAX_FINDINGS = 60              # keep the report focused


def normalize_line(line: str) -> str:
    """Normalize a source line for comparison: strip whitespace/comments."""
    stripped = line.strip()
    if not stripped:
        return ""
    # Remove comment-only lines
    if stripped.startswith(("#", "//", "/*", "*", "--", "<!--")):
        return ""
    # Remove inline comments (best-effort; avoids a full lexer)
    cleaned = re.sub(r"(?<![:'\"])#.*$", "", stripped)
    cleaned = re.sub(r"//.*$", "", cleaned)
    # Collapse whitespace and trailing separators
    cleaned = " ".join(cleaned.split()).rstrip(";").strip()
    return cleaned


def block_hash(lines: list[str]) -> str:
    return hashlib.sha1("\n".join(lines).encode("utf-8", errors="replace")).hexdigest()


def similarity_pct(seq_a: list[str], seq_b: list[str]) -> int:
    """Compare two normalized line sequences; returns 0-100."""
    if not seq_a or not seq_b:
        return 0
    matches = sum(1 for a, b in zip(seq_a, seq_b) if a == b)
    length = max(len(seq_a), len(seq_b))
    return int(round((matches / length) * 100))


def detect_duplicates(
    files: list[dict],
    min_lines: int = DEFAULT_MIN_LINES,
    min_similarity: int = DEFAULT_MIN_SIMILARITY,
    max_findings: int = MAX_FINDINGS,
) -> dict:
    """Detect duplicated blocks across real source files.

    files: list of {path, lines} where lines are the REAL file lines.
    Returns {"findings": [...], "groups": n, "files_analyzed": n,
             "parameters": {...}}
    """
    findings: list[dict] = []
    files_analyzed = 0

    # 1. Pre-compute normalized lines per file.
    normalized: dict[str, list[tuple[int, str]]] = {}  # path -> [(orig_line_no, norm)]
    for f in files:
        path = f["path"]
        lines = f.get("lines") or f.get("content", "").splitlines()
        norm = []
        for idx, line in enumerate(lines):
            n = normalize_line(line)
            if n:
                norm.append((idx + 1, n))
        if len(norm) >= min_lines:
            normalized[path] = norm
            files_analyzed += 1

    # 2. Hash every min_lines window per file, index by hash.
    window_index: dict[str, list[tuple[str, int]]] = {}  # hash -> [(path, start_norm_idx)]
    for path, norm in normalized.items():
        for i in range(len(norm) - min_lines + 1):
            window = [norm[j][1] for j in range(i, i + min_lines)]
            h = block_hash(window)
            window_index.setdefault(h, []).append((path, i))

    # 3. For each hash with multiple locations, extend the match greedily.
    reported_keys: set[tuple[str, int, str, int]] = set()
    group_count = 0

    for h, locations in window_index.items():
        if len(locations) < 2:
            continue
        # Distinct files only — never compare a file with itself.
        pairs = []
        for a in range(len(locations)):
            for b in range(a + 1, len(locations)):
                (path_a, idx_a), (path_b, idx_b) = locations[a], locations[b]
                if path_a == path_b:
                    continue
                # Skip reversed duplicate pairs from overlapping windows
                key = (path_a, idx_a, path_b, idx_b)
                if key in reported_keys:
                    continue
                pairs.append((path_a, idx_a, path_b, idx_b))

        if not pairs:
            continue
        group_count += 1

        for path_a, idx_a, path_b, idx_b in pairs:
            norm_a = normalized[path_a]
            norm_b = normalized[path_b]
            # Greedy extension beyond the seed window
            length = min_lines
            while (
                idx_a + length < len(norm_a)
                and idx_b + length < len(norm_b)
                and norm_a[idx_a + length][1] == norm_b[idx_b + length][1]
                and length < 200
            ):
                length += 1

            if length < min_lines:
                continue

            seq_a = [norm_a[idx_a + k][1] for k in range(length)]
            seq_b = [norm_b[idx_b + k][1] for k in range(length)]
            sim = similarity_pct(seq_a, seq_b)
            if sim < min_similarity:
                continue

            start_a = norm_a[idx_a][0]
            end_a = norm_a[idx_a + length - 1][0]
            start_b = norm_b[idx_b][0]
            end_b = norm_b[idx_b + length - 1][0]

            reported_keys.add((path_a, idx_a, path_b, idx_b))
            findings.append({
                "file_a": path_a,
                "start_line_a": start_a,
                "end_line_a": end_a,
                "file_b": path_b,
                "start_line_b": start_b,
                "end_line_b": end_b,
                "similarity": sim,
                "duplicated_lines": length,
                "token_hash": h,
                "snippet": "\n".join(seq_a[:12]),
            })

            if len(findings) >= max_findings:
                logger.info(f"Duplicate detection capped at {max_findings} findings")
                return {
                    "findings": findings,
                    "groups": group_count,
                    "files_analyzed": files_analyzed,
                    "parameters": {
                        "min_block_lines": min_lines,
                        "min_similarity_pct": min_similarity,
                        "capped": True,
                    },
                }

    # Sort by similarity, then size
    findings.sort(key=lambda f: (-f["duplicated_lines"], -f["similarity"]))

    return {
        "findings": findings,
        "groups": group_count,
        "files_analyzed": files_analyzed,
        "parameters": {
            "min_block_lines": min_lines,
            "min_similarity_pct": min_similarity,
            "capped": False,
        },
    }
