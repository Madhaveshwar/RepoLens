"""
GitHub Source Fetcher — pull real source file contents from a repository.

Used by the deterministic insight analyzers (dependencies, duplicates,
complexity, architecture, technical debt). Every analyzer only ever sees
actual file content fetched from GitHub — nothing is invented.

Note: PyGithub get_git_tree returns at most 100k entries / 7MB; larger
repositories are truncated by GitHub itself, which we surface honestly.
"""

from __future__ import annotations

import os
import fnmatch
from typing import Any

from app.utils.logger import get_logger
from app.utils.validation import should_skip_file

logger = get_logger("source_fetcher")

# Extensions considered text/source for content-level analysis.
SOURCE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".cs", ".go", ".rb",
    ".php", ".cpp", ".cc", ".c", ".h", ".hpp", ".rs", ".kt", ".swift",
}

# Manifest / lock files we can actually parse (dependency scanner).
MANIFEST_FILES = {
    "package.json": "npm",
    "requirements.txt": "pip",
    "pyproject.toml": "pip",
    "Pipfile": "pip",
    "Pipfile.lock": "pip",
    "poetry.lock": "pip",
    "pom.xml": "maven",
    "build.gradle": "gradle",
    "build.gradle.kts": "gradle",
    "composer.json": "composer",
    "Gemfile": "bundler",
    "Gemfile.lock": "bundler",
    "go.mod": "go",
    "Cargo.toml": "cargo",
    "Cargo.lock": "cargo",
}

# Extra directories ignored for insight analysis (on top of should_skip_file).
EXTRA_IGNORED_DIRS = {
    "vendor", "venv", ".venv", "env", "virtualenv", "site-packages",
    "__pycache__", ".next", ".nuxt", "out", "target", "obj", "bin",
    "bower_components", ".terraform", ".idea", ".vscode", "storage",
}

# Hard per-file size guard: skip files larger than 256 KB for content fetch.
MAX_FILE_BYTES = 256 * 1024

# Global budget: never fetch more than this many file contents in one pass.
MAX_FILES_FETCHED = 150

# Perf guard: skip files larger than this many lines for duplicate detection.
MAX_DUP_FILE_LINES = 4000


def is_ignored_path(path: str) -> bool:
    """True when a path should be excluded from insight analysis."""
    if should_skip_file(path):
        return True
    parts = path.split("/")
    for part in parts[:-1]:  # directories
        if part in EXTRA_IGNORED_DIRS or part.startswith("."):
            return True
    basename = os.path.basename(path).lower()
    if basename.endswith(".min.js") or basename.endswith(".min.css"):
        return True
    if basename.endswith(".map"):
        return True
    return False


def is_source_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in SOURCE_EXTENSIONS


def is_manifest_file(path: str) -> bool:
    return os.path.basename(path) in MANIFEST_FILES


