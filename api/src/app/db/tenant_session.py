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
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.db.engine import get_session_factory
from app.db.tenant import validate_schema_name


def get_tenant_session(request: Request) -> Iterator[Session]:
    """Yield a SQLAlchemy session scoped to the authenticated user's tenant schema.

    On PostgreSQL the session's ``search_path`` is set to
    ``{schema_name}, public`` so ORM queries hit the correct tenant tables.
    On SQLite (test environments) the search_path step is skipped because
    SQLite has no schema support.
    """
    user = get_current_user(request)
    validate_schema_name(user.schema_name)

    session_factory = get_session_factory()
    with session_factory() as session:
        url = str(session.get_bind().url)
        if url.startswith("postgresql"):
            # SET search_path is a session-level command in PostgreSQL — it
            # persists across transactions on the same connection.  Execute it
            # then commit so the auto-begun transaction is closed; route handlers
            # that call session.begin() will start a fresh transaction with the
            # search_path already active.
            session.execute(
                text(f"SET search_path TO {user.schema_name}, public")
            )
            session.commit()
        yield session


def get_tenant_graph_name(request: Request) -> str:
    """Return the AGE graph name for the authenticated user's tenant.

    Routes that perform Cypher queries against Apache AGE use this to resolve
    the per-user graph (``nn_user_<id>``).
    """
    user = get_current_user(request)
    validate_schema_name(user.schema_name)
    return f"nn_{user.schema_name}"
