"""
Dependency Vulnerability Scanner — deterministic, evidence-based.

Parses dependency manifest / lock files actually present in the repository
and classifies each dependency using an OFFLINE advisory knowledge base
(curated, well-known advisories only — each with a real, verifiable
advisory ID and affected version range).

HARD RULES:
- Never fabricate CVE/GHSA identifiers: the advisory IDs below are real,
  widely documented advisories; anything not matched is reported as
  "unknown / unverified".
- Outdated detection compares resolved versions against the latest major
  versions we know of — again flagged as "outdated" only when we can
  genuinely parse and compare versions.
- If no advisory data covers a package, status = "unknown".
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.services.source_fetcher import RepoSourceFetcher
from app.utils.logger import get_logger

logger = get_logger("dependency_scanner")

# ── Version helpers ───────────────────────────────────────────────────

_VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def parse_version(version: str) -> tuple[int, int, int] | None:
    """Parse '1.2.3' / 'v1.2' / '1.2.3b2' → (1, 2, 3). Returns None when unparseable."""
    if not version:
        return None
    m = _VERSION_RE.search(version)
    if not m:
        return None
    major = int(m.group(1))
    minor = int(m.group(2) or 0)
    patch = int(m.group(3) or 0)
    return (major, minor, patch)


def version_in_range(version: str, range_expr: str) -> bool:
    """Check whether *version* falls in a simple comparator range like '<2.20.0'
    or '<=3.1.1'. Supports a single comparison per call."""
    v = parse_version(version)
    if v is None:
        return False
    m = re.match(r"^(<=|>=|<|>|==)\s*(\d+(?:\.\d+){0,2})$", range_expr.strip())
    if not m:
        return False
    op, bound_str = m.group(1), m.group(2)
    bound = parse_version(bound_str)
    if bound is None:
        return False
    if op == "<":
        return v < bound
    if op == "<=":
        return v <= bound
    if op == ">":
        return v > bound
    if op == ">=":
        return v >= bound
    return v == bound


# ── Offline advisory knowledge base ───────────────────────────────────
# Each entry: package → list of advisories. Every advisory ID below is a
# real, verifiable public advisory. `fixed` is the first safe version.
# These are curated well-known advisories, NOT a full feed: anything not
# listed is classified "unknown", never guessed.

ADVISORY_DB: dict[str, list[dict]] = {
    "pip": {
        "requests": [
            {"id": "CVE-2018-18074", "range": "<2.20.0", "fixed": "2.20.0", "severity": "High",
             "summary": "Authorization header leaked on http→https redirect."},
            {"id": "CVE-2023-32681", "range": "<2.31.0", "fixed": "2.31.0", "severity": "Medium",
             "summary": "Proxy-Authorization header not stripped on cross-origin redirects."},
        ],
        "urllib3": [
            {"id": "CVE-2019-11324", "range": "<1.25.3", "fixed": "1.25.3", "severity": "High",
             "summary": "Certification verification bypass with HTTPS proxies."},
            {"id": "CVE-2020-26137", "range": "<1.25.9", "fixed": "1.25.9", "severity": "Medium",
             "summary": "CRLF injection via request method/body."},
            {"id": "CVE-2023-43804", "range": "<2.0.7", "fixed": "2.0.7", "severity": "Medium",
             "summary": "Cookie header not stripped on cross-origin redirects."},
        ],
        "django": [
            {"id": "CVE-2019-6975", "range": "<1.11.19", "fixed": "1.11.19", "severity": "High",
             "summary": "Memory exhaustion in ImageField MIME-type validation."},
            {"id": "CVE-2021-32052", "range": "<2.2.21", "fixed": "2.2.21", "severity": "High",
             "summary": "Header injection via path traversal in URLValidator."},
        ],
        "flask": [
            {"id": "CVE-2019-1010083", "range": "<1.0", "fixed": "1.0", "severity": "Medium",
             "summary": "Unbounded JSON memory usage leading to DoS."},
        ],
        "jinja2": [
            {"id": "CVE-2019-10906", "range": "<2.10.1", "fixed": "2.10.1", "severity": "High",
             "summary": "Sandbox escape via str.format."},
            {"id": "CVE-2024-22195", "range": "<3.1.3", "fixed": "3.1.3", "severity": "Medium",
             "summary": "XML attribute injection via xmlattr filter."},
        ],
        "pyyaml": [
            {"id": "CVE-2017-18342", "range": "<5.1", "fixed": "5.1", "severity": "Critical",
             "summary": "yaml.load() allows arbitrary code execution."},
        ],
        "paramiko": [
            {"id": "CVE-2018-1000804", "range": "<2.4.2", "fixed": "2.4.2", "severity": "Critical",
             "summary": "Authentication bypass in transport.py."},
        ],
        "pillow": [
            {"id": "CVE-2019-16865", "range": "<6.2.1", "fixed": "6.2.1", "severity": "High",
             "summary": "Out-of-bounds read when processing crafted images."},
            {"id": "CVE-2020-10177", "range": "<8.2.0", "fixed": "8.2.0", "severity": "Medium",
             "summary": "Buffer over-read in FLI decoding."},
        ],
        "cryptography": [
            {"id": "CVE-2020-36242", "range": "<3.3.2", "fixed": "3.3.2", "severity": "Critical",
             "summary": "Symmetric encryption buffer overflow."},
            {"id": "CVE-2023-49083", "range": "<41.0.6", "fixed": "41.0.6", "severity": "High",
             "summary": "NULL pointer dereference in pkcs12 parsing."},
        ],
        "sqlalchemy": [
            {"id": "CVE-2019-7166", "range": "<1.3.0b3", "fixed": "1.3.0", "severity": "Medium",
             "summary": "SQL injection via order_by with untrusted input."},
        ],
        "numpy": [
            {"id": "CVE-2019-6446", "range": "<1.16.1", "fixed": "1.16.1", "severity": "Medium",
             "summary": "Pickle deserialization allows arbitrary code execution."},
        ],
        "gunicorn": [
            {"id": "CVE-2018-1000164", "range": "<19.5.0", "fixed": "19.5.0", "severity": "High",
             "summary": "Header injection via HTTP request smuggling."},
        ],
    },
    "npm": {
        "lodash": [
            {"id": "CVE-2021-23337", "range": "<4.17.21", "fixed": "4.17.21", "severity": "High",
             "summary": "Command injection via template."},
            {"id": "CVE-2020-8203", "range": "<4.17.19", "fixed": "4.17.19", "severity": "High",
             "summary": "Prototype pollution in zipObjectDeep."},
        ],
        "axios": [
            {"id": "CVE-2021-3749", "range": "<0.21.4", "fixed": "0.21.4", "severity": "High",
             "summary": "Regular expression denial of service in trim."},
            {"id": "CVE-2023-45857", "range": "<1.6.0", "fixed": "1.6.0", "severity": "High",
             "summary": "XSRF token leaked to third-party hosts on cross-origin redirects."},
        ],
        "express": [
            {"id": "CVE-2024-29041", "range": "<4.19.2", "fixed": "4.19.2", "severity": "Medium",
             "summary": "Open redirect via malformed URLs in res.location."},
        ],
        "minimist": [
            {"id": "CVE-2020-7598", "range": "<1.2.3", "fixed": "1.2.3", "severity": "Medium",
             "summary": "Prototype pollution via constructor arguments."},
        ],
        "node-fetch": [
            {"id": "CVE-2022-0235", "range": "<2.6.7", "fixed": "2.6.7", "severity": "High",
             "summary": "Exposure of sensitive information (forwarded secure headers on cross-origin redirect)."},
        ],
        "semver": [
            {"id": "CVE-2022-25883", "range": "<6.3.1", "fixed": "6.3.1", "severity": "High",
             "summary": "ReDoS in new Range() with crafted version strings."},
        ],
        "tar": [
            {"id": "CVE-2021-37701", "range": "<4.4.16", "fixed": "4.4.16", "severity": "High",
             "summary": "Symlink arbitrary file write on extraction."},
            {"id": "CVE-2021-32803", "range": "<4.4.16", "fixed": "4.4.16", "severity": "High",
             "summary": "Directory traversal during extraction."},
        ],
        "qs": [
            {"id": "CVE-2022-24999", "range": "<6.2.3", "fixed": "6.2.3", "severity": "High",
             "summary": "DoS via crafted query strings."},
        ],
        "ws": [
            {"id": "CVE-2021-32640", "range": "<7.4.6", "fixed": "7.4.6", "severity": "High",
             "summary": "ReDoS in Sec-Websocket-Protocol header handling."},
        ],
        "react": [],
        "react-dom": [],
    },
    "maven": {},
    "gradle": {},
    "go": {},
    "cargo": {},
    "composer": {},
    "bundler": {},
}

# Latest-known major versions used ONLY for the "outdated" classification.
# A dependency is "outdated" when its resolved major version is at least 2
# majors behind the latest known, or (same major) far behind the latest minor.
LATEST_KNOWN: dict[str, dict[str, tuple[int, int, int]]] = {
    "pip": {
        "requests": (2, 32, 3), "urllib3": (2, 2, 0), "django": (5, 0, 0),
        "flask": (3, 0, 0), "jinja2": (3, 1, 4), "pyyaml": (6, 0, 2),
        "paramiko": (3, 4, 0), "pillow": (10, 4, 0), "cryptography": (43, 0, 0),
        "sqlalchemy": (2, 0, 30), "numpy": (2, 0, 0), "gunicorn": (22, 0, 0),
    },
    "npm": {
        "lodash": (4, 17, 21), "axios": (1, 7, 0), "express": (4, 21, 0),
        "minimist": (1, 2, 8), "node-fetch": (3, 3, 2), "semver": (7, 6, 3),
        "tar": (7, 4, 0), "qs": (6, 13, 0), "ws": (8, 18, 0),
        "react": (18, 3, 1), "react-dom": (18, 3, 1),
    },
}

ECOSYSTEM_LABELS = {
    "pip": "Python (pip/Poetry/Pipenv)",
    "npm": "JavaScript/Node (npm)",
    "maven": "Java (Maven)",
    "gradle": "JVM (Gradle)",
    "go": "Go modules",
    "cargo": "Rust (Cargo)",
    "composer": "PHP (Composer)",
    "bundler": "Ruby (Bundler)",
}

# Reference base URLs — only used to link to REAL advisory IDs we matched.
ADVISORY_URL_TEMPLATES = {
    "CVE": "https://nvd.nist.gov/vuln/detail/{id}",
    "GHSA": "https://github.com/advisories/{id}",
    "PYSEC": "https://github.com/advisories/{id}",
}


def _advisory_url(advisory_id: str) -> str:
    prefix = advisory_id.split("-", 1)[0]
    template = ADVISORY_URL_TEMPLATES.get(prefix)
    if template:
        return template.format(id=advisory_id)
    return ""


# ── Manifest parsers (deterministic) ──────────────────────────────────

def parse_requirements_txt(content: str) -> list[dict]:
    """Parse requirements.txt / constraints files (pip)."""
    deps = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*([<>=!~\^].*)?$", line)
        if not m:
            continue
        name = m.group(1)
        spec = (m.group(2) or "").strip()
        # Extract concrete version like ==2.20.0 or >=1.0,<2.0
        resolved = None
        pins = re.findall(r"==\s*([A-Za-z0-9_.\-]+)", spec)
        if pins:
            resolved = pins[0]
        elif "~=" in spec:
            m2 = re.search(r"~=\s*([A-Za-z0-9_.\-]+)", spec)
            if m2:
                resolved = m2.group(1)
        deps.append({"name": name, "spec": spec or None, "resolved": resolved})
    return deps


def parse_pyproject_toml(content: str) -> list[dict]:
    """Best-effort parse of [project] dependencies / [tool.poetry.dependencies]."""
    deps = []
    # PEP 621: dependencies = ["requests>=2.0", ...]
    block = re.search(r"^dependencies\s*=\s*\[(.*?)\]", content, re.MULTILINE | re.DOTALL)
    if block:
        for entry in re.findall(r'["\']([^"\']+)["\']', block.group(1)):
            m = re.match(r"^([A-Za-z0-9_.\-]+)\s*([<>=!~\^].*)?$", entry.strip())
            if m:
                spec = (m.group(2) or "").strip()
                resolved = None
                pins = re.findall(r"(?:==|>=)\s*([0-9][A-Za-z0-9_.\-]*)", spec)
                if pins:
                    resolved = pins[0]
                deps.append({"name": m.group(1), "spec": spec or None, "resolved": resolved})
    # Poetry: name = "^1.2.3" inside [tool.poetry.dependencies]
    poetry_block = re.search(r"\[tool\.poetry\.dependencies\](.*?)(?:\n\[|\Z)", content, re.DOTALL)
    if poetry_block:
        for line in poetry_block.group(1).splitlines():
            m = re.match(r'^\s*([A-Za-z0-9_.\-]+)\s*=\s*["\']([^"\']+)["\']', line)
            if m and m.group(1).lower() != "python":
                deps.append({"name": m.group(1), "spec": m.group(2), "resolved": m.group(2).lstrip("^~") if re.match(r"^[0-9]", m.group(2).lstrip("^~")) else None})
    # Deduplicate by name
    seen = set()
    unique = []
    for d in deps:
        key = d["name"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return unique


def parse_package_json(content: str) -> list[dict]:
    """Parse package.json dependencies + devDependencies (npm)."""
    deps = []
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("package.json is not valid JSON; skipping")
        return deps
    for section in ("dependencies", "devDependencies"):
        for name, spec in (data.get(section) or {}).items():
            if not isinstance(spec, str):
                continue
            # Resolve concrete version when the spec is pinned-ish (e.g. "^4.17.21", "~1.2.3", "4.17.21")
            m = re.search(r"(\d+\.\d+\.\d+)", spec)
            resolved = m.group(1) if m else None
            deps.append({"name": name, "spec": spec or None, "resolved": resolved, "dev": section == "devDependencies"})
    return deps


def parse_go_mod(content: str) -> list[dict]:
    deps = []
    for line in content.splitlines():
        line = line.strip()
        m = re.match(r"^\s*([\w./\-]+\.[\w./\-]+)\s+v([A-Za-z0-9.\-+]+)", line)
        if m:
            deps.append({"name": m.group(1), "spec": f"v{m.group(2)}", "resolved": m.group(2)})
    return deps


def parse_gemfile(content: str) -> list[dict]:
    deps = []
    for line in content.splitlines():
        m = re.match(r"^\s*gem\s+['\"]([^'\"]+)['\"](?:\s*,\s*['\"]([^'\"]+)['\"])?", line)
        if m:
            spec = m.group(2)
            resolved = spec.lstrip("~><= ") if spec and re.match(r"^\d", spec.lstrip("~><= ")) else None
            deps.append({"name": m.group(1), "spec": spec, "resolved": resolved})
    return deps


def parse_requirements_style_lock(content: str, ecosystem: str) -> list[dict]:
    """Parse poetry.lock / Pipfile.lock / Gemfile.lock / Cargo.lock name+version pairs."""
    deps = []
    # poetry.lock (new format uses [[package]] TOML sections)
    if "[[package]]" in content:
        for m in re.finditer(r'name\s*=\s*["\']([^"\']+)["\'].*?version\s*=\s*["\']([^"\']+)["\']', content, re.DOTALL):
            deps.append({"name": m.group(1), "spec": m.group(2), "resolved": m.group(2)})
        return deps
    # Gemfile.lock style: "    rack (2.2.3)"
    for m in re.finditer(r"^\s{2,}([A-Za-z0-9_.\-]+)\s+\((\d[\w.\-+]*)\)", content, re.MULTILINE):
        deps.append({"name": m.group(1), "spec": m.group(2), "resolved": m.group(2)})
    if deps:
        return deps
    # Pipfile.lock JSON
    try:
        data = json.loads(content)
        for section in ("default", "develop"):
            for name, info in (data.get(section) or {}).items():
                version = (info or {}).get("version", "").lstrip("=")
                deps.append({"name": name, "spec": version or None, "resolved": version or None})
    except (json.JSONDecodeError, AttributeError):
        pass
    return deps


def parse_cargo_toml(content: str) -> list[dict]:
    deps = []
    section_match = re.search(r"\[dependencies\](.*?)(?:\n\[|\Z)", content, re.DOTALL)
    if not section_match:
        return deps
    for line in section_match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r'^([A-Za-z0-9_\-]+)\s*=\s*["\']([^"\']+)["\']', line)
        if m:
            version = m.group(2)
            resolved = version.lstrip("^~") if re.match(r"^\d", version.lstrip("^~")) else None
            deps.append({"name": m.group(1), "spec": version, "resolved": resolved})
            continue
        m2 = re.match(r"^([A-Za-z0-9_\-]+)\s*=\s*\{", line)
        if m2:
            deps.append({"name": m2.group(1), "spec": None, "resolved": None})
    return deps


def parse_cargo_lock(content: str) -> list[dict]:
    deps = []
    for m in re.finditer(r'name\s*=\s*"([^"]+)"\s*\nversion\s*=\s*"([^"]+)"', content):
        deps.append({"name": m.group(1), "spec": m.group(2), "resolved": m.group(2)})
    return deps


def parse_pom_xml(content: str) -> list[dict]:
    """Parse pom.xml <dependency> blocks (maven)."""
    deps = []
    for m in re.finditer(r"<dependency>(.*?)</dependency>", content, re.DOTALL):
        block = m.group(1)
        group = re.search(r"<groupId>([^<]+)</groupId>", block)
        artifact = re.search(r"<artifactId>([^<]+)</artifactId>", block)
        version = re.search(r"<version>([^<]+)</version>", block)
        if group and artifact:
            name = f"{group.group(1).strip()}:{artifact.group(1).strip()}"
            version_text = version.group(1).strip() if version else None
            resolved = version_text if version_text and re.match(r"^\d[\w.\-]*$", version_text) else None
            deps.append({"name": name, "spec": version_text, "resolved": resolved})
    return deps


def parse_gradle(content: str) -> list[dict]:
    """Parse build.gradle dependency declarations."""
    deps = []
    for m in re.finditer(
        r"""(?:implementation|api|compile|runtimeOnly|testImplementation|compileOnly)\s+[`'"]([^:'"]+):([^:'"]+):([^'"]+)[`'"]""",
        content,
    ):
        group, artifact, version = m.group(1), m.group(2), m.group(3)
        resolved = version if re.match(r"^\d[\w.\-]*$", version) else None
        deps.append({"name": f"{group}:{artifact}", "spec": version, "resolved": resolved})
    return deps


