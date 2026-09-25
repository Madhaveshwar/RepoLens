import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from app.services.security_scanner import scan_security, parse_json_from_llm
from app.services.code_smell_detector import detect_code_smells
from app.services.test_generator import generate_tests
from app.services.github_service import GitHubService
from app.websockets.websocket_manager import ConnectionManager
import json

# --- PARSER TESTS ---

def test_parse_json_from_llm():
    raw_response = '```json\n[{"issue": "SQL Injection", "line": 10}]\n```'
    parsed = parse_json_from_llm(raw_response)
    assert len(parsed) == 1
    assert parsed[0]["issue"] == "SQL Injection"

    raw_response_dict = '{"issue": "XSS", "line": 20}'
    parsed_dict = parse_json_from_llm(raw_response_dict)
    assert len(parsed_dict) == 1
    assert parsed_dict[0]["issue"] == "XSS"

    assert parse_json_from_llm("") == []

# --- SCANNERS & DETECTORS TESTS ---

def test_scan_security_service():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content='[{"issue": "Hardcoded Secret detected in source code", "line": 1, "severity": "Critical", "suggestion": "Move the secret to an environment variable and access it via os.getenv()", "why_it_matters": "Hardcoded secrets in source code can be exposed if the repository is compromised"}]'))
    ]
    mock_client.chat.completions.create.return_value = mock_response

    res = scan_security(mock_client, "app.py", "secret = '123'", "", "Python")
    assert len(res) >= 1
    assert res[0]["issue"] == "Hardcoded Secret detected in source code"
    assert res[0]["severity"] == "Critical"

def test_detect_code_smells_service():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content='[{"issue": "Long Function detected in the source", "line": 1, "severity": "High", "suggestion": "Break this long function into smaller, focused functions that each do one thing well to improve readability", "why_it_matters": "Long functions are harder to understand, test, and maintain, violating single responsibility principles"}]'))
    ]
    mock_client.chat.completions.create.return_value = mock_response

    res = detect_code_smells(mock_client, "app.py", "def long(): pass", "", "Python")
    assert len(res) >= 1
    assert "Long Function" in res[0]["issue"]
    assert res[0]["severity"] == "High"

def test_generate_tests_service():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content="def test_hello(): assert True"))
    ]
    mock_client.chat.completions.create.return_value = mock_response

    res = generate_tests(mock_client, "app.py", "def hello(): pass", "Python")
    assert "test_hello" in res

# --- GITHUB SERVICE TESTS ---

@patch("app.services.github_service.Github")
def test_github_service_metadata(mock_github_class):
    mock_repo = MagicMock()
    mock_repo.description = "My test description"
    mock_repo.stargazers_count = 10
    mock_repo.forks_count = 5
    mock_repo.open_issues_count = 8
    mock_repo.default_branch = "main"
    mock_repo.get_languages.return_value = {"Python": 100}

    mock_pr = MagicMock()
    mock_pr.number = 42
    mock_pr.title = "Fix PR"
    mock_pr.user.login = "bot"
    mock_pr.state = "open"
    mock_pr.additions = 10
    mock_pr.deletions = 2
    mock_pr.head.sha = "sha1"
    mock_pr.base.sha = "sha2"

    mock_pulls = MagicMock()
    mock_pulls.totalCount = 1
    mock_pulls.__iter__.return_value = [mock_pr]
    mock_repo.get_pulls.return_value = mock_pulls

    mock_github_class.return_value.get_repo.return_value = mock_repo

    service = GitHubService(token="dummy-pat")
    details = service.get_repo_details("owner/repo")
    assert details["stars"] == 10
    assert details["description"] == "My test description"

    prs = service.get_open_pull_requests("owner/repo")
    assert len(prs) == 1
    assert prs[0]["number"] == 42

# --- WEBSOCKET CONNECTION MANAGER TESTS ---

@pytest.mark.anyio
async def test_websocket_manager_connect():
    manager = ConnectionManager()
    mock_ws = MagicMock()
    mock_ws.accept = AsyncMock()
    
    # Check websocket mock methods
    await manager.connect(mock_ws)
    assert mock_ws in manager.active_connections
    
    manager.disconnect(mock_ws)
    assert mock_ws not in manager.active_connections


# --- ADDITIONAL SERVICES TESTS (COVERAGE ENHANCEMENT) ---

