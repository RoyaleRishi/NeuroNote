"""Unit tests for tenant-scoped session dependency."""
from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.core.auth import UserContext
from app.db.tenant_session import get_tenant_graph_name, get_tenant_session


def _fake_request(schema_name: str = "user_abc123") -> MagicMock:
    """Build a mock Request whose cookies carry a fake access token.

    We patch ``get_current_user`` instead of constructing real JWTs, so the
    cookie content is irrelevant — the mock just needs the Request shape.
    """
    req = MagicMock()
    req.cookies = {"neuronote_access": "fake-token"}
    return req


# -- get_tenant_session -------------------------------------------------------


def test_get_tenant_session_yields_session(
    configured_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On SQLite the dependency yields a usable session (search_path skipped)."""
    user = UserContext(user_id="u1", email="a@b.com", schema_name="user_abc123")
    monkeypatch.setattr(
        "app.db.tenant_session.get_current_user", lambda _req: user
    )

    req = _fake_request()
    gen: Iterator = get_tenant_session(req)
    session = next(gen)

    from sqlalchemy.orm import Session

    assert isinstance(session, Session)

    # Clean up the generator.
    try:
        next(gen)
    except StopIteration:
        pass


def test_get_tenant_session_invalid_schema_raises(
    configured_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An invalid schema_name in the JWT must be rejected before opening a session."""
    bad_user = UserContext(
        user_id="u2", email="bad@b.com", schema_name="DROP TABLE users;--"
    )
    monkeypatch.setattr(
        "app.db.tenant_session.get_current_user", lambda _req: bad_user
    )

    req = _fake_request(schema_name="DROP TABLE users;--")
    with pytest.raises(ValueError, match="Invalid schema name"):
        gen = get_tenant_session(req)
        next(gen)


def test_get_tenant_session_empty_schema_raises(
    configured_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty schema_name must be rejected."""
    bad_user = UserContext(user_id="u3", email="empty@b.com", schema_name="")
    monkeypatch.setattr(
        "app.db.tenant_session.get_current_user", lambda _req: bad_user
    )

    req = _fake_request(schema_name="")
    with pytest.raises(ValueError, match="must not be empty"):
        gen = get_tenant_session(req)
        next(gen)


def test_get_tenant_session_no_auth_raises(configured_db: None) -> None:
    """Without a valid cookie the auth layer raises 401 before we touch the DB."""
    req = MagicMock()
    req.cookies = {}

    with pytest.raises(HTTPException) as exc_info:
        gen = get_tenant_session(req)
        next(gen)
    assert exc_info.value.status_code == 401


# -- get_tenant_graph_name ----------------------------------------------------


def test_get_tenant_graph_name_returns_correct_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Graph name follows ``nn_{schema_name}`` convention."""
    user = UserContext(user_id="u1", email="a@b.com", schema_name="user_abc123")
    monkeypatch.setattr(
        "app.db.tenant_session.get_current_user", lambda _req: user
    )

    req = _fake_request()
    assert get_tenant_graph_name(req) == "nn_user_abc123"


def test_get_tenant_graph_name_invalid_schema_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid schema names are rejected even for graph name lookups."""
    bad_user = UserContext(
        user_id="u2", email="bad@b.com", schema_name="not-valid!"
    )
    monkeypatch.setattr(
        "app.db.tenant_session.get_current_user", lambda _req: bad_user
    )

    req = _fake_request()
    with pytest.raises(ValueError, match="Invalid schema name"):
        get_tenant_graph_name(req)