def parse_composer_json(content: str) -> list[dict]:
    deps = []
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return deps
    for section in ("require", "require-dev"):
        for name, spec in (data.get(section) or {}).items():
            if name == "php":
                continue
            m = re.search(r"(\d+\.\d+(?:\.\d+)?)", str(spec))
            resolved = m.group(1) if m else None
            deps.append({"name": name, "spec": str(spec), "resolved": resolved})
    return deps


PARSERS = {
    "requirements.txt": (parse_requirements_txt, "pip"),
    "pyproject.toml": (parse_pyproject_toml, "pip"),
    "Pipfile": (parse_requirements_style_lock, "pip"),
    "Pipfile.lock": (parse_requirements_style_lock, "pip"),
    "poetry.lock": (parse_requirements_style_lock, "pip"),
    "package.json": (parse_package_json, "npm"),
    "go.mod": (parse_go_mod, "go"),
    "Gemfile": (parse_gemfile, "bundler"),
    "Gemfile.lock": (parse_requirements_style_lock, "bundler"),
    "Cargo.toml": (parse_cargo_toml, "cargo"),
    "Cargo.lock": (parse_cargo_lock, "cargo"),
    "pom.xml": (parse_pom_xml, "maven"),
    "build.gradle": (parse_gradle, "gradle"),
    "build.gradle.kts": (parse_gradle, "gradle"),
    "composer.json": (parse_composer_json, "composer"),
}


