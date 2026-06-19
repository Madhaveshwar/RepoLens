# backend/app/utils/validation.py
from __future__ import annotations
import re

KEYWORD_PATTERNS = [
    r"\bdef\b",
    r"\bclass\b",
    r"\bfunction\b",
    r"\bimport\b",
    r"\breturn\b",
    r"\bif\b",
    r"\bfor\b",
    r"\bwhile\b",
    r"print\s*\(",
    r"console\.log\s*\(",
    r"#include\b",
    r"\bpublic\s+class\b",
]

def is_valid_code(code: str) -> bool:
    if not code:
        return False
    cleaned_code = code.strip()
    if len(cleaned_code) < 12:
        return False
    if cleaned_code.isdigit():
        return False
    alpha_count = sum(char.isalpha() for char in cleaned_code)
    if alpha_count == 0:
        return False

    structure_hits = 0
    if re.search(r"[{}()\[\];=<>:]", cleaned_code):
        structure_hits += 1
    if re.search(r"\b\w+\s*=\s*.+", cleaned_code):
        structure_hits += 1
    if re.search(r"^\s*#", cleaned_code, flags=re.MULTILINE):
        structure_hits += 1
    if re.search(r"^\s*//", cleaned_code, flags=re.MULTILINE):
        structure_hits += 1

    keyword_hits = sum(
        1
        for pattern in KEYWORD_PATTERNS
        if re.search(pattern, cleaned_code, flags=re.IGNORECASE)
    )

    line_count = len([line for line in cleaned_code.splitlines() if line.strip()])
    if line_count == 1 and keyword_hits == 0 and structure_hits == 0:
        return False

    if keyword_hits >= 1 and structure_hits >= 1:
        return True
    if structure_hits >= 2 and alpha_count >= 4:
        return True
    return False

def should_skip_file(path: str) -> bool:
    ignored_patterns = [
        "node_modules", "dist", "build", ".git", "coverage",
        "package-lock.json", "yarn.lock", "pnpm-lock.yaml"
    ]
    path_lower = path.lower()
    for p in ignored_patterns:
        if p in path_lower:
            return True

    import os
    basename = os.path.basename(path).lower()
    ext = os.path.splitext(path)[1].lower()

    if ".min." in basename:
        return True
    if (
        "generated" in basename or
        "webpack" in basename or
        basename.endswith(".map")
    ):
        return True

    binary_extensions = {
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tiff", ".svg",
        ".zip", ".tar", ".gz", ".tgz", ".bz2", ".rar", ".7z", ".xz",
        ".exe", ".dll", ".so", ".dylib", ".bin", ".o", ".a", ".lib", ".out",
        ".mp4", ".mkv", ".avi", ".mov", ".flv", ".mp3", ".wav", ".flac", ".ogg",
        ".ttf", ".otf", ".woff", ".woff2", ".eot",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".db", ".sqlite", ".dat",
    }
    if ext in binary_extensions:
        return True
    return False

def detect_code_language(code: str) -> str:
    cleaned = code.strip()
    
    # Python
    if re.search(r'^\s*(def|class|import|from)\b', cleaned, re.MULTILINE) or \
       re.search(r'\belif\s+.*:|\bif\s+__name__\s*==\s*["\']__main__["\']:', cleaned) or \
       re.search(r'print\s*\([^)]*\)', cleaned) or \
       (re.search(r'#\s+', cleaned) and "def " in cleaned):
        return "Python"
        
    # JavaScript / TypeScript
    if re.search(r'\b(const|let|var|function|async|await|export|import)\b', cleaned):
        # Differentiate JS vs TS
        if re.search(r'\b(interface|type|namespace|as|public|private|protected|readonly)\b', cleaned) or \
           re.search(r':\s*(string|number|boolean|any|void|unknown|never)\b', cleaned):
            return "TypeScript"
        return "JavaScript"
        
    # Java
    if re.search(r'\b(public|private|protected)\s+class\b', cleaned) or \
       re.search(r'\bSystem\.out\.print(ln)?\b', cleaned) or \
       re.search(r'\bpublic\s+static\s+void\s+main\b', cleaned):
        return "Java"
        
    # Go
    if re.search(r'^\s*package\s+\w+', cleaned, re.MULTILINE) or \
       re.search(r'\bfunc\s+\w+\(', cleaned) or \
       re.search(r'import\s+\([^)]*\)', cleaned):
        return "Go"
        
    # Rust
    if re.search(r'\bfn\s+\w+\(', cleaned) or \
       re.search(r'\bpub\s+fn\b', cleaned) or \
       re.search(r'\blet\s+mut\b', cleaned) or \
       re.search(r'\bimpl\b', cleaned) or \
       re.search(r'use\s+std::', cleaned):
        return "Rust"
        
    # C/C++
    if re.search(r'#include\s+<[^>]+>', cleaned) or \
       re.search(r'\bint\s+main\s*\(', cleaned) or \
       re.search(r'\bstd::cout\b', cleaned) or \
       re.search(r'\bprintf\s*\(', cleaned):
        return "C/C++"
        
    # C#
    if re.search(r'\busing\s+System\b', cleaned) or \
       re.search(r'\bnamespace\s+\w+', cleaned) or \
       re.search(r'\bpublic\s+class\s+\w+', cleaned) and "Console.Write" in cleaned:
        return "C#"
        
    # HTML/CSS
    if re.search(r'<!DOCTYPE html>|<html|href=|src=|<div|<span|<p\b', cleaned, re.IGNORECASE):
        return "HTML/CSS"
        
    # SQL
    if re.search(r'\b(SELECT|INSERT|UPDATE|DELETE|CREATE TABLE|ALTER TABLE|DROP TABLE)\b', cleaned, re.IGNORECASE):
        return "SQL"
        
    return "Unknown"

