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

    model_config = {"from_attributes": True}

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

class GitAutomationRequest(BaseModel):
    file_path: str
    file_content: str
    branch_name: str
    commit_message: str = "AI-guided code remediation"
    pr_title: str = "[AI] Automated code fixes"
    pr_description: str = "This PR applies AI-detected code improvements, security patches, and maintainability fixes."

# API Key Schemas
class ApiKeyCreate(BaseModel):
    name: str

class ApiKeyOut(BaseModel):
    id: UUID
    name: str
    key_prefix: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}

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

    model_config = {"from_attributes": True}

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

    model_config = {"from_attributes": True}

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
    health_score: Optional[int] = None
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

    model_config = {"from_attributes": True}

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
    confidence_score: Optional[int] = None

    model_config = {"from_attributes": True}

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
    confidence_score: Optional[int] = None

    model_config = {"from_attributes": True}

class TestSuggestionOut(BaseModel):
    id: UUID
    analysis_id: UUID
    file: str
    content: str

    model_config = {"from_attributes": True}

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

    model_config = {"from_attributes": True}

# Report Schemas
class ReportOut(BaseModel):
    id: UUID
    analysis_id: UUID
    type: str
    created_at: datetime

    model_config = {"from_attributes": True}

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


class FixFindingRequest(BaseModel):
    finding_id: str
    finding_type: str  # "security" | "code_smell" | "test"
    file_path: str
    file_content: str
    issue: str
    severity: str = "Medium"
    suggestion: Optional[str] = None
    before_code: Optional[str] = None
    after_code: Optional[str] = None

class FixFindingResponse(BaseModel):
    fix_type: str
    original_code_snippet: str
    fixed_code_snippet: str
    fixed_full_file: Optional[str] = None
    explanation: str
    start_line: int = 1
    end_line: int = 1
    latency_seconds: float = 0.0


# [REMOVED] FixAllRequest, FixAllFindingItem, FixAllResponse, FixAllAndPrRequest, FixAllAndPrResponse
# These schemas were removed because this project does not modify repositories.


class AuditLogOut(BaseModel):
    id: UUID
    user_id: Optional[UUID] = None
    action: str
    details: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}

class ValidateFixCodeRequest(BaseModel):
    code: str
    file_path: str

class ValidateFixCodeResponse(BaseModel):
    syntax_ok: bool = True
    syntax_error: str = ""
    imports_ok: bool = True
    imports_error: str = ""
    overall_valid: bool = True



class RescanVerifyRequest(BaseModel):
    original_analysis_id: UUID
    rescan_analysis_id: UUID
    mark_resolved: bool = True

class RescanVerifyResponse(BaseModel):
    original_analysis_id: str
    rescan_analysis_id: str
    status: str  # "improved" | "regressed" | "no_change"
    fixed_findings: List[Dict[str, Any]]
    remaining_findings: List[Dict[str, Any]]
    new_findings: List[Dict[str, Any]]
    risk_score_before: int
    risk_score_after: int
    resolved_count: int
    unresolved_count: int

# [REMOVED] ApplyFixRequest, ApplyFixResponse — this project does not modify repositories

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

    model_config = {"from_attributes": True}


# Password Reset Schemas
class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ForgotPasswordResponse(BaseModel):
    message: str
    # Only populated in NON-PRODUCTION environments when email sending is not
    # configured, so local development can complete the reset flow without SMTP.
    dev_reset_url: Optional[str] = None

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str
    confirm_password: str

class ResetPasswordResponse(BaseModel):
    message: str

