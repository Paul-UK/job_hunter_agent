from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_DIR = Path(__file__).resolve().parent
os.environ.setdefault("JOB_AGENT_DATABASE_URL", f"sqlite:///{TEST_DIR / 'test_app.db'}")
os.environ.setdefault("JOB_AGENT_DATA_DIR", str(TEST_DIR / "data"))
os.environ.setdefault("JOB_AGENT_ARTIFACTS_DIR", str(TEST_DIR / "artifacts"))
os.environ.setdefault("JOB_AGENT_DEFAULT_DRY_RUN", "true")

from apps.api.app.db import Base, engine  # noqa: E402
from apps.api.app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def reset_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client
