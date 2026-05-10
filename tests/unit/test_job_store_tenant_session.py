"""Regression: job_store must use the caller's tenant-bound Session.

Previously the public helpers opened a fresh session via
``get_session_factory()()``, bypassing the caller's
``bind_session_to_tenant`` and causing INSERTs to land in ``public``.
These tests pin the contract: every public helper executes against the
session it was given.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.core import job_store


class _FakeResult:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self._rows = rows or []

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        return self._rows


class _FakeSession:
    """Captures execute() calls; mimics enough of Session for job_store."""

    def __init__(self, rows: list[Any] | None = None) -> None:
        self.executed: list[tuple[str, dict[str, Any] | None]] = []
        self.committed = 0
        self._next_rows = rows or []

    def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        self.executed.append((str(stmt), params))
        rows = self._next_rows
        self._next_rows = []  # one-shot
        return _FakeResult(rows)

    def commit(self) -> None:
        self.committed += 1


@pytest.fixture(autouse=True)
def _force_postgres_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force job_store to take the Postgres branch so we exercise the SQL path."""
    monkeypatch.setattr(job_store, "_is_postgres", lambda: True)


def test_create_or_get_job_uses_passed_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """create_or_get_job must execute on the passed session, not open a new one."""
    # Trip-wire: if the helper opens its own session, this raises.
    def _no_factory():  # pragma: no cover - defensive
        raise AssertionError("job_store opened its own session instead of using the caller's")

    monkeypatch.setattr(job_store, "_get_session", _no_factory)

    session = _FakeSession(rows=[])  # SELECT returns empty → INSERT path
    record, created = job_store.create_or_get_job(
        session,  # type: ignore[arg-type]
        note_id="note-x",
        content_hash="hash-x",
    )

    assert created is True
    assert record.status == "queued"
    # Two statements: SELECT existing, then INSERT.
    assert len(session.executed) == 2
    select_sql, _ = session.executed[0]
    insert_sql, _ = session.executed[1]
    assert "SELECT" in select_sql.upper()
    assert "INSERT INTO PROCESSING_JOBS" in insert_sql.upper()
    assert session.committed >= 1


def test_mark_job_completed_uses_passed_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_store, "_get_session", lambda: (_ for _ in ()).throw(
        AssertionError("opened own session")
    ))
    row = ("job-1", "completed", None, "2026-01-01", "2026-01-01", None)
    session = _FakeSession(rows=[row])

    result = job_store.mark_job_completed(
        session,  # type: ignore[arg-type]
        "job-1",
    )

    assert result is not None
    assert result.status == "completed"
    sql, _ = session.executed[0]
    assert "UPDATE PROCESSING_JOBS" in sql.upper()
    assert session.committed >= 1


def test_get_job_uses_passed_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_store, "_get_session", lambda: (_ for _ in ()).throw(
        AssertionError("opened own session")
    ))
    row = ("job-2", "running", None, "2026-01-01", "2026-01-01", None)
    session = _FakeSession(rows=[row])

    result = job_store.get_job(session, "job-2")  # type: ignore[arg-type]

    assert result is not None
    assert result.job_id == "job-2"
    sql, _ = session.executed[0]
    assert "SELECT" in sql.upper()
