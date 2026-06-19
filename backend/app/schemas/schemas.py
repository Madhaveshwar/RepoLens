from pydantic import BaseModel, EmailStr
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime

# Auth Schemas
class UserCreate(BaseModel):
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class UserOut(BaseModel):
    id: UUID
    email: EmailStr
    created_at: datetime
    has_github_pat: bool
    has_groq_api_key: bool
    has_openai_api_key: bool = False
    has_claude_api_key: bool = False
    has_gemini_api_key: bool = False
    has_openrouter_api_key: bool = False
    llm_default_provider: Optional[str] = None
    llm_default_model: Optional[str] = None
    llm_temperature: Optional[float] = None
    llm_max_tokens: Optional[int] = None

    class Config:
        from_attributes = True

class CredentialsUpdate(BaseModel):
    github_pat: Optional[str] = None
    groq_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    claude_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    llm_default_provider: Optional[str] = None
    llm_default_model: Optional[str] = None
    llm_temperature: Optional[float] = None
    llm_max_tokens: Optional[int] = None

class ValidateFixRequest(BaseModel):
    analysis_id: UUID
    file_path: str
    original_content: str
    edited_content: str

class ValidateFixResponse(BaseModel):
    status: str  # "fixed", "partially_fixed", "not_fixed"
    details: str
    remaining_issues: List[Dict[str, Any]] = []

class DeployInstructionsRequest(BaseModel):
    analysis_id: UUID
    branch: str = "main"

class DeployInstructionsResponse(BaseModel):
    steps: List[str]
    commit_suggestion: str
    pr_title_suggestion: str
    pr_description_suggestion: str

class GitPushRequest(BaseModel):
    repository_id: UUID
    file_path: str
    file_content: str
    commit_message: str
    branch: str = "main"

# API Key Schemas
class ApiKeyCreate(BaseModel):
    name: str

class ApiKeyOut(BaseModel):
    id: UUID
    name: str
    key_prefix: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

class ApiKeyGenerated(ApiKeyOut):
    plain_key: str

# Repository Schemas
class RepositoryConnect(BaseModel):
    url: str

class RepositoryOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    stars: int
    forks: int
    open_prs_count: int
    open_issues_count: int
    default_branch: str
    languages: Optional[Dict[str, Any]] = None
    is_connected: Optional[bool] = True
    last_scanned_at: Optional[datetime] = None
    latest_risk_score: Optional[int] = None
    permissions: Optional[Dict[str, bool]] = None
    created_at: datetime

    class Config:
        from_attributes = True

# PR Schemas
class PullRequestOut(BaseModel):
    id: UUID
    number: int
    title: str
    author: str
    state: str
    additions: int
    deletions: int
    head_sha: str
    base_sha: str
    created_at: datetime

    class Config:
        from_attributes = True

# Analysis & Finding Schemas
class AnalysisTrigger(BaseModel):
    repository_id: UUID
    pr_number: Optional[int] = None

class AnalysisOut(BaseModel):
    id: UUID
    repository_id: UUID
    pull_request_id: Optional[UUID] = None
    status: str
    progress: int
    risk_score: int
    latency_seconds: int
    estimated_token_usage: int
    files_analyzed_count: int
    characters_analyzed_count: int
    groq_requests_made: int
    cached_results_used: int
    model_name: Optional[str] = None
    prompt_tokens: Optional[int] = 0
    completion_tokens: Optional[int] = 0
    total_tokens: Optional[int] = 0
    scan_duration_seconds: Optional[int] = 0
    insights: Optional[str] = None
    timestamp: datetime

    class Config:
        from_attributes = True

class SecurityFindingOut(BaseModel):
    id: UUID
    analysis_id: UUID
    file: str
    line: int
    severity: str
    issue: str
    why_it_matters: Optional[str] = None
    risk_level: Optional[str] = None
    suggestion: str
    before_code: Optional[str] = None
    after_code: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    code_snippet: Optional[str] = None
    issue_explanation: Optional[str] = None

    class Config:
        from_attributes = True

class CodeSmellOut(BaseModel):
    id: UUID
    analysis_id: UUID
    file: str
    line: int
    severity: str
    issue: str
    why_it_matters: Optional[str] = None
    risk_level: Optional[str] = None
    suggestion: str
    before_code: Optional[str] = None
    after_code: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    code_snippet: Optional[str] = None
    issue_explanation: Optional[str] = None

    class Config:
        from_attributes = True

class TestSuggestionOut(BaseModel):
    id: UUID
    analysis_id: UUID
    file: str
    content: str

    class Config:
        from_attributes = True

class HealthScoreOut(BaseModel):
    id: UUID
    analysis_id: UUID
    health_score: int
    deductions: Optional[List[str]] = None
    readme_exists: bool
    large_files: Optional[List[Dict[str, Any]]] = None
    security_hotspots: Optional[List[Dict[str, Any]]] = None
    missing_tests: Optional[List[str]] = None
    test_files_count: int
    source_files_count: int
    docstring_coverage: int

    class Config:
        from_attributes = True

# Report Schemas
class ReportOut(BaseModel):
    id: UUID
    analysis_id: UUID
    type: str
    created_at: datetime

    class Config:
        from_attributes = True

# Combined Dashboard Metrics Schema
class DashboardMetrics(BaseModel):
    repositories_count: int
    prs_count: int
    vulnerabilities_count: int
    avg_health_score: float
    security_score: float
    security_score_history: List[Dict[str, Any]]
    severity_distribution: Dict[str, int]
    vulnerability_trends: List[Dict[str, Any]]
    health_history: List[Dict[str, Any]]
    recent_activity: List[Dict[str, Any]]
    top_risky_repositories: List[Dict[str, Any]]
    average_scan_duration: float
    token_consumption: Dict[str, int]
    model_usage: Dict[str, int]

# Local Snippet review
class SnippetReviewRequest(BaseModel):
    code: str
    language: str

class SnippetReviewOut(BaseModel):
    risk_score: int
    findings: List[Dict[str, Any]]
    test_suggestions: str
    severity_counts: Dict[str, int]
    latency_seconds: float
    scores: Dict[str, int]
    is_valid_code: bool
    detected_language: Optional[str] = None
    optimization_required: Optional[bool] = None
    optimized_code: Optional[str] = None
    quality_score: Optional[int] = None
    validation_message: Optional[str] = None

class AuditLogOut(BaseModel):
    id: UUID
    user_id: Optional[UUID] = None
    action: str
    details: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class DeadLetterTaskOut(BaseModel):
    id: UUID
    task_id: str
    task_name: str
    arguments: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    stack_trace: Optional[str] = None
    failed_at: datetime
    resolved: bool
    resolved_at: Optional[datetime] = None

    class Config:
        from_attributes = True

