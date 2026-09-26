import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Text, JSON, Float
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database.database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    github_pat_encrypted = Column(String, nullable=True)
    groq_api_key_encrypted = Column(String, nullable=True)
    openai_api_key_encrypted = Column(String, nullable=True)
    claude_api_key_encrypted = Column(String, nullable=True)
    gemini_api_key_encrypted = Column(String, nullable=True)
    openrouter_api_key_encrypted = Column(String, nullable=True)
    llm_default_provider = Column(String, default="groq", nullable=True)
    llm_default_model = Column(String, nullable=True)
    llm_temperature = Column(Float, default=0.3, nullable=True)
    llm_max_tokens = Column(Integer, default=4096, nullable=True)
    credentials_verified_at = Column(JSON, nullable=True)  # {"groq": "2026-06-24T17:43:00", ...}
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    repositories = relationship("Repository", back_populates="user", cascade="all, delete-orphan")
    api_keys = relationship("ApiKey", back_populates="user", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="user", cascade="all, delete-orphan")

class ApiKey(Base):
    __tablename__ = "api_keys"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    key_prefix = Column(String, nullable=False)  # e.g. "acr_..."
    hashed_key = Column(String, unique=True, index=True, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="api_keys")

class Repository(Base):
    __tablename__ = "repositories"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)  # e.g. "owner/repo"
    description = Column(Text, nullable=True)
    stars = Column(Integer, default=0)
    forks = Column(Integer, default=0)
    open_prs_count = Column(Integer, default=0)
    open_issues_count = Column(Integer, default=0)
    default_branch = Column(String, default="main")
    languages = Column(JSON, nullable=True)
    is_connected = Column(Boolean, default=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="repositories")
    pull_requests = relationship("PullRequest", back_populates="repository", cascade="all, delete-orphan")
    analyses = relationship("Analysis", back_populates="repository", cascade="all, delete-orphan")
    health_snapshots = relationship("RepositoryHealthSnapshot", cascade="all, delete-orphan")
    pr_reviews = relationship("PullRequestReview", cascade="all, delete-orphan")
    commit_analyses = relationship("CommitAnalysis", cascade="all, delete-orphan")

class PullRequest(Base):
    __tablename__ = "pull_requests"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id"), nullable=False, index=True)
    number = Column(Integer, nullable=False)
    title = Column(String, nullable=False)
    author = Column(String, nullable=False)
    state = Column(String, default="open")  # open, closed, merged
    additions = Column(Integer, default=0)
    deletions = Column(Integer, default=0)
    head_sha = Column(String, nullable=False)
    base_sha = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    repository = relationship("Repository", back_populates="pull_requests")
    analyses = relationship("Analysis", back_populates="pull_request", cascade="all, delete-orphan")

