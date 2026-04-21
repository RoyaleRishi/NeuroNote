from __future__ import annotations

from collections.abc import Iterator
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
API_SRC = ROOT / "api" / "src"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))


@pytest.fixture()
def configured_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    external_db_url = os.getenv("TEST_DATABASE_URL")
    if external_db_url:
        monkeypatch.setenv("DATABASE_URL", external_db_url)
    else:
        test_db_path = tmp_path / "api-test.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{test_db_path}")
    monkeypatch.setenv("DB_AUTO_CREATE", "true")
    monkeypatch.setenv("REQUIRE_DB_EXTENSIONS", "false")

    from app.db.engine import initialize_database, reset_engine
    from app.core.backfill_store import reset_backfill_status
    from app.core.job_store import reset_job_store

    reset_engine()
    reset_job_store()
    reset_backfill_status()
    initialize_database()
    yield
    reset_job_store()
    reset_backfill_status()
    reset_engine()


@pytest.fixture()
def client(configured_db: None) -> Iterator[TestClient]:
    from app.main import app
    from app.core.auth import UserContext, get_current_user
    from app.db.session import get_db_session
    from app.db.tenant_session import get_tenant_session

    # Override auth + tenant session for tests: no JWT required, no schema scoping.
    _fake_user = UserContext(user_id="test-user", email="test@test.com", schema_name="user_test0001")

    app.dependency_overrides[get_current_user] = lambda: _fake_user
    app.dependency_overrides[get_tenant_session] = get_db_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_tenant_session, None)


@pytest.fixture()
def db_session(configured_db: None) -> Iterator["Session"]:
    from app.db.engine import get_session_factory

    factory = get_session_factory()
    with factory() as session:
        yield session