def test_analyze_repository():
    from app.services.repository_analyzer import analyze_repository
    
    mock_gh_service = MagicMock()
    mock_gh_client = MagicMock()
    mock_gh_service.client = mock_gh_client
    
    mock_repo = MagicMock()
    mock_repo.default_branch = "main"
    mock_gh_client.get_repo.return_value = mock_repo
    
    mock_branch = MagicMock()
    mock_branch.commit.sha = "commitsha123"
    mock_repo.get_branch.return_value = mock_branch
    
    item_readme = MagicMock(path="README.md", type="blob", size=1024)
    item_reqs = MagicMock(path="requirements.txt", type="blob", size=512)
    item_main = MagicMock(path="main.py", type="blob", size=2048)
    item_test = MagicMock(path="tests/test_main.py", type="blob", size=1024)
    
    mock_git_tree = MagicMock()
    mock_git_tree.tree = [item_readme, item_reqs, item_main, item_test]
    mock_repo.get_git_tree.return_value = mock_git_tree
    
    def mock_get_content(repo, path, branch):
        if path == "requirements.txt":
            return "requests<2.20.0\npytest"
        elif path == "main.py":
            return '"""This is a docstring"""\ndef main(): pass'
        return ""
    mock_gh_service.get_file_content.side_effect = mock_get_content
    
    # Mock Groq client
    mock_groq = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content="Mock analysis report string"))
    ]
    mock_groq.chat.completions.create.return_value = mock_response
    
    res = analyze_repository(
        client=mock_groq,
        github_service=mock_gh_service,
        repo_name="owner/repo",
    )
    
    assert res["health_score"] > 0
    assert res["readme_exists"] is True
    assert res["source_files_count"] == 1
    assert "Mock analysis report string" in res["analysis_report"]


def test_handle_groq_error():
    from app.services.reviewer import handle_groq_error, GroqAPIError
    
    err1 = Exception("unauthorized 401 api key invalid")
    resolved1 = handle_groq_error(err1)
    assert isinstance(resolved1, GroqAPIError)
    # Friendly messages must point the user at Settings, never leak raw errors.
    assert "Settings" in str(resolved1)
    assert "API key" in str(resolved1)
    
    err2 = Exception("rate limit exceeded 429 quota")
    resolved2 = handle_groq_error(err2)
    assert isinstance(resolved2, GroqAPIError)
    assert "rate limit" in str(resolved2).lower()
    assert "try again" in str(resolved2).lower()
    
    err3 = Exception("model not found")
    resolved3 = handle_groq_error(err3)
    assert isinstance(resolved3, GroqAPIError)
    assert "model" in str(resolved3).lower()
    assert "Settings" in str(resolved3)


def test_groq_model_fallback_chain():
    """Groq defaults must be valid free-tier models (no Enterprise-only fallbacks)."""
    from app.services.llm_client import (
        PROVIDER_DEFAULT_MODELS,
        PROVIDER_FALLBACK_MODELS,
        GROQ_FALLBACK_MODEL,
        get_model_name,
        is_model_not_found_error,
        is_auth_error,
        is_rate_limit_error,
        create_chat_completion,
    )

    # The default Groq model must NOT be one that 404s on free accounts.
    assert get_model_name("groq", None) == PROVIDER_DEFAULT_MODELS["groq"]
    assert PROVIDER_DEFAULT_MODELS["groq"] not in ("", None)
    # The legacy Enterprise-only fallback must not be the only fallback option.
    assert GROQ_FALLBACK_MODEL in PROVIDER_FALLBACK_MODELS["groq"]
    assert len(PROVIDER_FALLBACK_MODELS["groq"]) >= 2
    # User-saved model preference must be respected.
    assert get_model_name("groq", "openai/gpt-oss-20b") == "openai/gpt-oss-20b"
    # Other providers keep their defaults.
    assert get_model_name("openai", None) == "gpt-4o-mini"


def test_model_error_classification():
    from app.services.llm_client import (
        is_model_not_found_error,
        is_auth_error,
        is_rate_limit_error,
    )

    assert is_model_not_found_error(Exception(
        "Error code: 404 - {'error': {'message': 'The model llama-3.1-8b-instant does not exist or you do not have access to it.'}}"
    ))
    assert is_model_not_found_error(Exception("model gpt-x has been decommissioned"))
    assert not is_model_not_found_error(Exception("connection refused"))

    assert is_auth_error(Exception("Error code: 401 - invalid api key"))
    assert not is_auth_error(Exception("model not found"))

    assert is_rate_limit_error(Exception("Error code: 429 - rate_limit_exceeded"))
    assert not is_rate_limit_error(Exception("Error code: 401 - unauthorized"))