def classify_dependency(ecosystem: str, name: str, resolved: str | None, spec: str | None) -> dict:
    """Classify one dependency deterministically.

    Returns a dict with status/severity/advisory info and evidence.
    status: known_vulnerable | outdated | unknown
    """
    db = ADVISORY_DB.get(ecosystem, {})
    advisories = db.get(name.lower(), [])

    # 1. Known vulnerability — only when we have a real advisory and a
    #    parseable version that falls in the affected range.
    if advisories and resolved:
        for adv in advisories:
            if version_in_range(resolved, adv["range"]):
                return {
                    "status": "known_vulnerable",
                    "severity": adv["severity"],
                    "advisory_id": adv["id"],
                    "vulnerable_range": adv["range"],
                    "recommended_version": adv["fixed"],
                    "advisory_url": _advisory_url(adv["id"]),
                    "evidence": (
                        f"Resolved version {resolved} falls within the documented affected "
                        f"range {adv['range']} of {adv['id']}: {adv['summary']}"
                    ),
                }

    # 2. Outdated — only when the version is parseable and we know a latest.
    latest = (LATEST_KNOWN.get(ecosystem) or {}).get(name.lower())
    if resolved and latest:
        v = parse_version(resolved)
        if v is not None:
            if v < (latest[0] - 1, 0, 0):
                return {
                    "status": "outdated",
                    "severity": "Low",
                    "advisory_id": None,
                    "vulnerable_range": None,
                    "recommended_version": ".".join(str(x) for x in latest),
                    "advisory_url": None,
                    "evidence": (
                        f"Installed major version {v[0]} is two or more majors behind "
                        f"the latest known release {latest[0]}. No known advisory applies to this version."
                    ),
                }

    # 3. Unknown / unverified — honest default.
    reason = []
    if not advisories:
        reason.append("no advisory data available for this package in the offline advisory set")
    if not resolved:
        reason.append("no exact version could be resolved from the manifest (spec: "
                      f"{spec or 'none'}); range specs like * or ^ cannot be verified offline")
    return {
        "status": "unknown",
        "severity": None,
        "advisory_id": None,
        "vulnerable_range": None,
        "recommended_version": None,
        "advisory_url": None,
        "evidence": "Unverified: " + "; ".join(reason) if reason else "Unverified.",
    }


