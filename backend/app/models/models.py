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

    repository = relationship("Repository", back_populates="analyses")
    pull_request = relationship("PullRequest", back_populates="analyses")
    security_findings = relationship("SecurityFinding", back_populates="analysis", cascade="all, delete-orphan")
    code_smells = relationship("CodeSmell", back_populates="analysis", cascade="all, delete-orphan")
    test_suggestions = relationship("TestSuggestion", back_populates="analysis", cascade="all, delete-orphan")
    health_scores = relationship("HealthScore", back_populates="analysis", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="analysis", cascade="all, delete-orphan")

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