def test_create_chat_completion_falls_back_on_model_error():
    """If the primary model 404s, create_chat_completion must retry a fallback model."""
    from app.services.llm_client import create_chat_completion
    from unittest.mock import MagicMock

    client = MagicMock()
    ok_response = MagicMock()
    ok_response.choices[0].message.content = "ok"

    # First call (primary model) raises 404 model-not-found; second (fallback) succeeds.
    client.chat.completions.create.side_effect = [
        Exception("Error code: 404 - model 'foo' does not exist or you do not have access to it."),
        ok_response,
    ]

    result = create_chat_completion(
        client=client, provider="groq",
        messages=[{"role": "user", "content": "hi"}],
        model="llama-3.1-8b-instant",
    )
    assert result.choices[0].message.content == "ok"
    assert client.chat.completions.create.call_count == 2

    # Non-model errors must propagate immediately (no blind retries).
    client2 = MagicMock()
    client2.chat.completions.create.side_effect = Exception("Error code: 401 - invalid api key")
    import pytest as _pytest
    with _pytest.raises(Exception, match="401"):
        create_chat_completion(
            client=client2, provider="groq",
            messages=[{"role": "user", "content": "hi"}],
            model="openai/gpt-oss-120b",
        )


def test_review_pull_request():
    from app.services.reviewer import review_pull_request
    
    mock_gh_service = MagicMock()
    mock_gh_service.get_pr_details.return_value = {"head_sha": "headsha", "base_sha": "basesha"}
    mock_gh_service.get_pr_files.return_value = [
        {"filename": "main.py", "patch": "@@ -1,1 +1,1 @@\n+print('hello')", "status": "modified"}
    ]
    mock_gh_service.get_file_content.return_value = "print('hello')"
    mock_gh_service.get_modified_lines.return_value = {1}
    
    mock_groq = MagicMock()
    mock_response = MagicMock()
    
    response_json = {
        "files_reviews": {
            "main.py": {
                "security_findings": [
                    {
                        "line": 1,
                        "severity": "High",
                        "issue": "SQL Injection",
                        "why_it_matters": "Insecure query",
                        "suggestion": "Use parameters",
                        "before_code": "sql = ...",
                        "after_code": "sql_param = ..."
                    }
                ],
                "code_smells": [
                    {
                        "line": 1,
                        "severity": "Low",
                        "issue": "Long function",
                        "why_it_matters": "Too long",
                        "suggestion": "Split it",
                        "before_code": "def func():...",
                        "after_code": "def split():..."
                    }
                ],
                "inline_comments": [
                    {
                        "line": 1,
                        "severity": "Medium",
                        "category": "Performance",
                        "issue": "Inefficient loop",
                        "why_it_matters": "O(N)",
                        "suggestion": "Optimize it",
                        "before_code": "for x...",
                        "after_code": "for y..."
                    }
                ],
                "test_suggestions": "Test case details",
                "severity_score": 50,
                "scores": {
                    "code_quality": 80,
                    "security": 70,
                    "maintainability": 75,
                    "performance": 85,
                    "technical_debt": 20
                }
            }
        },
        "repository_insights": "Nice repo insights"
    }
    
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps(response_json)))
    ]
    mock_groq.chat.completions.create.return_value = mock_response
    
    res = review_pull_request(
        repo_name="owner/repo",
        pr_number=5,
        github_service=mock_gh_service,
        client=mock_groq
    )
    
    assert res["risk_score"] > 0
    assert len(res["findings"]) == 3
    assert "Test case details" in res["test_suggestions"]