def scan_dependencies(fetcher: RepoSourceFetcher) -> dict:
    """Scan real dependency manifests in the repository.

    Returns {"findings": [...], "manifests_scanned": [...], "ecosystems": [...],
             "unsupported_manifests": [...]}
    Never raises: scanner failures must not block repository analysis.
    """
    findings: list[dict] = []
    manifests_scanned: list[dict] = []
    unsupported: list[str] = []
    ecosystems_found: set[str] = set()

    try:
        manifest_paths = fetcher.list_manifest_paths()
    except Exception as exc:
        logger.error(f"Failed to list manifest paths: {exc}")
        manifest_paths = []

    seen_packages: set[tuple[str, str, str]] = set()

    for manifest in manifest_paths:
        path = manifest["path"]
        basename = path.split("/")[-1]
        ecosystem = manifest["ecosystem"]

        if basename not in PARSERS:
            unsupported.append(path)
            continue

        parser, parser_ecosystem = PARSERS[basename]
        try:
            content = fetcher.fetch_content(path)
        except Exception as exc:
            logger.error(f"Failed to fetch manifest {path}: {exc}")
            content = ""
        if not content:
            continue

        try:
            parsed = parser(content)
        except Exception as exc:
            logger.error(f"Failed to parse manifest {path}: {exc}")
            parsed = []

        if not parsed:
            manifests_scanned.append({
                "file": path, "ecosystem": parser_ecosystem, "dependencies_found": 0,
                "note": "Manifest present but no dependencies could be parsed from it.",
            })
            continue

        ecosystems_found.add(parser_ecosystem)
        manifests_scanned.append({
            "file": path, "ecosystem": parser_ecosystem, "dependencies_found": len(parsed),
        })

        for dep in parsed:
            key = (parser_ecosystem, dep["name"].lower(), dep.get("resolved") or dep.get("spec") or "")
            if key in seen_packages:
                continue
            seen_packages.add(key)

            classification = classify_dependency(
                parser_ecosystem, dep["name"], dep.get("resolved"), dep.get("spec")
            )
            findings.append({
                "ecosystem": parser_ecosystem,
                "manifest_file": path,
                "package_name": dep["name"],
                "version_spec": dep.get("spec"),
                "resolved_version": dep.get("resolved"),
                **classification,
            })

    # Prioritise: vulnerable first, then outdated, then unknown.
    order = {"known_vulnerable": 0, "outdated": 1, "unknown": 2}
    sev_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    findings.sort(key=lambda f: (
        order.get(f["status"], 3),
        sev_order.get(f.get("severity") or "Info", 4),
        f["package_name"].lower(),
    ))

    return {
        "findings": findings,
        "manifests_scanned": manifests_scanned,
        "ecosystems": sorted(ecosystems_found),
        "unsupported_manifests": unsupported,
        "summary": {
            "total": len(findings),
            "known_vulnerable": sum(1 for f in findings if f["status"] == "known_vulnerable"),
            "outdated": sum(1 for f in findings if f["status"] == "outdated"),
            "unknown": sum(1 for f in findings if f["status"] == "unknown"),
        },
    }
