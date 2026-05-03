# NeuroNote — Claude Code Context

## Rules when working in this database 
1. You are a senior software engineer
2. This project uses `uv` and a uv virtual environment for this environment.
3. Come up with a plan for the desired task using SOLID principles and high trust online resoruces that have tackled a similar problem, document that plan in a temporary file.
4. Always create the project structure first, then write test cases for all viable scenarios, and only then implement the logic. Document everything in that temporary file.
5. Always run tests against the written test cases after implementation.
6. Always write neat slop-free/minimal but descriptive comments and docs for everything we do.
7. After any code changes always scan for deadcode and do cleanup
8. Make sure what we implemented aligns with the plan.
9. Update codebase relevant documentation.
10. Delete temporary file
11. For bugs always prioritise permanent fixes and NOT quick fixes, Use high trust online resources
12. For UI/UX work, define explicit acceptance criteria in the temp plan (interaction, loading, error, keyboard,
  accessibility).
13. For frontend behavior changes, write/adjust tests first for all user-visible scenarios, then implement.
14. Every destructive action must have both mouse and keyboard access parity.
15. Use a consistent visual system (tokens/variables, spacing scale, typography scale); avoid ad-hoc styling..
16. Epic completion requires passing every gate in `docs/release_checklist.md` (no skipped gates).

## What this project is

NeuroNote is a local-first AI-powered knowledge base. Users write notes in a rich TipTap editor; the system automatically extracts concepts and relations with an NLP pipeline (rule-based, spaCy, or Claude-enhanced), stores them in an Apache AGE property graph, and lets users explore the knowledge graph interactively. Clicking any concept node opens an AI-generated insight panel grounded in the user's own notes.

## Monorepo layout

```
api/          FastAPI backend (Python 3.12, uv)
web/          Next.js 14 frontend (TypeScript)
shared/       Versioned contracts (Python Pydantic + TypeScript interfaces, mirrored)
infra/        Docker Compose stack
tests/        Python test suite (pytest)
docs/         Architecture decisions, implementation plan, UX research
```

## Running the project

```bash
make compose-up       # start full stack (Docker required)
make compose-migrate  # apply DB migrations after pulling
make compose-check    # API health checks
make compose-test     # API test suite
make compose-down     # stop
```

Web: `http://localhost:3000` · API: `http://localhost:8000`

## Key architectural decisions

### API
- **FastAPI** with async route handlers; `Depends(get_tenant_session)` for tenant-scoped DB injection (sets `search_path` per user); `Depends(get_db_session)` for public-schema-only routes (health, auth)
- **SQLAlchemy** ORM (sync sessions, not async) — the DB layer is synchronous even though route handlers are `async def`
- **Apache AGE** (typed property graph in PostgreSQL) — Cypher queries via raw SQL with `LOAD 'age'` + `ag_catalog` search path
- **Schema is migration-first** — `DB_AUTO_CREATE=false`; always run `make compose-migrate` after pulling new migrations
- **Alembic** for migrations — 14 migrations in `api/alembic/versions/`
- **Multi-tenancy** — schema-per-user isolation. Each user gets a PostgreSQL schema (`user_xxx`) with all data tables + an AGE graph (`nn_user_xxx`). `get_tenant_session()` sets `search_path` from JWT `schema_name`. All data queries use unqualified table names (resolved via `search_path`).
- **OAuth authentication** — Google + GitHub via `authlib` + JWT. `httpOnly` secure cookies (`neuronote_access` 15min, `neuronote_refresh` 7d). `get_current_user()` FastAPI dependency extracts `UserContext` from JWT.
- **pgvector** for semantic embeddings — note-level embeddings stored in `note_embeddings` (384-dim, HNSW index); per-user schema
- **Shared contracts** — Pydantic models in `shared/contracts/python/v1/`; always update the matching TypeScript file in `shared/contracts/ts/v1/` when changing Python contracts, and vice versa

#### Users table (migration 0014)
- `public.users` — OAuth user records for multi-tenant SaaS. Stores identity (`email`, `oauth_provider`, `oauth_provider_id`), display info (`display_name`, `avatar_url`), and tenant mapping (`schema_name`). Each user maps to an isolated tenant schema. Unique constraints on `email`, `schema_name`, and `(oauth_provider, oauth_provider_id)`.

