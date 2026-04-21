from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
import os
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.db.config import get_database_settings
from app.db.engine import get_session_factory, initialize_database
from app.db.extensions import validate_required_extensions
from app.routes.auth import router as auth_router
from app.routes.backfill import router as backfill_router
from app.routes.concepts import router as concepts_router
from app.routes.connections import router as connections_router
from app.routes.backlinks import router as backlinks_router
from app.routes.blocks import router as blocks_router
from app.routes.entity_aliases import router as entity_aliases_router
from app.routes.export import router as export_router
from app.routes.extraction_results import router as extraction_results_router
from app.routes.graph import router as graph_router
from app.routes.meta_classification import router as meta_classification_router
from app.routes.health import router as health_router
from app.routes.import_ import router as import_router
from app.routes.media import router as media_router
from app.routes.notes import router as notes_router
from app.routes.preferences import router as preferences_router
from app.routes.process import router as process_router
from app.core.job_store import mark_stale_jobs_as_failed
from app.core.rate_limiter import limiter
from app.services.startup_backfill_service import StartupBackfillService

# Paths that are always public regardless of API_KEY setting.
_PUBLIC_PATHS = {
    "/health", "/docs", "/openapi.json", "/redoc",
    "/v1/auth/google/login", "/v1/auth/google/callback",
    "/v1/auth/github/login", "/v1/auth/github/callback",
    "/v1/auth/dev/login", "/v1/auth/dev/status",
}

class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = "-"  # type: ignore[attr-defined]
        return True


logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [%(name)s] [req=%(request_id)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
_request_id_filter = _RequestIdFilter()
logging.getLogger().addFilter(_request_id_filter)
for _h in logging.getLogger().handlers:
    _h.addFilter(_request_id_filter)
logging.getLogger("httpx").setLevel(logging.WARNING)

_LOG = logging.getLogger(__name__)


def _startup_database() -> None:
    initialize_database()
    settings = get_database_settings()
    if not settings.require_postgres_extensions:
        return

    session_factory = get_session_factory()
    with session_factory() as session:
        validate_required_extensions(session)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    _startup_database()
    mark_stale_jobs_as_failed()
    backfill_service: StartupBackfillService | None = None
    settings = get_database_settings()
    if settings.database_url.startswith("postgresql"):
        backfill_service = StartupBackfillService()
        backfill_service.run_async(backfill_service.run_note_reprocessing_backfill)

    try:
        yield
    finally:
        if backfill_service is not None:
            backfill_service.shutdown()


app = FastAPI(title="NeuroNote API", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

_cors_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Session middleware required by authlib for OAuth state storage.
# Uses SESSION_SECRET (separate from JWT_SECRET) to avoid coupling rotation.
_session_secret = os.environ.get("SESSION_SECRET") or os.environ.get("JWT_SECRET", "dev-session-secret")
app.add_middleware(SessionMiddleware, secret_key=_session_secret)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next: object) -> object:
    """Attach X-Request-ID to every request for log correlation."""
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
    request.state.request_id = request_id

    old_factory = logging.getLogRecordFactory()

    def record_factory(*args: object, **kwargs: object) -> logging.LogRecord:
        record = old_factory(*args, **kwargs)
        record.request_id = request_id  # type: ignore[attr-defined]
        return record

    logging.setLogRecordFactory(record_factory)
    try:
        response = await call_next(request)  # type: ignore[operator]
    finally:
        logging.setLogRecordFactory(old_factory)

    response.headers["X-Request-ID"] = request_id  # type: ignore[union-attr]
    return response


@app.middleware("http")
async def api_key_middleware(request: Request, call_next: object) -> object:
    """Enforce X-Api-Key when API_KEY env var is set. No-op in local dev (unset)."""
    required_key = os.environ.get("API_KEY", "").strip()
    if not required_key or request.url.path in _PUBLIC_PATHS or request.method == "OPTIONS":
        return await call_next(request)  # type: ignore[operator]

    provided_key = request.headers.get("X-Api-Key", "")
    if provided_key != required_key:
        return JSONResponse(status_code=403, content={"detail": "Forbidden"})

    return await call_next(request)  # type: ignore[operator]


app.include_router(auth_router, prefix="/v1")
app.include_router(health_router)
app.include_router(notes_router, prefix="/v1")
app.include_router(backlinks_router, prefix="/v1")
app.include_router(blocks_router, prefix="/v1")
app.include_router(process_router, prefix="/v1")
app.include_router(entity_aliases_router, prefix="/v1")
app.include_router(backfill_router, prefix="/v1")
app.include_router(media_router, prefix="/v1")
app.include_router(export_router, prefix="/v1")
app.include_router(graph_router, prefix="/v1")
app.include_router(connections_router, prefix="/v1")
app.include_router(concepts_router, prefix="/v1")
app.include_router(preferences_router, prefix="/v1")
app.include_router(import_router, prefix="/v1")
app.include_router(extraction_results_router, prefix="/v1")
app.include_router(meta_classification_router, prefix="/v1")