def test_review_entire_repository():
    from app.services.reviewer import review_entire_repository
    
    mock_gh_service = MagicMock()
    mock_gh_client = MagicMock()
    mock_gh_service.client = mock_gh_client
    
    mock_repo = MagicMock()
    mock_repo.default_branch = "main"
    # review_entire_repository resolves the Repository via the service's
    # cached get_repo_object() helper.
    mock_gh_service.get_repo_object.return_value = mock_repo
    
    mock_branch = MagicMock()
    mock_branch.commit.sha = "commitsha123"
    mock_repo.get_branch.return_value = mock_branch
    
    item_main = MagicMock(path="main.py", type="blob", size=2048)
    mock_git_tree = MagicMock()
    mock_git_tree.tree = [item_main]
    mock_repo.get_git_tree.return_value = mock_git_tree
    
    mock_gh_service.get_file_content.return_value = "def my_func(): pass"
    
    # Mock Groq client
    mock_groq = MagicMock()
    mock_response = MagicMock()
    
    response_json = {
        "files_reviews": {
            "main.py": {
                "security_findings": [],
                "code_smells": [],
                "inline_comments": [],
                "test_suggestions": "Unit tests recommendations",
                "severity_score": 0,
                "scores": {}
            }
        },
        "repository_insights": "Repo-level suggestions"
    }
    
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps(response_json)))
    ]
    mock_groq.chat.completions.create.return_value = mock_response
    
    res = review_entire_repository(
        repo_name="owner/repo",
        github_service=mock_gh_service,
        client=mock_groq
    )
    
    assert res["total_files_analyzed"] == 1
    assert "Repo-level suggestions" in res["repo_analysis"]["analysis_report"]


def test_review_single_code_snippet():
    from app.services.reviewer import review_single_code_snippet
    
    mock_groq = MagicMock()
    mock_response = MagicMock()
    
    response_json = {
        "security_findings": [
            {
                "line": 1,
                "severity": "Medium",
                "issue": "XSS",
                "suggestion": "Sanitize inputs",
                "why_it_matters": "Context injection",
                "risk_level": "Medium",
                "before_code": "unsafe",
                "after_code": "safe"
            }
        ],
        "code_smells": [],
        "inline_comments": [],
        "test_suggestions": "Snippet test suggestions",
        "severity_score": 30,
        "optimization_required": True,
        "optimized_code": "def hello(): return escape('hello')",
        "scores": {
            "code_quality": 70,
            "security": 60,
            "maintainability": 80,
            "performance": 90,
            "technical_debt": 10
        }
    }
    
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps(response_json)))
    ]
    mock_groq.chat.completions.create.return_value = mock_response
    
    res = review_single_code_snippet(
        code="def hello(): return 'hello'",
        language="Python",
        client=mock_groq
    )
    
    assert res["risk_score"] > 0
    assert len(res["findings"]) == 1
    assert res["is_valid_code"] is True
    assert res["optimization_required"] is True
    assert res["optimized_code"] == "def hello(): return escape('hello')"


def test_review_snippet_valid_python():
    from app.services.reviewer import review_single_code_snippet
    
    mock_groq = MagicMock()
    mock_response = MagicMock()
    
    response_json = {
        "security_findings": [],
        "code_smells": [],
        "inline_comments": [],
        "test_suggestions": "Mock test cases for Python",
        "severity_score": 0,
        "optimization_required": False,
        "optimized_code": None,
        "scores": {
            "code_quality": 95,
            "security": 100,
            "maintainability": 90,
            "performance": 95,
            "technical_debt": 5
        }
    }
    
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps(response_json)))
    ]
    mock_groq.chat.completions.create.return_value = mock_response
    
    python_code = """
def calculate_area(width, height):
    return width * height
"""
    res = review_single_code_snippet(python_code, "Auto", mock_groq)
    assert res["is_valid_code"] is True
    assert res["detected_language"] == "Python"
    assert res["optimization_required"] is False
    assert res["optimized_code"] is None
    assert res["quality_score"] == 95


def test_review_snippet_valid_javascript():
    from app.services.reviewer import review_single_code_snippet
    
    mock_groq = MagicMock()
    mock_response = MagicMock()
    
    response_json = {
        "security_findings": [],
        "code_smells": [],
        "inline_comments": [],
        "test_suggestions": "Mock JS tests",
        "severity_score": 0,
        "optimization_required": False,
        "optimized_code": None,
        "scores": {
            "code_quality": 98,
            "security": 100,
            "maintainability": 95,
            "performance": 98,
            "technical_debt": 0
        }
    }
    
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps(response_json)))
    ]
    mock_groq.chat.completions.create.return_value = mock_response
    
    js_code = """
const greet = (name) => {
    console.log(`Hello, ${name}`);
    return `Hello, ${name}`;
};
"""
    res = review_single_code_snippet(js_code, "Auto", mock_groq)
    assert res["is_valid_code"] is True
    assert res["detected_language"] == "JavaScript"
    assert res["optimization_required"] is False
    assert res["quality_score"] == 98


