import os
# Force required env vars for tests before importing backend app
os.environ["JWT_SECRET"] = "test_jwt_secret_key_for_testing_only_12345"
os.environ["ENCRYPTION_KEY"] = "u-3M1t-H3VnJzLox58pZf4lX3z4P4hGZ8Z0K2S-2U_w="
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///test.db"
os.environ["SYNC_DATABASE_URL"] = "sqlite:///test.db"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["TESTING"] = "1"

import pytest
import asyncio
from typing import Generator
from fastapi.testclient import TestClient
from backend.app.database.database import Base, sync_engine
from backend.app.main import app

@pytest.fixture(scope="session", autouse=True)
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    # Create SQLite tables
    Base.metadata.create_all(bind=sync_engine)
    yield
    Base.metadata.drop_all(bind=sync_engine)
    # Remove test.db if it exists
    if os.path.exists("test.db"):
        try:
            os.remove("test.db")
        except Exception:
            pass

@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def anyio_backend():
    return "asyncio"