#### Tenant provisioning (`api/src/app/db/tenant.py`)
- Schema-per-user isolation: each user gets a PostgreSQL schema (`user_xxx`) with all 13 data tables + an AGE graph (`nn_user_xxx`).
- `create_user_schema(session, schema_name)` — provisions schema, tables (from `schema_template.sql`), and AGE graph.
- `drop_user_schema(session, schema_name)` — tears down graph + schema.
- `apply_ddl_to_all_schemas(session, ddl)` — runs DDL across all tenant schemas (for future migrations).
- SQLite fallback for tests: emulates schemas via `{schema}__{table}` prefixed table names.
- Schema names must match `^user_[a-z0-9]{4,32}$`.

#### User preferences (migration 0015)
- `user_preferences` (per-tenant) — key-value store for per-user settings. Keys: `llm_mode` (`edge` | `cloud`), `llm_api_key`, `llm_base_url`, `llm_model`. Default is `edge`.
- `GET /v1/preferences` returns all preferences with API key masked (`****abcd`). `PUT /v1/preferences` does partial updates.
- `POST /v1/preferences/test-connection` validates a cloud-mode API key by making a test completion call.

#### LLM dual-mode architecture
- **Edge mode** (default): Gemma 4 E4B runs in-browser via WebGPU using `@mlc-ai/web-llm`. Frontend extracts concepts/relations locally, posts results to `POST /v1/extraction-results` and `POST /v1/meta-classification-results`. Server is purely a data layer for these users — no LLM cost.
- **Cloud mode**: User's `llm_api_key` is read from `user_preferences` and passed to `NoteProcessingService` / `ConceptInsightService` (via `_load_user_llm_config` helpers). Existing `POST /v1/process-note` flow is reused. Falls back to env-var key if user hasn't configured one.
- Frontend orchestration in `web/src/lib/orchestration/edge-processing.ts` (edge) and existing `process-polling.ts` (cloud). `NoteEditor.startProcessing` branches on `llmMode` prop.
- Edge LLM lifecycle managed by `useEdgeLLM(enabled, retryToken)` hook — handles WebGPU detection, model download progress, ready state.
- UI components: `ModelStatusIndicator` (header badge), `ModelDownloadProgress` (download banner), `WebGPUCheck` (modal when WebGPU unsupported).

#### Cache tables (migration 0011)
- `concept_insight_cache` — caches Claude-generated concept insights keyed by `(concept_label, content_digest)`. The digest is a SHA-256 of sorted `note_id:content_hash` pairs, so the cache auto-invalidates when any relevant note changes.
- `nlp_extraction_cache` — caches NLP/SLM extraction results keyed by `(content_hash, extraction_profile)`. Eliminates redundant LLM calls after container restarts for unchanged notes.

### NLP pipeline (`api/src/app/nlp/`)
- `NoteNlpPipeline` in `pipeline.py` — entry point; reads `NLP_EXTRACTION_PROFILE` env var
- Three profiles: `rule-only` (default), `hybrid-spacy`, `llm-enhanced`
- LRU extraction cache keyed by `content_hash` — notes with identical text share one result; backed by `nlp_extraction_cache` DB table for cross-restart persistence
- `SLMExtractor` (`slm_extractor.py`) wraps the LLM API for `llm-enhanced` profile — uses sync `LLMClient`
- `ConceptMetaClassifier` (`concept_meta.py`) — called after each note's graph sync; uses the LLM to identify `SYNONYM_OF` pairs (e.g. "ML" ↔ "machine learning") and `SUBTOPIC_OF` pairs (e.g. "backpropagation" → "neural networks") among newly extracted concepts; writes edges to AGE; uses sync `LLMClient`. Guards against re-classification via `concept_registry.meta_classified_at` — already-classified concepts are always skipped.
- `ConceptInsightService` (`services/concept_insight_service.py`) calls the LLM for on-demand insight generation — uses async `AsyncLLMClient`; cached in `concept_insight_cache`

### Graph sync (`api/src/app/services/graph_sync_service.py`)
- Delete-and-replace semantics: on each note save, all AGE nodes/edges sourced from that note are deleted then re-created
- `GraphSyncPayload` carries entities, keyphrases, relations, resolved_entities, embedding, entity_mentions
- Block-scoped `MENTIONS` edges: each edge carries `source_note_id`, `mention_text`, `start_offset`, `end_offset`
- **Concept meta edges are durable**: `SYNONYM_OF` and `SUBTOPIC_OF` edges between Entity nodes carry no `source_note_id`, so they are never deleted by the note's delete-and-replace sync. They persist across note re-edits.
- **Entity node properties**: `id` (slug), `name` (canonical text), `kind` (label), `updated_at`. The property is `name` — **not** `text`. Cypher queries must use `e.name`, not `e.text`.

