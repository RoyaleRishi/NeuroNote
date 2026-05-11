# Contributing to NeuroNote

## Development setup

```bash
# Start the full stack (Docker required)
make compose-up

# Apply DB migrations after pulling
make compose-migrate

# Run the test suite
make compose-test

# Stop the stack
make compose-down
```

Web: `http://localhost:3000` · API: `http://localhost:8000`

## Running checks locally

```bash
# Python: lint + type check + tests
uv run --project api --group dev ruff check api/src shared tests
uv run --project api --group dev mypy api/src shared
uv run --project api --group dev pytest tests/integration tests/unit -q

# TypeScript: type check + frontend tests
cd web && npm run typecheck && npx vitest run
```

## Adding an API route

1. Create `api/src/app/routes/<name>.py` with `router = APIRouter()`.
2. Add request/response Pydantic models to `shared/contracts/python/v1/`.
3. Add matching TypeScript interfaces to `shared/contracts/ts/v1/`.
4. Register the router in `api/src/app/main.py`: `app.include_router(router, prefix="/v1")`.
5. Add typed fetch wrappers to `web/src/lib/api-client.ts`.
6. Add an integration test in `tests/integration/`.

## Adding a database migration

```bash
docker compose -f infra/docker-compose.yml exec api \
  uv run alembic revision --autogenerate -m "describe your change"
make compose-migrate
```

Migration files go in `api/alembic/versions/` with the naming convention `YYYYMMDD_NNNN_<description>.py`. Write them idempotently — they run in production. For tenant-schema changes, update `api/src/app/db/schema_template.sql` and call `apply_ddl_to_all_schemas()` in the migration.

## Shared contracts

`shared/contracts/python/v1/` and `shared/contracts/ts/v1/` must stay in sync. When you change a Python Pydantic model, update the matching TypeScript interface in the same commit.

## Design tokens

All new CSS must use tokens from `web/src/app/globals.css`, not hardcoded values:
- Colors: `var(--text-strong)`, `var(--accent)`, `var(--panel-bg)`, `var(--danger)`, …
- Font sizes: `var(--text-xs)`, `var(--text-sm)`, `var(--text-base)`
- Z-indices: `var(--z-dropdown)`, `var(--z-modal)`, `var(--z-toast)`

## Pull request guidelines

- One concern per PR — keep diffs focused and reviewable
- All CI checks must pass before merge (ruff, mypy, pytest, tsc, vitest)
- New API endpoints need a matching integration test in `tests/integration/`
- New frontend user-visible behavior needs a Vitest test in `web/src/**/*.test.tsx`
- Follow existing patterns — see `CLAUDE.md` for architectural decisions and `docs/decisions.md` for historical rationale
