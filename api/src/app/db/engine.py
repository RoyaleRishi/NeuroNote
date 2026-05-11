from __future__ import annotations

import re
from contextvars import ContextVar
from threading import Lock

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry

from app.db.config import get_database_settings
from app.db.models import Base

_ENGINE: Engine | None = None
_SESSION_FACTORY: sessionmaker[Session] | None = None
_ACTIVE_DATABASE_URL: str | None = None
_LOCK = Lock()

# Per-thread/task tenant schema. When set, the pool checkout event applies
# `SET search_path TO {schema}, public` to every checked-out connection.
# When unset, search_path defaults to "$user", public (the public schema).
_tenant_schema: ContextVar[str | None] = ContextVar("_tenant_schema", default=None)
_SCHEMA_PATTERN = re.compile(r"^user_[a-z0-9]{4,32}$")


def set_tenant_schema(schema_name: str | None) -> None:
    """Set (or clear) the tenant schema for the current async task / thread.

    Connections checked out from the pool while a schema is active have
    their ``search_path`` set to ``{schema}, public``. Pass None to clear.
    """
    if schema_name is not None and not _SCHEMA_PATTERN.fullmatch(schema_name):
        raise ValueError(f"Invalid schema name: {schema_name!r}")
    _tenant_schema.set(schema_name)


def get_tenant_schema() -> str | None:
    return _tenant_schema.get()


def _build_engine(database_url: str, *, db_echo: bool) -> Engine:
    connect_args: dict[str, object] = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    is_postgres = database_url.startswith("postgresql")
    kwargs: dict[str, object] = {
        "echo": db_echo,
        "future": True,
        "pool_pre_ping": is_postgres,
        "connect_args": connect_args,
    }
    if is_postgres:
        kwargs["pool_size"] = 5
        kwargs["max_overflow"] = 5
        kwargs["pool_recycle"] = 300  # recycle connections after 5 min

    eng = create_engine(database_url, **kwargs)  # type: ignore[arg-type]

    if database_url.startswith("postgresql"):
        # Bulletproof tenant routing.
        #
        # Strategy: callers set the tenant schema on a SQLAlchemy
        # ``Connection.info`` dict via ``bind_session_to_tenant()``, and
        # the ``before_cursor_execute`` event reads it on every query
        # and emits ``SET search_path TO {schema}, public`` first.
        #
        # Why ``Connection.info`` instead of a ContextVar: FastAPI runs
        # sync dependencies and sync route handlers in separate
        # threadpool calls — each gets a fresh contextvars copy, so the
        # var set in the dependency is invisible to the route. The
        # Connection object IS shared (the session keeps it across
        # queries), so ``conn.info`` propagates correctly.
        #
        # ``ContextVar`` is still used as a fallback for code paths that
        # don't have a session/connection (e.g. background tasks that
        # open ad-hoc sessions). Both are read; the connection's info
        # wins if present.

        @event.listens_for(eng, "before_cursor_execute")
        def _apply_tenant_search_path(
            conn: object,
            cursor: object,
            statement: str,
            parameters: object,
            context: object,
            executemany: bool,
        ) -> None:
            # Don't recurse on our own SET, or interfere with explicit
            # session-state changes (LOAD 'age', SET search_path = ...).
            stripped = statement.lstrip()
            upper = stripped.upper()
            if upper.startswith(("SET ", "RESET ", "SHOW ", "LOAD ")):
                return
            # AGE Cypher calls already include ag_catalog in their query;
            # don't clobber the manually-set search_path.
            if "ag_catalog" in stripped:
                return
            # 1. Per-connection override (set by bind_session_to_tenant).
            tenant = None
            try:
                tenant = conn.info.get("tenant_schema")  # type: ignore[attr-defined]
            except AttributeError:
                pass
            # 2. ContextVar fallback (background tasks).
            if not tenant:
                tenant = _tenant_schema.get()
            # Tenant schema must come first so unqualified table names
            # (e.g. user_preferences, notes) resolve to the tenant schema,
            # not ag_catalog. ag_catalog stays in path for AGE operators.
            target = (
                f'"{tenant}", ag_catalog, public' if tenant
                else '"$user", ag_catalog, public'
            )
            cursor.execute(f"SET search_path TO {target}")  # type: ignore[attr-defined]

        # Connection.info is per-DBAPI-connection and persists across pool
        # checkouts. Wipe the tenant binding on checkin so the next request
        # to use this connection starts clean.
        @event.listens_for(eng, "checkin")
        def _clear_tenant_on_checkin(
            dbapi_conn: object,
            connection_record: ConnectionPoolEntry,
        ) -> None:
            info = getattr(connection_record, "info", None)
            if info is not None:
                info.pop("tenant_schema", None)

    return eng


def bind_session_to_tenant(session: "Session", schema_name: str) -> None:
    """Attach a tenant schema to the session's underlying Connection.

    Every subsequent query on this session will be prefixed with
    ``SET search_path TO {schema}, public`` by the
    ``before_cursor_execute`` event. The binding lasts as long as the
    session retains the connection (typically the request lifetime).
    """
    if not _SCHEMA_PATTERN.fullmatch(schema_name):
        raise ValueError(f"Invalid schema name: {schema_name!r}")
    conn = session.connection()
    conn.info["tenant_schema"] = schema_name


def get_engine() -> Engine:
    global _ENGINE, _SESSION_FACTORY, _ACTIVE_DATABASE_URL

    settings = get_database_settings()
    with _LOCK:
        if _ENGINE is None or _ACTIVE_DATABASE_URL != settings.database_url:
            if _ENGINE is not None:
                _ENGINE.dispose()
            _ENGINE = _build_engine(settings.database_url, db_echo=settings.db_echo)
            _SESSION_FACTORY = sessionmaker(
                bind=_ENGINE,
                autoflush=False,
                expire_on_commit=False,
                class_=Session,
            )
            _ACTIVE_DATABASE_URL = settings.database_url
        return _ENGINE


def get_session_factory() -> sessionmaker[Session]:
    _ = get_engine()
    assert _SESSION_FACTORY is not None
    return _SESSION_FACTORY


def initialize_database() -> None:
    settings = get_database_settings()
    if not settings.db_auto_create:
        return
    if settings.database_url.startswith("postgresql"):
        return
    Base.metadata.create_all(bind=get_engine())


def reset_engine() -> None:
    global _ENGINE, _SESSION_FACTORY, _ACTIVE_DATABASE_URL

    with _LOCK:
        if _ENGINE is not None:
            _ENGINE.dispose()
        _ENGINE = None
        _SESSION_FACTORY = None
        _ACTIVE_DATABASE_URL = None