### Concept insight service (`api/src/app/services/concept_insight_service.py`)
- `GET /v1/concepts/insight?label=<concept>` returns notes + AI insight grounded in user's notes
- Note discovery uses two phases: (1) case-insensitive LIKE search on title + content; (2) AGE graph traversal via `MENTIONS` edges with UNION clauses for `SYNONYM_OF` (1-hop, undirected) and `SUBTOPIC_OF` (finds notes mentioning a subtopic of the searched concept)
- Results cached in `concept_insight_cache` keyed by `(concept_label, content_digest)`

### Frontend
- **Next.js App Router** — all client components use `"use client"`
- **TipTap** editor with custom extensions: `mathInline`, `mathBlock`, `wikiLink`, `blockRef`, `image`
- **D3.js** for graph rendering (`D3GraphCanvas.tsx`) — force-directed simulation
- **Autosave orchestration** (`web/src/lib/orchestration/`) — 800ms debounce for save, 3s for processing queue trigger
- **API client** (`web/src/lib/api-client.ts`) — typed fetch wrappers using shared TS contracts
- **Design tokens** — all colors, font sizes, z-indices, spacing use CSS custom properties from `globals.css`; never use hardcoded hex colors or bare `rem` values in new CSS

### Password protection (`web/src/middleware.ts`)
- Controlled by `APP_PASSWORD` env var on the `web` service. Unset (default) = no gate, app loads directly.
- When set: Next.js Edge Middleware intercepts all routes except `/login`, `/api/auth/login`, `/api/auth/logout`, `/_next/*`, and static assets. Unauthenticated requests redirect to `/login?next=<original_path>`.
- Token = HMAC-SHA256(`SESSION_SECRET || APP_PASSWORD`, `APP_PASSWORD`) stored as `neuronote_session` httpOnly session cookie (no `maxAge` — cleared when browser closes).
- Middleware uses Web Crypto API (`crypto.subtle`); login/logout API routes use Node.js `crypto.createHmac`.
- Logout button in workspace header is shown only when `NEXT_PUBLIC_AUTH_ENABLED === "true"` (set automatically when `APP_PASSWORD` is non-empty via `${APP_PASSWORD:+true}` in compose).
- Key files: `web/src/middleware.ts`, `web/src/app/login/page.tsx`, `web/src/app/login/LoginForm.tsx`, `web/src/app/api/auth/login/route.ts`, `web/src/app/api/auth/logout/route.ts`

### Logging
- Root logger format uses `%(request_id)s` — injected by `_RequestIdFilter` in `main.py`
- `httpx` logger is set to `WARNING` to suppress HTTP request INFO noise from background threads
- Background threads (startup backfill, NLP processing) do not carry `request_id` — the filter provides `-` as default

## Important patterns to follow

### Adding a new API route
1. Create `api/src/app/routes/<name>.py` with `router = APIRouter()`
2. Add Pydantic response model to `shared/contracts/python/v1/`
3. Add matching TypeScript interface to `shared/contracts/ts/v1/`
4. Register in `api/src/app/main.py`: `app.include_router(router, prefix="/v1")`
5. Add `fetchXxx()` wrapper to `web/src/lib/api-client.ts`

### Adding a DB migration
```bash
docker compose -f infra/docker-compose.yml exec api uv run alembic revision --autogenerate -m "describe change"
make compose-migrate
```
Migration files go in `api/alembic/versions/` — naming convention: `YYYYMMDD_NNNN_<description>.py`

### Shared contracts
Both sides must stay in sync. When you change `shared/contracts/python/v1/graph.py`, update `shared/contracts/ts/v1/graph.ts` in the same commit.

### CSS design tokens
All new CSS must use tokens, not hardcoded values:
- Colors: `var(--text-strong)`, `var(--accent)`, `var(--panel-bg)`, `var(--danger)`, etc.
- Font sizes: `var(--text-xs)` (0.75rem), `var(--text-sm)` (0.8rem), `var(--text-base)` (0.875rem)
- Z-indices: `var(--z-dropdown)`, `var(--z-modal)`, `var(--z-toast)`
- Graph: `var(--graph-node-note)`, `var(--graph-node-entity)`, `var(--graph-node-highlight)`, `var(--graph-edge-dim)`, `var(--graph-node-dim-opacity)`

### Shared backend utilities (`api/src/app/utils/text.py`)
Text normalisation functions are centralised here. Do NOT duplicate these in services:
- `normalize_title(value)` — collapse whitespace, strip
- `normalize_title_key(value)` — normalize + lowercase (for case-insensitive comparison)
- `extract_wiki_link_titles(content_text)` — deduplicated, normalised `[[Title]]` targets
- `normalize_entity_key(value)` — slugify to `a-z0-9-` key
- `normalize_include_types(values)` — validate graph include_types with defaults