class Analysis(Base):
    __tablename__ = "analyses"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id"), nullable=False, index=True)
    pull_request_id = Column(UUID(as_uuid=True), ForeignKey("pull_requests.id"), nullable=True, index=True)
    status = Column(String, default="pending")  # pending, running, completed, failed
    progress = Column(Integer, default=0)
    risk_score = Column(Integer, default=0)
    latency_seconds = Column(Integer, default=0)
    estimated_token_usage = Column(Integer, default=0)
    files_analyzed_count = Column(Integer, default=0)
    characters_analyzed_count = Column(Integer, default=0)
    groq_requests_made = Column(Integer, default=0)
    cached_results_used = Column(Integer, default=0)
    model_name = Column(String, nullable=True)
    prompt_tokens = Column(Integer, default=0, nullable=True)
    completion_tokens = Column(Integer, default=0, nullable=True)
    total_tokens = Column(Integer, default=0, nullable=True)
    scan_duration_seconds = Column(Integer, default=0, nullable=True)
    insights = Column(Text, nullable=True)
    is_deleted = Column(Boolean, default=False, nullable=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    # ── Snapshot identity: the EXACT repository state this scan analyzed. ──
    # Pinned once at scan start (branch HEAD resolved to a commit SHA) and
    # reused by every feature (explorer, insights, reports, chat) so all
    # views consistently represent the same snapshot.
    commit_sha = Column(String, nullable=True, index=True)
    branch = Column(String, nullable=True)
    # Identity of the analysis configuration that produced this result.
    # Same repository + same commit + same analysis_version ⇒ the persisted
    # result can be reused instead of re-running the LLM.
    analysis_version = Column(String, nullable=True, index=True)

    repository = relationship("Repository", back_populates="analyses")
    pull_request = relationship("PullRequest", back_populates="analyses")
    security_findings = relationship("SecurityFinding", back_populates="analysis", cascade="all, delete-orphan")
    code_smells = relationship("CodeSmell", back_populates="analysis", cascade="all, delete-orphan")
    test_suggestions = relationship("TestSuggestion", back_populates="analysis", cascade="all, delete-orphan")
    health_scores = relationship("HealthScore", back_populates="analysis", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="analysis", cascade="all, delete-orphan")
    dependency_findings = relationship("DependencyFinding", cascade="all, delete-orphan")
    duplicate_findings = relationship("DuplicateCodeFinding", cascade="all, delete-orphan")
    debt_findings = relationship("TechnicalDebtFinding", cascade="all, delete-orphan")
    architecture_analyses = relationship("ArchitectureAnalysis", cascade="all, delete-orphan")
    complexity_findings = relationship("ComplexityFinding", cascade="all, delete-orphan")

class SecurityFinding(Base):
    __tablename__ = "security_findings"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id = Column(UUID(as_uuid=True), ForeignKey("analyses.id"), nullable=False, index=True)
    file = Column(String, nullable=False)
    line = Column(Integer, nullable=False)
    severity = Column(String, nullable=False)  # Critical, High, Medium, Low, Info
    issue = Column(Text, nullable=False)
    why_it_matters = Column(Text, nullable=True)
    risk_level = Column(String, nullable=True)
    suggestion = Column(Text, nullable=False)
    before_code = Column(Text, nullable=True)
    after_code = Column(Text, nullable=True)
    start_line = Column(Integer, nullable=True)
    end_line = Column(Integer, nullable=True)
    code_snippet = Column(Text, nullable=True)
    issue_explanation = Column(Text, nullable=True)
    confidence_score = Column(Integer, default=85, nullable=True)
    source = Column(String, nullable=True)  # ai_analysis | static_analysis

    analysis = relationship("Analysis", back_populates="security_findings")

class CodeSmell(Base):
    __tablename__ = "code_smells"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id = Column(UUID(as_uuid=True), ForeignKey("analyses.id"), nullable=False, index=True)
    file = Column(String, nullable=False)
    line = Column(Integer, nullable=False)
    severity = Column(String, nullable=False)
    issue = Column(Text, nullable=False)
    why_it_matters = Column(Text, nullable=True)
    risk_level = Column(String, nullable=True)
    suggestion = Column(Text, nullable=False)
    before_code = Column(Text, nullable=True)
    after_code = Column(Text, nullable=True)
    start_line = Column(Integer, nullable=True)
    end_line = Column(Integer, nullable=True)
    code_snippet = Column(Text, nullable=True)
    issue_explanation = Column(Text, nullable=True)
    confidence_score = Column(Integer, default=85, nullable=True)
    source = Column(String, nullable=True)  # ai_analysis | static_analysis

    analysis = relationship("Analysis", back_populates="code_smells")

class TestSuggestion(Base):
    __tablename__ = "test_suggestions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id = Column(UUID(as_uuid=True), ForeignKey("analyses.id"), nullable=False, index=True)
    file = Column(String, nullable=False)
    content = Column(Text, nullable=False)  # Markdown block containing tests

    analysis = relationship("Analysis", back_populates="test_suggestions")

class HealthScore(Base):
    __tablename__ = "health_scores"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id = Column(UUID(as_uuid=True), ForeignKey("analyses.id"), nullable=False, index=True)
    health_score = Column(Integer, nullable=False)
    deductions = Column(JSON, nullable=True)
    readme_exists = Column(Boolean, default=False)
    large_files = Column(JSON, nullable=True)
    security_hotspots = Column(JSON, nullable=True)
    missing_tests = Column(JSON, nullable=True)
    test_files_count = Column(Integer, default=0)
    source_files_count = Column(Integer, default=0)
    docstring_coverage = Column(Integer, default=0)

    analysis = relationship("Analysis", back_populates="health_scores")

class Report(Base):
    __tablename__ = "reports"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id = Column(UUID(as_uuid=True), ForeignKey("analyses.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    type = Column(String, nullable=False)  # PDF, Markdown, JSON, CSV
    filepath = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    analysis = relationship("Analysis", back_populates="reports")
    user = relationship("User", back_populates="reports")



class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    action = Column(String, nullable=False)  # e.g., "CONNECT_REPO", "TRIGGER_SCAN", "APPLY_FIX"
    details = Column(JSON, nullable=True)
    ip_address = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")

class DeadLetterTask(Base):
    __tablename__ = "dead_letter_tasks"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(String, nullable=False, index=True)
    task_name = Column(String, nullable=False)
    arguments = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    stack_trace = Column(Text, nullable=True)
    failed_at = Column(DateTime, default=datetime.utcnow)
    resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime, nullable=True)

# ═══════════════════════════════════════════════════════════════════
# Repository Insights Models (health trend, dependencies, duplicates,
# technical debt, architecture, complexity, PR reviews, commit analyses)
# ═══════════════════════════════════════════════════════════════════

class RepositoryHealthSnapshot(Base):
    """One row per completed repository scan so health can be tracked over time.

    Never back-filled with invented data: rows are only created by the
    scan pipeline when a scan actually completes.
    """
    __tablename__ = "repository_health_snapshots"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id"), nullable=False, index=True)
    analysis_id = Column(UUID(as_uuid=True), ForeignKey("analyses.id"), nullable=False, index=True)
    branch = Column(String, nullable=True)
    commit_sha = Column(String, nullable=True)
    health_score = Column(Integer, nullable=False)
    security_score = Column(Integer, nullable=True)
    code_quality_score = Column(Integer, nullable=True)
    code_smell_count = Column(Integer, default=0, nullable=True)
    performance_issue_count = Column(Integer, default=0, nullable=True)
    critical_count = Column(Integer, default=0, nullable=True)
    high_count = Column(Integer, default=0, nullable=True)
    medium_count = Column(Integer, default=0, nullable=True)
    low_count = Column(Integer, default=0, nullable=True)
    total_issue_count = Column(Integer, default=0, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    repository = relationship("Repository")
    analysis = relationship("Analysis")


class DependencyFinding(Base):
    """A single dependency parsed from a real dependency manifest file.

    status distinguishes: known_vulnerable | outdated | unknown.
    advisory_id is only set when a real advisory ID was matched.
    """
    __tablename__ = "dependency_findings"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id = Column(UUID(as_uuid=True), ForeignKey("analyses.id"), nullable=False, index=True)
    ecosystem = Column(String, nullable=False)          # npm, pip, maven, gradle, go, cargo, composer, bundler
    manifest_file = Column(String, nullable=False)      # e.g. "package.json"
    package_name = Column(String, nullable=False)
    version_spec = Column(String, nullable=True)        # spec as written in the manifest
    resolved_version = Column(String, nullable=True)    # exact version when lockfile provides it
    status = Column(String, nullable=False, default="unknown")
    severity = Column(String, nullable=True)            # Critical/High/Medium/Low for known vulns
    advisory_id = Column(String, nullable=True)         # e.g. "GHSA-xxxx" / "CVE-..." when real
    vulnerable_range = Column(String, nullable=True)    # description of affected range
    recommended_version = Column(String, nullable=True)
    advisory_url = Column(String, nullable=True)
    evidence = Column(Text, nullable=True)              # why we classified it this way
    created_at = Column(DateTime, default=datetime.utcnow)

    analysis = relationship("Analysis")


class DuplicateCodeFinding(Base):
    __tablename__ = "duplicate_code_findings"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id = Column(UUID(as_uuid=True), ForeignKey("analyses.id"), nullable=False, index=True)
    file_a = Column(String, nullable=False)
    start_line_a = Column(Integer, nullable=False)
    end_line_a = Column(Integer, nullable=False)
    file_b = Column(String, nullable=False)
    start_line_b = Column(Integer, nullable=False)
    end_line_b = Column(Integer, nullable=False)
    similarity = Column(Integer, nullable=False)        # 0-100
    duplicated_lines = Column(Integer, nullable=False)
    token_hash = Column(String, nullable=True, index=True)  # group clones sharing the same block hash
    snippet = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    analysis = relationship("Analysis")


class TechnicalDebtFinding(Base):
    __tablename__ = "technical_debt_findings"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id = Column(UUID(as_uuid=True), ForeignKey("analyses.id"), nullable=False, index=True)
    category = Column(String, nullable=False)           # code_smell, complexity, duplication, todos, long_functions, large_files, security, dependencies
    severity = Column(String, nullable=False)
    title = Column(String, nullable=False)
    evidence = Column(Text, nullable=False)             # measured facts only
    file = Column(String, nullable=True)
    line_start = Column(Integer, nullable=True)
    line_end = Column(Integer, nullable=True)
    estimated_effort_hours = Column(Float, nullable=True)  # heuristic estimate, always labelled as estimate
    remediation = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    analysis = relationship("Analysis")


class ArchitectureAnalysis(Base):
    __tablename__ = "architecture_analyses"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id = Column(UUID(as_uuid=True), ForeignKey("analyses.id"), nullable=False, index=True)
    result = Column(JSON, nullable=False)               # full evidence-based architecture payload
    created_at = Column(DateTime, default=datetime.utcnow)

    analysis = relationship("Analysis")


class ComplexityFinding(Base):
    __tablename__ = "complexity_findings"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id = Column(UUID(as_uuid=True), ForeignKey("analyses.id"), nullable=False, index=True)
    file = Column(String, nullable=False)
    name = Column(String, nullable=False)               # function/class name
    kind = Column(String, nullable=False, default="function")  # function | method | class
    line_start = Column(Integer, nullable=False)
    line_end = Column(Integer, nullable=True)
    cyclomatic_complexity = Column(Integer, nullable=False)
    nesting_depth = Column(Integer, nullable=True)
    length_lines = Column(Integer, nullable=True)
    language = Column(String, nullable=True)
    severity = Column(String, nullable=False, default="Low")
    explanation = Column(Text, nullable=True)
    suggestion = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    analysis = relationship("Analysis")


class PullRequestReview(Base):
    """Persisted PR review from the dedicated PR review pipeline.

    findings_json keeps the full findings list including the
    `source` field (ai_analysis vs deterministic/static).
    """
    __tablename__ = "pull_request_reviews"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id"), nullable=False, index=True)
    pr_number = Column(Integer, nullable=False, index=True)
    head_sha = Column(String, nullable=True)
    base_branch = Column(String, nullable=True)
    head_branch = Column(String, nullable=True)
    author = Column(String, nullable=True)
    title = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    risk_score = Column(Integer, nullable=True)
    summary = Column(Text, nullable=True)               # AI summary (grounded in actual diff)
    findings_json = Column(JSON, nullable=False, default=list)
    files_changed = Column(Integer, nullable=True)
    additions = Column(Integer, nullable=True)
    deletions = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="completed")
    created_at = Column(DateTime, default=datetime.utcnow)

    repository = relationship("Repository")


class CommitAnalysis(Base):
    """Persisted commit/change analysis (compare commit vs its parent)."""
    __tablename__ = "commit_analyses"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id"), nullable=False, index=True)
    commit_sha = Column(String, nullable=False, index=True)
    parent_sha = Column(String, nullable=True)
    author = Column(String, nullable=True)
    message = Column(Text, nullable=True)
    committed_at = Column(DateTime, nullable=True)
    files_changed = Column(Integer, nullable=True)
    additions = Column(Integer, nullable=True)
    deletions = Column(Integer, nullable=True)
    security_impact = Column(Text, nullable=True)
    quality_impact = Column(Text, nullable=True)
    code_smells_json = Column(JSON, nullable=True, default=list)
    complexity_json = Column(JSON, nullable=True, default=list)
    ai_summary = Column(Text, nullable=True)
    findings_json = Column(JSON, nullable=True, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)

    repository = relationship("Repository")


class AnalysisResultCache(Base):
    """Persistent, deterministic result-reuse store for repository scans.

    Key = repository_id + commit_sha + analysis_version (+ model/provider).
    Value = the full scan summary needed to materialize a completed Analysis
    without calling the LLM again.

    This is the production source of truth for result reuse — NOT the local
    JSON reviewer cache, which Render instances lose on restart/redeploy.
    """
    __tablename__ = "analysis_result_cache"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Part of the natural key; indexed for lookup (uniqueness enforced by the
    # cache_key hash column below).
    repository_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id"), nullable=False, index=True)
    commit_sha = Column(String, nullable=False, index=True)
    analysis_version = Column(String, nullable=False, index=True)
    # sha256(repository_id + commit_sha + analysis_version + model + provider)
    cache_key = Column(String, nullable=False, unique=True, index=True)
    model_name = Column(String, nullable=True)
    provider = Column(String, nullable=True)
    # Full stored result payload (same shape as the scan pipeline output).
    result_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_hit_at = Column(DateTime, nullable=True)
    hit_count = Column(Integer, default=0, nullable=True)

    repository = relationship("Repository")


class PasswordResetToken(Base):
    """Single-use, time-limited password reset tokens.

    Only the SHA-256 hash of the raw token is stored, so a database leak
    cannot be used to reset anyone's password.
    """
    __tablename__ = "password_reset_tokens"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String, unique=True, index=True, nullable=False)  # sha256(raw_token)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)  # set when consumed; NULL = still valid
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")