def validate_code_snippet(code: str, selected_language: str = "Auto") -> tuple[bool, str, str]:
    if not code or not code.strip():
        return False, "The code snippet is empty. Please enter some code to review.", "Unknown"
        
    cleaned = code.strip()
    
    # Check URL
    url_pattern = re.compile(r'^\s*(https?://[^\s]+|www\.[^\s]+)\s*$', re.IGNORECASE)
    if url_pattern.match(cleaned) or (cleaned.startswith(("http://", "https://", "www.")) and len(cleaned.splitlines()) == 1):
        return False, "The input appears to be a URL. Please provide actual source code instead.", "Unknown"
        
    # Check Resume
    resume_keywords = {"experience", "education", "employment", "skills", "projects", "work history", "objective", "references", "curriculum vitae", "resume"}
    text_lower = cleaned.lower()
    resume_matches = sum(1 for kw in resume_keywords if re.search(r'\b' + re.escape(kw) + r'\b', text_lower))
    if resume_matches >= 3 and not any(k in text_lower for k in ["def ", "class ", "import ", "const ", "function", "{", "}", "fn "]):
        return False, "The input appears to be a resume. Please provide actual source code instead.", "Unknown"
        
    # Basic heuristic code checks
    alpha_count = sum(char.isalpha() for char in cleaned)
    if alpha_count == 0:
        return False, "The input does not contain any alphanumeric characters. Please provide valid code.", "Unknown"
        
    # Check for plain English / prose paragraphs
    code_symbols = {'{', '}', '[', ']', '(', ')', ';', '=', '<', '>', '_', '+', '-', '*', '/', '#', '\\', '$', ':', '&', '|', '^', '%'}
    symbol_count = sum(1 for char in cleaned if char in code_symbols)
    symbol_ratio = symbol_count / len(cleaned) if len(cleaned) > 0 else 0
    
    words = [w for w in re.split(r'\W+', text_lower) if w]
    stop_words = {"the", "and", "of", "to", "in", "is", "that", "it", "he", "was", "for", "on", "are", "as", "with", "his", "they", "i", "at", "be", "this", "have", "from"}
    stop_word_count = sum(1 for w in words if w in stop_words)
    stop_word_ratio = stop_word_count / len(words) if len(words) > 0 else 0
    
    # Language detection
    detected_lang = detect_code_language(code)
    
    if detected_lang == "Unknown":
        # If symbol ratio is extremely low (< 2.5%) and stop word ratio is high (> 15%), reject as prose.
        if symbol_ratio < 0.025 and stop_word_ratio > 0.15 and len(words) > 10:
            return False, "The input appears to be plain text or prose rather than source code. Please provide a valid code snippet.", "Unknown"
        # If it doesn't pass is_valid_code rules
        if not is_valid_code(code):
            return False, "The input does not resemble valid source code. Please provide a valid code snippet.", "Unknown"
            
    final_lang = detected_lang
    if final_lang == "Unknown":
        if selected_language and selected_language != "Auto":
            final_lang = selected_language
        else:
            final_lang = "Python"  # Default fallback
            
    return True, "Code snippet is valid.", final_lang
