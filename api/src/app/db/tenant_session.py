"""Tenant-scoped SQLAlchemy session dependency for multi-tenant routes.

Extracts the authenticated user's ``schema_name`` from the JWT, validates it,
and configures the session's ``search_path`` so all unqualified table references
resolve to the tenant's isolated schema.

Usage::

    @router.get("/v1/notes")
    async def list_notes(
        session: Session = Depends(get_tenant_session),
    ):
        ...
"""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.db.engine import bind_session_to_tenant, get_session_factory
from app.db.tenant import validate_schema_name


def get_tenant_session(request: Request) -> Iterator[Session]:
    """Yield a SQLAlchemy session scoped to the authenticated user's tenant schema.

    The session's underlying Connection is tagged via
    ``Connection.info["tenant_schema"]``; the engine's
    ``before_cursor_execute`` event reads it and emits
    ``SET search_path TO {schema}, public`` before every SQL
    statement. The binding is cleared on connection checkin so it
    cannot leak to other requests sharing the pool.
    """
    user = get_current_user(request)
    validate_schema_name(user.schema_name)

    session_factory = get_session_factory()
    with session_factory() as session:
        url = str(session.get_bind().url)  # type: ignore[union-attr]
        if url.startswith("postgresql"):
            bind_session_to_tenant(session, user.schema_name)
        yield session


def get_tenant_graph_name(request: Request) -> str:
    """Return the AGE graph name for the authenticated user's tenant.

    Routes that perform Cypher queries against Apache AGE use this to resolve
    the per-user graph (``nn_user_<id>``).
    """
    user = get_current_user(request)
    validate_schema_name(user.schema_name)
    return f"nn_{user.schema_name}"