def test_review_snippet_random_english_text():
    from app.services.reviewer import review_single_code_snippet
    mock_groq = MagicMock()
    
    english_text = "This is just a simple paragraph of English text. It is not code. There are no programming statements here."
    res = review_single_code_snippet(english_text, "Auto", mock_groq)
    assert res["is_valid_code"] is False
    assert "prose" in res["validation_message"].lower() or "text" in res["validation_message"].lower()
    mock_groq.chat.completions.create.assert_not_called()


def test_review_snippet_empty_input():
    from app.services.reviewer import review_single_code_snippet
    mock_groq = MagicMock()
    
    res = review_single_code_snippet("   \n  \t ", "Python", mock_groq)
    assert res["is_valid_code"] is False
    assert "empty" in res["validation_message"].lower()
    mock_groq.chat.completions.create.assert_not_called()


def test_review_snippet_already_optimized():
    from app.services.reviewer import review_single_code_snippet
    
    mock_groq = MagicMock()
    mock_response = MagicMock()
    
    response_json = {
        "security_findings": [],
        "code_smells": [],
        "inline_comments": [],
        "test_suggestions": "Test templates",
        "severity_score": 0,
        "optimization_required": False,
        "optimized_code": None,
        "scores": {
            "code_quality": 100,
            "security": 100,
            "maintainability": 100,
            "performance": 100,
            "technical_debt": 0
        }
    }
    
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps(response_json)))
    ]
    mock_groq.chat.completions.create.return_value = mock_response
    
    code = "def get_pi():\n    return 3.14159\n"
    res = review_single_code_snippet(code, "Python", mock_groq)
    assert res["is_valid_code"] is True
    assert res["optimization_required"] is False
    assert res["optimized_code"] is None
    assert res["quality_score"] == 100


def test_review_snippet_poor_quality():
    from app.services.reviewer import review_single_code_snippet
    
    mock_groq = MagicMock()
    mock_response = MagicMock()
    
    response_json = {
        "security_findings": [
            {
                "line": 2,
                "severity": "Critical",
                "issue": "SQL Injection",
                "why_it_matters": "Direct SQL injection vulnerability",
                "risk_level": "Critical",
                "suggestion": "Use parameters",
                "before_code": "execute(query)",
                "after_code": "execute(query, params)"
            }
        ],
        "code_smells": [
            {
                "line": 4,
                "severity": "Low",
                "issue": "Magic strings",
                "why_it_matters": "Cognitive load",
                "risk_level": "Low",
                "suggestion": "Constant variable",
                "before_code": "conn = 'admin'",
                "after_code": "ADMIN_USER = 'admin'"
            }
        ],
        "inline_comments": [],
        "test_suggestions": "Suggested tests",
        "severity_score": 60,
        "optimization_required": True,
        "optimized_code": "def safe_query(db, user):\n    db.execute('SELECT * FROM users WHERE name = %s', (user,))\n",
        "scores": {
            "code_quality": 40,
            "security": 30,
            "maintainability": 50,
            "performance": 70,
            "technical_debt": 60
        }
    }
    
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps(response_json)))
    ]
    mock_groq.chat.completions.create.return_value = mock_response
    
    poor_code = "def query(db, user):\n    db.execute('SELECT * FROM users WHERE name = ' + user)\n"
    res = review_single_code_snippet(poor_code, "Python", mock_groq)
    assert res["is_valid_code"] is True
    assert res["optimization_required"] is True
    assert res["optimized_code"] is not None
    assert "safe_query" in res["optimized_code"]
    assert len(res["findings"]) == 2


