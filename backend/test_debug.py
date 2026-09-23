"""Debug celery task test failure."""
import os
os.environ["JWT_SECRET"] = "test_jwt_secret_key_for_testing_only_12345"
os.environ["ENCRYPTION_KEY"] = "u-3M1t-H3VnJzLox58pZf4lX3z4P4hGZ8Z0K2S-2U_w="
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///test.db"
os.environ["SYNC_DATABASE_URL"] = "sqlite:///test.db"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["TESTING"] = "1"

from unittest.mock import patch, MagicMock
from app.database.database import SessionLocal, Base, sync_engine
from app.models.models import User, Repository, Analysis

# Setup DB
Base.metadata.create_all(bind=sync_engine)

# Create user and repo
db = SessionLocal()
user = User(email="debug@test.com")
user.hashed_password = "$2b$12$test"
db.add(user)
db.commit()

repo = Repository(user_id=user.id, name="debug/repo", default_branch="main")
db.add(repo)
db.commit()

analysis = Analysis(repository_id=repo.id, status="pending", progress=0)
db.add(analysis)
db.commit()

analysis_id = str(analysis.id)
db.close()

from app.tasks.tasks import run_analysis_task

with patch("app.tasks.tasks.redis_client", MagicMock()):
    with patch("app.tasks.tasks.GitHubService") as mock_gh:
        with patch("app.tasks.tasks.build_llm_client") as mock_llm:
            with patch("app.tasks.tasks.review_entire_repository") as mock_review:
                with patch("app.tasks.tasks.os.makedirs", MagicMock()):
                    with patch("app.tasks.tasks.generate_pdf_report", MagicMock()):
                        with patch("builtins.open", MagicMock()):
                            mock_review.return_value = {
                                "risk_score": 10, "latency_seconds": 12,
                                "estimated_token_usage": 1500, "files_analyzed_count": 5,
                                "characters_analyzed_count": 8000, "groq_requests_made": 3,
                                "cached_results_used": 1,
                                "token_stats": {"model_name": "test", "prompt_tokens": 800, "completion_tokens": 700, "total_tokens": 1500},
                                "findings": [],
                                "test_suggestions": "test",
                                "repo_analysis": {"health_score": 92, "deductions": [], "readme_exists": True,
                                    "large_files": [], "security_hotspots": [], "missing_tests": [],
                                    "test_files_count": 1, "source_files_count": 4, "docstring_coverage": 80}
                            }
                            try:
                                result = run_analysis_task(analysis_id)
                                print(f"Result: {result}")
                            except Exception as e:
                                import traceback
                                print(f"Exception: {e}")
                                traceback.print_exc()

# Check status
db = SessionLocal()
updated = db.query(Analysis).filter_by(id=analysis.id).first()
print(f"Analysis status: {updated.status}")
print(f"Analysis insights: {updated.insights}")
db.close()

# Cleanup
Base.metadata.drop_all(bind=sync_engine)
if os.path.exists("test.db"):
    os.remove("test.db")
