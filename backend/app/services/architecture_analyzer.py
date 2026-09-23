"""
Architecture Analysis — strictly evidence-based.

Detects components, layers, frameworks and inter-module relationships from
the repository's REAL file tree and file contents. Technologies are reported
only when actually detected (dependency manifests, imports, config files).
Nothing is inferred about stacks that leave no trace.
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from typing import Any

from app.services.source_fetcher import RepoSourceFetcher, is_ignored_path
from app.utils.logger import get_logger

logger = get_logger("architecture_analyzer")

MAX_IMPORT_EDGES = 60
MAX_ENTRIES = 15


# ── Framework / technology detection ─────────────────────────────────
# Each signal requires a REAL trace: a manifest dependency, an import, or
# a config file that actually exists.

def _manifest_dep_versions(manifest_contents: dict[str, str]) -> dict[str, str]:
    """Flatten manifest package lists → {package_lower: manifest_file}."""
    pkgs: dict[str, str] = {}
    try:
        from app.services.dependency_scanner import (
            parse_requirements_txt, parse_pyproject_toml, parse_package_json,
            parse_go_mod, parse_cargo_toml, parse_composer_json,
        )
        for path, content in manifest_contents.items():
            basename = os.path.basename(path)
            parsed: list[dict] = []
            if basename == "package.json":
                parsed = parse_package_json(content)
            elif basename == "requirements.txt":
                parsed = parse_requirements_txt(content)
            elif basename == "pyproject.toml":
                parsed = parse_pyproject_toml(content)
            elif basename == "go.mod":
                parsed = parse_go_mod(content)
            elif basename == "Cargo.toml":
                parsed = parse_cargo_toml(content)
            elif basename == "composer.json":
                parsed = parse_composer_json(content)
            for dep in parsed:
                pkgs.setdefault(dep["name"].lower(), path)
    except Exception as exc:
        logger.error(f"Manifest flattening failed: {exc}")
    return pkgs


def _detect_frameworks(
    tree_paths: list[str],
    manifest_pkgs: dict[str, str],
    file_contents: dict[str, str],
) -> list[dict]:
    """Return detected technologies with concrete evidence for each."""
    detected: list[dict] = []

    def add(name: str, category: str, evidence: list[str]):
        detected.append({"name": name, "category": category, "evidence": evidence[:3]})

    # Backend / frontend frameworks via manifest deps
    framework_deps = {
        "fastapi": ("FastAPI", "Backend framework"),
        "flask": ("Flask", "Backend framework"),
        "django": ("Django", "Backend framework"),
        "express": ("Express", "Backend framework"),
        "next": ("Next.js", "Frontend framework"),
        "nextjs": ("Next.js", "Frontend framework"),
        "react": ("React", "Frontend framework"),
        "vue": ("Vue.js", "Frontend framework"),
        "@angular/core": ("Angular", "Frontend framework"),
        "svelte": ("Svelte", "Frontend framework"),
        "spring-boot-starter-web": ("Spring Boot", "Backend framework"),
    }
    for dep_key, (name, category) in framework_deps.items():
        if dep_key in manifest_pkgs:
            add(name, category, [f"Declared in {manifest_pkgs[dep_key]}"])

    # Databases via manifest deps + config files
    db_deps = {
        "sqlalchemy": ("SQLAlchemy", "Database layer"),
        "psycopg2": ("PostgreSQL driver (psycopg2)", "Database layer"),
        "asyncpg": ("PostgreSQL driver (asyncpg)", "Database layer"),
        "pymongo": ("MongoDB driver (PyMongo)", "Database layer"),
        "redis": ("Redis client", "Cache/Datastore"),
        "mongoose": ("Mongoose (MongoDB)", "Database layer"),
        "pg": ("PostgreSQL driver (node-postgres)", "Database layer"),
        "mysql2": ("MySQL driver", "Database layer"),
        "sqlite3": ("SQLite driver", "Database layer"),
        "prisma": ("Prisma ORM", "Database layer"),
        "typeorm": ("TypeORM", "Database layer"),
        "sequelize": ("Sequelize ORM", "Database layer"),
    }
    for dep_key, (name, category) in db_deps.items():
        if dep_key in manifest_pkgs:
            add(name, category, [f"Declared in {manifest_pkgs[dep_key]}"])

    # Task queue / cache
    queue_deps = {
        "celery": ("Celery", "Background jobs"),
        "bullmq": ("BullMQ", "Background jobs"),
        "sidekiq": ("Sidekiq", "Background jobs"),
        "kafka-python": ("Kafka client", "Message broker"),
    }
    for dep_key, (name, category) in queue_deps.items():
        if dep_key in manifest_pkgs:
            add(name, category, [f"Declared in {manifest_pkgs[dep_key]}"])

    # AI / LLM integrations (only if genuinely declared or imported)
    ai_deps = {
        "groq": ("Groq client", "AI/LLM"),
        "openai": ("OpenAI client", "AI/LLM"),
        "anthropic": ("Anthropic client", "AI/LLM"),
        "langchain": ("LangChain", "AI/LLM"),
        "langsmith": ("LangSmith", "AI/LLM"),
        "transformers": ("HuggingFace Transformers", "AI/ML"),
    }
    for dep_key, (name, category) in ai_deps.items():
        if dep_key in manifest_pkgs:
            add(name, category, [f"Declared in {manifest_pkgs[dep_key]}"])

    # Infra / deployment via real config files
    infra_files = {
        "dockerfile": ("Docker", "Containerization"),
        "docker-compose.yml": ("Docker Compose", "Containerization"),
        "docker-compose.yaml": ("Docker Compose", "Containerization"),
        "render.yaml": ("Render", "Deployment config"),
        "vercel.json": ("Vercel", "Deployment config"),
        "nginx.conf": ("nginx", "Web server config"),
        ".github/workflows": ("GitHub Actions", "CI/CD"),
    }
    lowered = [p.lower() for p in tree_paths]
    for marker, (name, category) in infra_files.items():
        marker_l = marker.lower()
        for p in lowered:
            if p == marker_l or p.endswith("/" + marker_l) or p.startswith(marker_l):
                add(name, category, [f"Found config file: {p}"])
                break

    # PostgreSQL / Redis referenced in compose files (real content check)
    for path, content in file_contents.items():
        if "docker-compose" in path.lower() and content:
            if "postgres" in content.lower():
                add("PostgreSQL", "Database", [f"postgres service in {path}"])
            if "redis" in content.lower():
                add("Redis", "Cache/Broker", [f"redis service in {path}"])

    # Test frameworks by presence of test dirs/config
    for p in tree_paths:
        base = os.path.basename(p).lower()
        if base in ("pytest.ini", "conftest.py") or (base.startswith("pytest") and base.endswith(".cfg")):
            add("pytest", "Testing", [f"Found: {p}"])
            break
    if any("jest.config" in p.lower() for p in tree_paths):
        add("Jest", "Testing", ["Found jest.config"])
    if any(p.endswith(("vitest.config.ts", "vitest.config.js")) for p in tree_paths):
        add("Vitest", "Testing", ["Found vitest.config"])

    # Deduplicate by name
    seen = set()
    unique = []
    for d in detected:
        if d["name"].lower() not in seen:
            seen.add(d["name"].lower())
            unique.append(d)
    return unique


# ── Layer detection ──────────────────────────────────────────────────

def _detect_layers(tree_paths: list[str]) -> list[dict]:
    """Detect architectural layers from actual directory structure."""
    top_dirs: set[str] = set()
    for p in tree_paths:
        parts = p.split("/")
        if len(parts) > 1:
            top_dirs.add(parts[0].lower())

    layer_markers = {
        "frontend/ui": {"frontend", "client", "ui", "web", "views", "pages", "components"},
        "backend/api": {"backend", "api", "server", "routers", "routes", "controllers", "views"},
        "services/domain": {"services", "domain", "core", "business", "usecases"},
        "data/models": {"models", "entities", "repositories", "db", "database", "dao"},
        "tests": {"tests", "test", "spec", "__tests__"},
        "scripts/tooling": {"scripts", "tools", "bin"},
        "docs": {"docs", "documentation"},
        "infrastructure": {"infra", "infrastructure", "deploy", "k8s", "terraform"},
    }
    layers = []
    for layer_name, markers in layer_markers.items():
        matched = sorted(top_dirs & markers)
        if matched:
            layers.append({"layer": layer_name, "evidence_directories": matched})
    return layers


# ── Component detection ──────────────────────────────────────────────

def _detect_components(tree_paths: list[str]) -> list[dict]:
    """Main modules/components from directory structure + entry points."""
    dir_file_counts: dict[str, int] = defaultdict(int)
    for p in tree_paths:
        parts = p.split("/")
        if len(parts) > 1:
            top = parts[0]
            dir_file_counts[top] += 1
        else:
            dir_file_counts["(root)"] += 1

    components = [
        {"name": d, "file_count": c}
        for d, c in sorted(dir_file_counts.items(), key=lambda x: -x[1])[:12]
        if c >= 2 or d == "(root)"
    ]
    return components


def _detect_entry_points(tree_paths: list[str]) -> list[dict]:
    """Real entry-point candidates: main/app/manage/index files at root or top level."""
    entry_names = {"main.py", "app.py", "manage.py", "wsgi.py", "asgi.py",
                   "index.js", "index.ts", "index.tsx", "main.js", "main.ts",
                   "server.js", "server.ts", "app.js", "app.ts", "cli.py", "__init__.py"}
    entries = []
    for p in tree_paths:
        base = os.path.basename(p)
        if base in entry_names:
            depth = p.count("/")
            if depth <= 2:  # root or shallow package entries
                priority = 0 if depth == 0 else 1
                entries.append({"path": p, "level": "root" if depth == 0 else "package", "priority": priority})
    entries.sort(key=lambda e: (e["priority"], e["path"]))
    return entries[:MAX_ENTRIES]


# ── Internal import graph ────────────────────────────────────────────

_PY_IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.MULTILINE)
_JS_IMPORT = re.compile(r"""(?:import\s+[^'"]*?from\s*|require\s*\(\s*)['"]([^'"]+)['"]""", re.MULTILINE)
_GO_IMPORT = re.compile(r'^\s*"([\w./\-]+)"', re.MULTILINE)


def _build_import_graph(
    files: list[dict],
    known_top_dirs: set[str],
) -> dict:
    """Build module dependency edges from real import statements."""
    edges: list[dict] = []
    external: dict[str, int] = defaultdict(int)
    internal_edges: dict[tuple[str, str], int] = defaultdict(int)

    module_to_top: dict[str, str] = {}
    for f in files:
        path = f["path"]
        parts = path.split("/")
        if len(parts) > 1:
            module_to_top[path] = parts[0]
        else:
            module_to_top[path] = "(root)"

    for f in files:
        path = f["path"]
        content = f.get("content") or ""
        if not content:
            continue
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        imported_names: list[str] = []

        if ext == "py":
            for m in _PY_IMPORT.finditer(content):
                mod = m.group(1) or m.group(2)
                if mod:
                    imported_names.append(mod.split(".")[0])
        elif ext in ("js", "jsx", "ts", "tsx", "mjs", "cjs"):
            for m in _JS_IMPORT.finditer(content):
                spec = m.group(1)
                if spec.startswith("."):
                    # relative import — resolve top dir if possible
                    parts = path.split("/")
                    rel_top = spec.lstrip("./").split("/")[0]
                    target_top = None
                    for i in range(len(parts) - 1, 0, -1):
                        if parts[i] == rel_top or rel_top == "..":
                            target_top = parts[i - 1] if i >= 1 else None
                            break
                    if target_top:
                        imported_names.append(target_top)
                else:
                    # package specifier — may be scoped like @scope/pkg
                    bits = spec.split("/")
                    name = "/".join(bits[:2]) if spec.startswith("@") else bits[0]
                    imported_names.append(name)
        elif ext == "go":
            for m in _GO_IMPORT.finditer(content):
                imported_names.append(m.group(1).split("/")[-1])

        src_top = module_to_top.get(path, "(root)")
        for name in imported_names:
            if not name:
                continue
            if name in known_top_dirs or name in ("(root)",):
                tgt_top = name
                if src_top != tgt_top:
                    internal_edges[(src_top, tgt_top)] += 1
            else:
                external[name] += 1

    for (src, tgt), count in internal_edges.items():
        edges.append({"from": src, "to": tgt, "imports": count})
    edges.sort(key=lambda e: -e["imports"])

    externals = [
        {"package": name, "import_count": count}
        for name, count in sorted(external.items(), key=lambda x: -x[1])[:25]
    ]
    return {"internal_edges": edges[:MAX_IMPORT_EDGES], "external_imports": externals}


# ── Concerns (evidence-based) ────────────────────────────────────────

def _detect_concerns(tree_paths: list[str], graph: dict, layers: list[dict]) -> list[dict]:
    concerns = []
    layer_names = {l["layer"] for l in layers}

    # God-component: one top dir dominating the file count
    if tree_paths:
        counts: dict[str, int] = defaultdict(int)
        for p in tree_paths:
            counts[p.split("/")[0]] += 1
        total = sum(counts.values())
        if total >= 30:
            top, c = max(counts.items(), key=lambda x: x[1])
            if c / total > 0.6:
                concerns.append({
                    "concern": f"'{top}/' contains {c} of {total} files ({int(c / total * 100)}% of the tree).",
                    "evidence": [f"{top}/: {c} files"],
                    "suggestion": "Consider splitting this directory into cohesive sub-modules.",
                })

    # Cyclic dependency between top-level modules
    edge_list = graph.get("internal_edges", [])
    pair_set = {(e["from"], e["to"]) for e in edge_list}
    seen_cycles = set()
    for (a, b) in pair_set:
        if (b, a) in pair_set and a < b and (a, b) not in seen_cycles:
            seen_cycles.add((a, b))
            concerns.append({
                "concern": f"Mutual imports between '{a}' and '{b}' suggest a possible cycle at module level.",
                "evidence": [f"{a} → {b}", f"{b} → {a}"],
                "suggestion": "Extract shared types/utilities into a lower-level module both can depend on.",
            })

    # Mixed frontend/backend in one flat root
    if "frontend/ui" not in layer_names and "backend/api" not in layer_names:
        jsish = sum(1 for p in tree_paths if p.endswith((".ts", ".tsx", ".jsx")))
        pyish = sum(1 for p in tree_paths if p.endswith(".py"))
        if jsish and pyish:
            concerns.append({
                "concern": f"Both JavaScript/TypeScript ({jsish} files) and Python ({pyish} files) sources exist without a clear top-level separation.",
                "evidence": [f".py files: {pyish}", ".ts/.tsx/.jsx files: " + str(jsish)],
                "suggestion": "If these are separate apps (e.g. backend + frontend), consider isolating them in dedicated directories.",
            })

    return concerns


# ── Orchestrator ─────────────────────────────────────────────────────

def analyze_architecture(fetcher: RepoSourceFetcher) -> dict:
    """Full architecture analysis from real repo data. Never raises."""
    tree_items = fetcher.get_tree_items()
    tree_paths = [item.path for item in tree_items if not is_ignored_path(item.path)]

    # Fetch manifest contents for framework detection
    manifest_contents: dict[str, str] = {}
    try:
        for manifest in fetcher.list_manifest_paths():
            content = fetcher.fetch_content(manifest["path"])
            if content:
                manifest_contents[manifest["path"]] = content
    except Exception as exc:
        logger.error(f"Manifest fetch failed during architecture analysis: {exc}")

    # Fetch a subset of source files for import graph (reuse fetch budget)
    source_files: list[dict] = []
    try:
        candidates = [p for p in fetcher.list_source_paths()][:60]
        for candidate in candidates:
            content = fetcher.fetch_content(candidate["path"])
            if content:
                source_files.append({"path": candidate["path"], "content": content})
    except Exception as exc:
        logger.error(f"Source fetch failed during architecture analysis: {exc}")

    manifest_pkgs = _manifest_dep_versions(manifest_contents)
    frameworks = _detect_frameworks(tree_paths, manifest_pkgs, manifest_contents)
    layers = _detect_layers(tree_paths)
    components = _detect_components(tree_paths)
    entries = _detect_entry_points(tree_paths)
    known_top_dirs = {c["name"] for c in components} | {p.split("/")[0] for p in tree_paths if "/" in p}
    graph = _build_import_graph(source_files, known_top_dirs)
    concerns = _detect_concerns(tree_paths, graph, layers)

    languages: dict[str, int] = defaultdict(int)
    ext_lang = {"py": "Python", "js": "JavaScript", "jsx": "JavaScript", "mjs": "JavaScript",
                "ts": "TypeScript", "tsx": "TypeScript", "java": "Java", "go": "Go",
                "rb": "Ruby", "rs": "Rust", "php": "PHP", "cs": "C#"}
    for p in tree_paths:
        ext = p.rsplit(".", 1)[-1].lower() if "." in p else ""
        if ext in ext_lang:
            languages[ext_lang[ext]] += 1

    structure_summary = {
        "total_files": len(tree_paths),
        "directories": sorted({p.rsplit("/", 1)[0] for p in tree_paths if "/" in p})[:40],
        "tree_truncated": fetcher.truncated,
    }

    return {
        "summary": {
            "note": "All components, frameworks and relationships below were detected from actual repository files. Nothing is inferred without evidence.",
            "structure": structure_summary,
            "languages": dict(sorted(languages.items(), key=lambda x: -x[1])),
        },
        "frameworks": frameworks,
        "layers": layers,
        "components": components,
        "entry_points": [e["path"] for e in entries],
        "internal_dependencies": graph["internal_edges"],
        "external_dependencies": graph["external_imports"],
        "concerns": concerns,
    }