def test_report_generator_all(tmp_path):
    from app.services.report_generator import (
        generate_markdown_report,
        generate_json_report,
        generate_csv_report,
        generate_pdf_report,
    )
    
    report_data = {
        "repo_name": "owner/repo",
        "pr_number": 42,
        "timestamp": "2026-06-15 12:00 UTC",
        "risk_score": 45,
        "findings": [
            {
                "file": "main.py",
                "line": 10,
                "severity": "High",
                "category": "Security",
                "issue": "SQL Injection",
                "why_it_matters": "Direct interpolation",
                "suggestion": "Use parameterized query",
                "before_code": "execute('...' + param)",
                "after_code": "execute('...', (param,))"
            },
            {
                "file": "utils.py",
                "line": 20,
                "severity": "Low",
                "category": "Code Smell",
                "issue": "Magic numbers",
                "why_it_matters": "Poor maintainability",
                "suggestion": "Use constants",
                "before_code": "x = 3.14",
                "after_code": "PI = 3.14"
            }
        ],
        "test_suggestions": "### File: main.py\n- Test SQL injection boundary conditions",
        "repo_analysis": {
            "health_score": 85,
            "analysis_report": "Overall structure looks standard.",
            "source_files_count": 5,
            "test_files_count": 2,
            "docstring_coverage": 75
        },
        "files_analyzed_log": [
            {"file": "main.py", "type": "Python", "status": "Analyzed", "findings": 1},
            {"file": "utils.py", "type": "Python", "status": "Analyzed", "findings": 1}
        ],
        "scores": {
            "code_quality": 80,
            "security": 70,
            "maintainability": 75,
            "performance": 85,
            "technical_debt": 20
        }
    }
    
    md_report = generate_markdown_report(report_data)
    assert "# RepoLens AI Report - owner/repo" in md_report
    assert "SQL Injection" in md_report
    
    json_report = generate_json_report(report_data)
    assert '"risk_score": 45' in json_report
    
    csv_report = generate_csv_report(report_data)
    assert "SQL Injection" in csv_report
    
    pdf_file = tmp_path / "report.pdf"
    generate_pdf_report(report_data, str(pdf_file))
    assert pdf_file.exists()


# --- GITHUB SERVICE ADDITIONAL UNIT TESTS ---

def test_parse_repo_url_edge_cases():
    from app.services.github_service import parse_repo_url
    assert parse_repo_url(None) is None
    assert parse_repo_url("") is None
    assert parse_repo_url("owner/repo") == "owner/repo"
    assert parse_repo_url("https://github.com/owner/repo.git") == "owner/repo"
    assert parse_repo_url("git@github.com:owner/repo.git") == "owner/repo"
    assert parse_repo_url("github.com/owner/repo") == "owner/repo"
    assert parse_repo_url("https://github.com/owner/repo/tree/main") == "owner/repo"
    assert parse_repo_url("https://github.com/org/sub/owner/repo") == "org/sub"
    assert parse_repo_url("invalid-url") is None


@patch("app.services.github_service.Github")
def test_github_service_constructor_no_token(mock_github_class):
    service = GitHubService(token=None)
    mock_github_class.assert_called_once()
    assert service.token is None


@patch("app.services.github_service.Github")
def test_github_service_get_repo_details_exceptions(mock_github_class):
    from github import GithubException
    mock_client = MagicMock()
    mock_github_class.return_value = mock_client
    
    # Case 1: Repo not found (404)
    mock_client.get_repo.side_effect = GithubException(404, {"message": "Not Found"})
    service = GitHubService(token="dummy")
    with pytest.raises(ValueError) as exc:
        service.get_repo_details("owner/repo")
    assert "Repository not found" in str(exc.value)

    # Case 2: Rate limit (403)
    mock_client.get_repo.side_effect = GithubException(403, {"message": "Rate limit"})
    with pytest.raises(ValueError) as exc:
        service.get_repo_details("owner/repo")
    assert "rate limit exceeded" in str(exc.value)

    # Case 3: Other Error (500)
    mock_client.get_repo.side_effect = GithubException(500, {"message": "Internal Server Error"})
    with pytest.raises(ValueError) as exc:
        service.get_repo_details("owner/repo")
    assert "GitHub API Error" in str(exc.value)

    # Case 4: Default branch empty or branch lookup 404
    mock_client.get_repo.side_effect = None
    mock_repo = MagicMock()
    mock_repo.default_branch = ""
    mock_repo.full_name = "owner/repo"
    mock_repo.description = "desc"
    mock_repo.stargazers_count = 0
    mock_repo.forks_count = 0
    mock_repo.get_languages.return_value = {}
    mock_repo.open_issues_count = 5
    mock_repo.get_pulls.return_value.totalCount = 2
    mock_client.get_repo.return_value = mock_repo
    details = service.get_repo_details("owner/repo")
    assert details["is_empty"] is True

    # Case 5: Branch check throws 404
    mock_repo.default_branch = "main"
    mock_repo.get_branch.side_effect = GithubException(404, {"message": "Branch not found"})
    details = service.get_repo_details("owner/repo")
    assert details["is_empty"] is True

    # Case 6: Branch check throws other error
    mock_repo.get_branch.side_effect = GithubException(500, {"message": "Generic error"})
    with pytest.raises(ValueError):
        service.get_repo_details("owner/repo")


