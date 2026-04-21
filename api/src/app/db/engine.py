from __future__ import annotations

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

    # Reset search_path on every connection checkout so tenant-scoped sessions
    # don't leak their search_path into subsequent requests that draw the same
    # pooled connection.  Without this, connections returning from
    # get_tenant_session (search_path = user_xxx, public) would cause queries
    # against the shared `users` table (neuronote schema) to fail with
    # "relation does not exist".
    if database_url.startswith("postgresql"):

        @event.listens_for(eng, "checkout")
        def _reset_search_path(
            dbapi_conn: object,
            connection_record: ConnectionPoolEntry,
            connection_proxy: object,
        ) -> None:
            cursor = dbapi_conn.cursor()  # type: ignore[union-attr]
            cursor.execute('SET search_path TO "$user", public')
            cursor.close()

    return eng


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