### Shared frontend hooks (`web/src/lib/hooks/`)
Complex state slices extracted from `NotesWorkspace` into composable hooks:
- `useQuickSwitch(notes, selectedNoteId)` — quick-switch modal state + keyboard nav
- `useBacklinks(baseUrl)` — backlinks modal state + fetch logic
- `useGlobalGraph(baseUrl)` — global graph state + filters + fetch logic
- `useSelectionMode()` — multi-select state + bulk dialog toggles

### Graph constants (`web/src/components/graph/graph-constants.ts`)
All D3 graph rendering magic numbers (forces, sizes, animation timing) are defined here. D3GraphCanvas reads colors from CSS custom properties at render time.

### File import (`api/src/app/import_/`)
- `markdown_parser.py` — line-by-line regex parser that converts markdown/text to TipTap JSON
- Route: `POST /v1/notes/import` accepts `ImportNoteRequest` (filename + content), auto-queues NLP processing
- Frontend: `FileDropZone` component wraps workspace with drag-drop overlay for `.md`/`.txt`

### Extraction feedback
- `ProcessStatusResponse.extraction_summary` — JSONB column on `processing_jobs` table (migration 0013)
- `ExtractionSummaryBadge` component in editor toolbar shows entity/relation/keyphrase counts after processing
- `process-polling.ts` callbacks receive full `ProcessStatusResponse` (not just status string)

### Repository separation
- `GraphRepository` — AGE/Cypher graph operations only
- `EmbeddingRepository` — pgvector embedding upsert + nearest-neighbor search (split from GraphRepository for ISP)

## Test suite

```bash
make compose-test          # full Python test suite
make compose-test-db       # PostgreSQL extension tests only
cd web && npx vitest run   # frontend tests
```

Test files: `tests/unit/`, `tests/integration/`, `tests/perf/`, `tests/e2e/`
Frontend tests: `web/src/**/*.test.tsx`

## Environment variables

| Variable | Where set | Purpose |
|---|---|---|
| `DATABASE_URL` | `api/.env` | PostgreSQL connection string |
| `NLP_EXTRACTION_PROFILE` | `api/.env` or compose | `rule-only` / `hybrid-spacy` / `llm-enhanced` |
| `NLP_MODEL_NAME` | `api/.env` or compose | spaCy model (e.g. `spacy:en_core_web_sm`) |
| `NLP_ENTITY_SEED_TERMS` | `api/.env` or compose | Comma-separated terms for deterministic seeding |
| `LLM_API_KEY` | `api/.env` or compose | API key for the LLM provider. Falls back to `ANTHROPIC_API_KEY` if not set. |
| `LLM_BASE_URL` | `api/.env` or compose | Base URL for any OpenAI-compatible endpoint. Default: `https://api.anthropic.com/v1/`. Examples: `https://api.openai.com/v1`, `https://api.groq.com/openai/v1`, `http://localhost:11434/v1` |
| `ANTHROPIC_API_KEY` | `api/.env` or compose | Legacy fallback for `LLM_API_KEY` when using Anthropic. |
| `NEXT_PUBLIC_API_BASE_URL` | `web/.env` | API URL for the browser (`http://localhost:8000`) |
| `APP_PASSWORD` | `infra/.env` or compose | Password gate for the web UI. Unset = disabled (dev mode). When set, all routes require login. |
| `SESSION_SECRET` | `infra/.env` or compose | Secret for HMAC-SHA256 session token. Falls back to `APP_PASSWORD` if unset. Use `openssl rand -hex 32`. |
| `PREF_ENCRYPTION_KEY` | `api/.env` or compose | Base64url Fernet key for encrypting `llm_api_key` at rest. Generate with: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Unset = no-op (plaintext stored). |
| `NEXT_PUBLIC_AUTH_ENABLED` | Set automatically by compose | `"true"` when `APP_PASSWORD` is non-empty. Controls logout button visibility. Do not set manually. |

## Files to be careful with

- `api/src/app/main.py` — app bootstrap, logging config, lifespan hooks, router registration
- `api/alembic/versions/` — migrations are irreversible in production; write idempotently
- `shared/contracts/python/v1/graph.py` + `shared/contracts/ts/v1/graph.ts` — must stay in sync
- `web/src/app/globals.css` — all design tokens live here; circular variable references will silently break styling
- `infra/docker-compose.yml` — service definitions, port mappings, env var injection
- `web/src/middleware.ts` — Edge runtime; must use Web Crypto API (not Node.js `crypto`); matcher covers all non-static routes