@patch("app.services.github_service.Github")
def test_github_service_get_pr_files(mock_github_class):
    mock_client = MagicMock()
    mock_github_class.return_value = mock_client
    mock_repo = MagicMock()
    mock_client.get_repo.return_value = mock_repo
    mock_pr = MagicMock()
    mock_repo.get_pull.return_value = mock_pr
    
    mock_file = MagicMock()
    mock_file.filename = "app.py"
    mock_file.additions = 5
    mock_file.deletions = 2
    mock_file.changes = 7
    mock_file.status = "modified"
    mock_file.patch = None
    mock_file.raw_url = "http://raw"
    mock_pr.get_files.return_value = [mock_file]
    
    service = GitHubService("dummy")
    files = service.get_pr_files("owner/repo", 1)
    assert len(files) == 1
    assert files[0]["filename"] == "app.py"
    assert files[0]["patch"] == ""


@patch("app.services.github_service.Github")
def test_github_service_get_file_content_scenarios(mock_github_class):
    mock_client = MagicMock()
    mock_github_class.return_value = mock_client
    mock_repo = MagicMock()
    mock_client.get_repo.return_value = mock_repo
    
    service = GitHubService("dummy")
    
    # Content is a list (directory instead of file)
    mock_repo.get_contents.return_value = [MagicMock()]
    content = service.get_file_content("owner/repo", "dir", "main")
    assert content == ""
    
    # Exception thrown
    mock_repo.get_contents.side_effect = Exception("failed")
    content = service.get_file_content("owner/repo", "app.py", "main")
    assert content == ""


def test_github_service_diff_logic():
    service = GitHubService("dummy")
    
    # 1. get_modified_lines
    assert service.get_modified_lines("") == set()
    
    patch_str = (
        "@@ -1,3 +1,4 @@\n"
        " line1\n"
        "+line2 added\n"
        "-line3 removed\n"
        " line4\n"
    )
    lines = service.get_modified_lines(patch_str)
    assert lines == {2}
    
    # 2. find_diff_position
    assert service.find_diff_position("", 5) is None
    
    patch_str_2 = (
        "@@ -1,3 +1,3 @@\n"
        " line1\n"
        "-line2\n"
        "+line2_new\n"
        " line3\n"
    )
    # The first line (line1) is unchanged. line2 is at target line 2.
    # Diff starts at @@ line (diff_line_count starts at 1 for hunk header).
    # line1: diff_line_count=2, current_new_line=1
    # -line2: diff_line_count=3, no new line increment.
    # +line2_new: diff_line_count=4, current_new_line=2. Since current_new_line==2, returns 4.
    pos = service.find_diff_position(patch_str_2, 2)
    assert pos == 4
    
    # Check invalid match case where match is None
    patch_invalid = "@@ -invalid @@\n+line"
    assert service.find_diff_position(patch_invalid, 1) == 2


@patch("app.services.github_service.Github")
def test_github_service_comments_logic(mock_github_class):
    mock_client = MagicMock()
    mock_github_class.return_value = mock_client
    mock_repo = MagicMock()
    mock_client.get_repo.return_value = mock_repo
    mock_pr = MagicMock()
    mock_repo.get_pull.return_value = mock_pr
    
    # post_comment success
    service = GitHubService("dummy")
    assert service.post_comment("owner/repo", 1, "body") is True
    
    # post_comment exception
    mock_repo.get_pull.side_effect = Exception("error")
    assert service.post_comment("owner/repo", 1, "body") is False
    mock_repo.get_pull.side_effect = None
    
    # post_inline_comments no token
    service_no_token = GitHubService(None)
    posted, failed = service_no_token.post_inline_comments("owner/repo", 1, [{"file": "app.py"}])
    assert posted == 0
    assert failed == 1
    
    # post_inline_comments empty commits
    mock_pr.get_commits.return_value = []
    posted, failed = service.post_inline_comments("owner/repo", 1, [{"file": "app.py"}])
    assert posted == 0
    assert failed == 1
    
    # post_inline_comments happy path
    mock_pr.get_commits.return_value = [MagicMock()]
    inline_comments = [
        {"file": "app.py", "line": 10, "body": "Comment"},
        {"file": "", "line": 5, "body": "Invalid comment"}
    ]
    posted, failed = service.post_inline_comments("owner/repo", 1, inline_comments)
    assert posted == 1
    assert failed == 1
    
    # post_inline_comments exception when creating comment
    mock_pr.create_review_comment.side_effect = Exception("failed inline")
    posted, failed = service.post_inline_comments("owner/repo", 1, [{"file": "app.py", "line": 10, "body": "Comment"}])
    assert posted == 0
    assert failed == 1
    
    # Exception on top level
    mock_pr.get_commits.side_effect = Exception("top level error")
    posted, failed = service.post_inline_comments("owner/repo", 1, [{"file": "app.py", "line": 10, "body": "Comment"}])
    assert posted == 0
    assert failed == 1