class RepoSourceFetcher:
    """Fetch a repository's file tree and real file contents via GitHub."""

    def __init__(self, github_service, repo_name: str):
        self.github_service = github_service
        self.repo_name = repo_name
        self._client = github_service.get_client_for_repo(repo_name)
        self._repo = self._client.get_repo(repo_name)
        self.default_branch = self._repo.default_branch or "main"
        self._branch_sha: str | None = None
        self.truncated = False
        self._fetch_budget_used = 0
        self._content_cache: dict[tuple[str, str], str] = {}

    # ── tree access ───────────────────────────────────────────────

    def get_branch_sha(self, branch: str | None = None) -> str | None:
        branch = branch or self.default_branch
        if self._branch_sha:
            return self._branch_sha
        try:
            branch_obj = self._repo.get_branch(branch)
            self._branch_sha = branch_obj.commit.sha
        except Exception as exc:
            logger.error(f"Failed to resolve branch SHA for {self.repo_name}@{branch}: {exc}")
            self._branch_sha = None
        return self._branch_sha

    def get_tree_items(self, branch: str | None = None) -> list[Any]:
        """Return blob entries of the recursive git tree (real files only)."""
        sha = self.get_branch_sha(branch)
        if not sha:
            return []
        try:
            git_tree = self._repo.get_git_tree(sha=sha, recursive=True)
            self.truncated = bool(getattr(git_tree, "truncated", False))
            if self.truncated:
                logger.warning(f"Git tree for {self.repo_name} was truncated by GitHub; analysis covers the retrieved subset only.")
            return [item for item in git_tree.tree if item.type == "blob"]
        except Exception as exc:
            logger.error(f"Failed to fetch git tree for {self.repo_name}: {exc}")
            return []

    def list_source_paths(self, branch: str | None = None) -> list[dict]:
        """Real source files (path, size) present in the repo, ignoring junk."""
        paths = []
        for item in self.get_tree_items(branch):
            path = item.path
            if not is_source_file(path) or is_ignored_path(path):
                continue
            paths.append({"path": path, "size": item.size or 0})
        paths.sort(key=lambda p: p["size"])
        return paths

    def list_manifest_paths(self, branch: str | None = None) -> list[dict]:
        """Real dependency manifest/lock files present in the repo."""
        found = []
        for item in self.get_tree_items(branch):
            path = item.path
            if is_ignored_path(path):
                continue
            if is_manifest_file(path):
                found.append({
                    "path": path,
                    "ecosystem": MANIFEST_FILES[os.path.basename(path)],
                    "size": item.size or 0,
                })
        found.sort(key=lambda p: p["path"])
        return found

    def find_paths_by_glob(self, patterns: list[str], branch: str | None = None) -> list[str]:
        """Real file paths matching any glob pattern (e.g. 'docker-compose.yml')."""
        matched = []
        for item in self.get_tree_items(branch):
            path = item.path
            if is_ignored_path(path):
                continue
            basename = os.path.basename(path)
            for pattern in patterns:
                if fnmatch.fnmatch(basename, pattern) or fnmatch.fnmatch(path, pattern):
                    matched.append(path)
                    break
        return matched

    # ── content access ────────────────────────────────────────────

    def fetch_content(self, path: str, branch: str | None = None) -> str:
        """Fetch real file content at the given branch/ref (cached)."""
        ref = branch or self.default_branch
        cache_key = (path, ref)
        if cache_key in self._content_cache:
            return self._content_cache[cache_key]

        if self._fetch_budget_used >= MAX_FILES_FETCHED:
            logger.warning(f"Fetch budget exhausted ({MAX_FILES_FETCHED} files); skipping {path}")
            return ""

        content = self.github_service.get_file_content(self.repo_name, path, ref)
        self._fetch_budget_used += 1
        self._content_cache[cache_key] = content or ""
        return self._content_cache[cache_key]

    def fetch_source_files(
        self,
        branch: str | None = None,
        max_files: int = MAX_FILES_FETCHED,
        max_lines_per_file: int = MAX_DUP_FILE_LINES,
    ) -> list[dict]:
        """Fetch real content for source files (smallest first for coverage).

        Returns a list of dicts: {path, content, lines}.
        """
        candidates = self.list_source_paths(branch)
        fetched = []
        for candidate in candidates:
            if len(fetched) >= max_files:
                break
            if candidate["size"] > MAX_FILE_BYTES:
                continue
            content = self.fetch_content(candidate["path"], branch)
            if not content:
                continue
            lines = content.splitlines()
            if len(lines) > max_lines_per_file:
                lines = lines[:max_lines_per_file]
            if not any(line.strip() for line in lines):
                continue
            fetched.append({
                "path": candidate["path"],
                "content": "\n".join(lines),
                "lines": lines,
            })
        logger.info(
            f"Fetched {len(fetched)} source files from {self.repo_name} "
            f"(budget used: {self._fetch_budget_used})"
        )
        return fetched