@pytest.mark.anyio
async def test_listen_to_redis_channel():
    from app.websockets.websocket_manager import listen_to_redis_channel
    
    mock_ws = AsyncMock()
    mock_ws.send_text = AsyncMock()
    
    # Mock redis
    mock_redis_client = AsyncMock()
    mock_pubsub = AsyncMock()
    
    # Set up mock pubsub messages
    # First call returns None, second returns progress message, third returns completion message
    mock_pubsub.get_message.side_effect = [
        None,
        {"type": "message", "data": b'{"status": "analyzing", "progress": 50}'},
        {"type": "message", "data": b'{"status": "completed", "progress": 100}'}
    ]
    
    mock_redis_client.pubsub = MagicMock(return_value=mock_pubsub)
    
    with patch("app.websockets.websocket_manager.aioredis.from_url", return_value=mock_redis_client):
        await listen_to_redis_channel("analysis_123", mock_ws)
        
    # Assert subscribe/unsubscribe and close
    mock_pubsub.subscribe.assert_called_once_with("analysis_progress_analysis_123")
    mock_pubsub.unsubscribe.assert_called_once_with("analysis_progress_analysis_123")
    mock_redis_client.close.assert_called_once()
    
    # Verify mock_ws send_text calls
    assert mock_ws.send_text.call_count == 2


@pytest.mark.anyio
async def test_listen_to_redis_channel_disconnect():
    from app.websockets.websocket_manager import listen_to_redis_channel
    from fastapi import WebSocketDisconnect
    
    mock_ws = AsyncMock()
    mock_ws.send_text.side_effect = WebSocketDisconnect()
    
    mock_redis_client = AsyncMock()
    mock_pubsub = AsyncMock()
    mock_pubsub.get_message.return_value = {"type": "message", "data": b'{"status": "analyzing", "progress": 50}'}
    mock_redis_client.pubsub = MagicMock(return_value=mock_pubsub)
    
    with patch("app.websockets.websocket_manager.aioredis.from_url", return_value=mock_redis_client):
        await listen_to_redis_channel("analysis_123", mock_ws)
        
    mock_pubsub.unsubscribe.assert_called_once_with("analysis_progress_analysis_123")


def test_is_valid_code():
    from app.utils.validation import is_valid_code
    
    # False cases
    assert is_valid_code(None) is False
    assert is_valid_code("") is False
    assert is_valid_code("   ") is False
    assert is_valid_code("short") is False
    assert is_valid_code("123456789012") is False
    assert is_valid_code("!!!@@@###$$$") is False
    assert is_valid_code("line without keyword or structure") is False
    
    # True cases
    assert is_valid_code("def my_func():\n    return True") is True
    assert is_valid_code("const x = 5;\nconsole.log(x);") is True
    assert is_valid_code("class Foo:\n    pass") is True
    assert is_valid_code("# comment\n// comment\nimport os") is True


def test_should_skip_file():
    from app.utils.validation import should_skip_file
    
    # Skip cases
    assert should_skip_file("node_modules/index.js") is True
    assert should_skip_file("dist/bundle.js") is True
    assert should_skip_file("build/main.js") is True
    assert should_skip_file("my-project/coverage/lcov.info") is True
    assert should_skip_file(".git/config") is True
    assert should_skip_file("package-lock.json") is True
    assert should_skip_file("jquery.min.js") is True
    assert should_skip_file("generated_code.py") is True
    assert should_skip_file("webpack.config.js") is True
    assert should_skip_file("main.js.map") is True
    assert should_skip_file("image.png") is True
    assert should_skip_file("document.pdf") is True
    assert should_skip_file("data.db") is True
    
    # Don't skip cases
    assert should_skip_file("app/main.py") is False
    assert should_skip_file("src/components/Sidebar.tsx") is False


