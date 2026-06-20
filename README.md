# NeuroNote
NeuroNote is a local-first, AI-powered knowledge base. You write notes in a rich editor, and the system automatically extracts concepts, builds a knowledge graph, and lets you explore how your ideas connect — all without leaving your workspace.

**Key capabilities:**
- **Rich editor** — TipTap-based with slash commands, wiki-links (`[[Note Title]]`), block references (`((uid))`), LaTeX math, images, and checklists
- **Automatic concept extraction** — deterministic NLP pipeline (kbir-inspec keyphrase transformer + YAKE ensemble, embedding-based cross-note normalisation, structural relation derivation) identifies concepts and relations in every note. No LLM call in the critical path.
- **Knowledge graph** — Apache AGE typed property graph; explore your notes as a D3 force-directed graph with hop depth, confidence, and node-type filters
- **Concept Insight Panel** — click any concept or entity node in the graph to see all related notes, an AI-generated synthesis paragraph grounded solely in your notes, and curated external learning links
- **Backlinks** — know which notes reference any note or block
- **Organization** — subjects (notebooks), tags, pinned notes, archive, full-text search
- **Markdown export** — zip archive with note.md + assets folder

---

## Services

| Service | Description |
|---|---|
| `web/` | Next.js 14 frontend — workspace sidebar, rich editor, graph panels |
| `api/` | FastAPI backend — note persistence, NLP processing, graph queries, media |
| `shared/` | Versioned TypeScript + Python request/response contracts |
| `infra/` | Docker Compose stack (PostgreSQL 16 + AGE + pgvector, API, Web) |
| `tests/` | Unit, integration, performance, and E2E tests |

---

## Quick Start (Docker Compose)

```bash
# 1. Start the full stack
make compose-up

# 2. Apply database migrations
make compose-migrate

# 3. Open in browser
open http://localhost:3000
```

Custom ports: `WEB_PORT=3001 API_PORT=8001 DB_PORT=5433 make compose-up`

Default URLs: Web `http://localhost:3000` · API `http://localhost:8000` · Postgres `localhost:5432`

---

## AI Features

### NLP Extraction Pipeline (deterministic)

Every note save triggers background concept extraction via `NoteNlpPipeline`, which runs three deterministic stages — no LLM call is required:

1. **`extract_concepts`** — ensemble of the `ml6team/keyphrase-extraction-kbir-inspec` transformer (high precision on dense prose) and YAKE (statistical recall on lists/informal text). Cleanup filter drops leading determiners, purely-stopword phrases, code tokens, and anything outside 2–60 chars.
2. **`normalise_concepts`** — embeds each span and runs cosine nearest-neighbour against `concept_registry.embedding` (HNSW). A match at threshold ≥ 0.88 reuses the existing canonical concept; otherwise a new registry row is inserted. This is how cross-note concept identity is established.
3. **`derive_relations`** — emits five structural edge types from TipTap block structure alone: `MENTIONED_TOGETHER`, `SUBTOPIC_OF`, `SIBLING_OF`, `REFERENCES`, `DEFINED_BY`.

Results are cached by `content_hash` in `nlp_extraction_cache` and shared across notes with identical text. Re-extraction across all notes is available via the `reextract_all_notes` script in `api/src/app/scripts/`.

The LLM is now used only for (a) optional per-note summaries and (b) the on-demand Concept Insight Panel — see below.

### LLM Modes (Edge vs. Cloud)

Each user picks how the LLM runs via the `llm_mode` preference (default `edge`):

| | Edge mode (default) | Cloud mode |
|---|---|---|
| Who runs the LLM | Browser (WebGPU via WebLLM) | API server |
| Data leaves device | No (notes stay local) | Yes (sent to configured provider) |
| Requires API key | No | Yes (`llm_api_key` in `/v1/preferences`) |
| Model | `Gemma-2-2b-it` (downloaded once, ~2–4 GB) | Any OpenAI-compatible endpoint |

**Cloud provider configuration** is per-user (`PUT /v1/preferences`): `llm_api_key`, `llm_base_url`, `llm_model`. The server falls back to env vars (`LLM_API_KEY` / `LLM_BASE_URL`) only if the user hasn't configured their own. API keys are Fernet-encrypted at rest when `PREF_ENCRYPTION_KEY` is set.

| Provider | `llm_base_url` | Example `llm_model` |
|---|---|---|
| Anthropic | `https://api.anthropic.com/v1/` | `claude-haiku-4-5-20251001` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Groq | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| Mistral | `https://api.mistral.ai/v1` | `mistral-small-latest` |
| Ollama (local) | `http://localhost:11434/v1` | `llama3.2` |

### Concept Insight Panel

When you click any non-note node (concept, entity, relation) in either graph view, a panel opens showing:

1. **Related Notes** — all notes mentioning the concept, with snippets, clickable to open. Note discovery uses case-insensitive LIKE on title + content **and** AGE graph traversal via `MENTIONS` edges with UNION clauses for `SYNONYM_OF` (1-hop) and `SUBTOPIC_OF` (subtopic-mentioning notes).
2. **AI Insight** — a synthesis paragraph drawn *only* from your notes. In **edge mode** the LLM call runs in the browser; in **cloud mode** it runs on the server with the user's configured API key. Cached server-side in `concept_insight_cache` keyed by `(concept_label, content_digest)`.
3. **Further Learning** — AI-suggested reputable external resources (clearly labeled; verify before visiting).

In cloud mode without a configured API key (and no env-var fallback), the notes list still renders — the insight section shows a config hint and the configuration error surfaces via the `insight_error` field of `ConceptInsightResponse`.

**API:**
```bash
curl "http://localhost:8000/v1/concepts/insight?label=machine+learning&limit_notes=10"
```

---

## Authentication

NeuroNote uses OAuth 2.0 (Google and GitHub) for user identity. Each authenticated user gets an isolated PostgreSQL schema (`user_<id>`) containing all their data tables and a dedicated AGE graph (`nn_user_<id>`).

**Environment variables required for OAuth:**

| Variable | Description |
|---|---|
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google OAuth app credentials |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | GitHub OAuth app credentials |
| `JWT_SECRET` | HS256 signing secret for access/refresh JWTs |
| `SESSION_SECRET` | HMAC secret for authlib OAuth state storage (separate from JWT_SECRET) |

**Token flow:**
- Access token: 15-minute httpOnly cookie (`neuronote_access`) containing `user_id`, `email`, `schema_name`
- Refresh token: 7-day httpOnly cookie (`neuronote_refresh`) — only `user_id`
- Frontend transparently refreshes on 401 via `POST /v1/auth/refresh`

**Dev bypass:** `POST /v1/auth/dev/login` (enabled only when no OAuth credentials are configured).

**Password gate (self-hosted):** Set `APP_PASSWORD` in the compose env to enable a simple login page at `/login`. HMAC-SHA256 session token stored as `neuronote_session` cookie (cleared on browser close). When set, `NEXT_PUBLIC_AUTH_ENABLED` is automatically set to `"true"` by compose, showing a Logout button in the header.

---

## Edge Mode Lifecycle

Edge mode runs an LLM fully in the browser via [WebLLM](https://webllm.mlc.ai/) + WebGPU. The server acts as a pure data layer.

1. **Consent** — on first use of edge mode, a consent dialog is shown before any model download begins. The choice is persisted to `localStorage`.
2. **Download** — the browser downloads the model into IndexedDB via `@mlc-ai/web-llm`. Progress is reflected in the header `ModelStatusIndicator` and the `ModelDownloadProgress` banner.
3. **Crash recovery** — a `edge-init-pending` flag is set in `localStorage` before download and cleared after the first successful inference. If a previous tab was killed mid-load, `EdgeCrashBanner` offers retry or one-click switch to cloud.
4. **Inference** — once ready, the browser performs extraction and posts results to `POST /v1/extraction-results` and `POST /v1/meta-classification-results`. Insight calls use `GET /v1/concepts/insight-context` for note excerpts and complete the LLM call locally.
5. **Mode switch** — toggle via `UserMenu` (writes `llm_mode` to `/v1/preferences`). Cloud-mode keys can be validated via `POST /v1/preferences/test-connection` before saving.

**Browser requirements:** Chrome 113+, Edge 113+, or any browser with `navigator.gpu`. Safari and Firefox are currently unsupported — `WebGPUCheck` renders a modal when missing.

---

## Editor Features

| Feature | How to trigger |
|---|---|
| Block type menu | Toolbar buttons (Paragraph, H1–H3, Bullet, Numbered, Checklist, Quote, Code, Divider) |
| Slash commands | Type `/` anywhere (e.g. `/h1`, `/bullet`, `/code`) |
| Command palette | `Cmd+K` / `Ctrl+K` |
| Wiki-link | `[[Note Title]]` — autocomplete + quick-create for new notes |
| Block reference | `((` — search and insert a reference to any block |
| Inline math | Wrap LaTeX in `$...$` or use the mathInline node |
| Block math | Use the mathBlock node or `/math` slash command |
| Linked mentions | Click "Linked mentions" in the editor panel |
| Keyboard shortcuts | `?` or the help button opens the shortcut reference |

---

## Knowledge Graph

### Local Graph (per-note)

Shows the neighborhood of a single note — note nodes, entity nodes, and relation edges up to N hops away.

**API:**
```bash
curl "http://localhost:8000/v1/graph/local/{note_id}?max_hops=1&limit_nodes=80&min_confidence=0.35&include_types=note,entity,relation"
```

Filter parameters:
- `max_hops` — neighborhood depth (1–2)
- `limit_nodes` — max nodes returned (1–150)
- `min_confidence` — entity confidence threshold (0.0–1.0)
- `include_types` — comma-separated: `note`, `entity`, `relation`

**UI:** Switch to the "Graph" tab in any note editor. Click a note node to open that note. Click any other node to open the Concept Insight Panel.

### Global Graph

Shows the full cross-note knowledge graph.

**API:**
```bash
curl "http://localhost:8000/v1/graph/global?limit_nodes=500&min_confidence=0.0&include_types=note,entity,relation"
```

**UI:** Accessible from the workspace sidebar global graph button.

---

## Organization

### Notes list filters

```bash
curl "http://localhost:8000/v1/notes?limit=20&offset=0&search=graph&subject_id=inbox&tag=ml&is_archived=false"
```

| Parameter | Description |
|---|---|
| `search` | Case-insensitive title + body text search |
| `subject_id` | Filter by subject/notebook |
| `tag` | Filter by normalized tag |
| `is_archived` | `false` (default) or `true` for archived notes |
| `is_pinned` | Optional `true`/`false` pinned filter |

### Subjects & Tags

Subjects (notebooks) and tags are managed via the note editor's three-dots menu. Notes can be assigned a subject, multiple tags, pinned, and archived. Pinned notes appear at the top of the sidebar.

---

## Project Docs

| File | Contents |
|---|---|
| `docs/plan.md` | Executable implementation plan and epic history |
| `docs/initial_scoping_doc.md` | Original requirements baseline |
| `docs/retrospective_learnings.md` | Implementation insights |
| `docs/LLM.md` | LLM integration notes |
| `shared/contracts/README.md` | Versioned contract documentation |

---

## Development

### Common commands

```bash
make compose-up          # Start full stack
make compose-migrate     # Apply DB migrations
make compose-check       # Run API health checks
make compose-test        # Run API test suite
make compose-test-db     # Run PostgreSQL extension tests
make compose-logs        # Stream container logs
make compose-down        # Stop all containers
```

### Local fallback (no Docker)

```bash
make setup
make check
make test
make run-api-db   # Start API + local DB
make run-web      # Start Next.js dev server
```

### Schema management

Schema is migration-first (`DB_AUTO_CREATE=false` in the compose API runtime). Always run `make compose-migrate` after pulling changes that include new migrations.

Migration history:
- `20260301_0001` — core schema (notes, blocks, entities, entity_aliases)
- `20260307_0002` — entity_aliases idempotent repair
- `20260311_0003` — `notes.note_title` column
- `20260312_0004` — workspace organization (flags + note_tags)
- `20260313_0005` — media schema (note_assets)
- `20260314_0006` — block tree fields (block_uid, parent_block_uid, sibling_order)
- `20260314_0007` — note_assets schema drift repair
- `20260402_0008` — semantic embeddings (pgvector, note_embeddings)
- `20260402_0009` — processing jobs persistence
- `20260402_0010` — concept registry
- `20260403_0011` — AI cache tables (concept_insight_cache, nlp_extraction_cache)
- `20260403_0012` — concept meta-classification (meta_classified_at on concept_registry)
- `20260407_0013` — extraction_summary JSONB column on processing_jobs
- `20260409_0014` — public.users table (OAuth identity + tenant mapping)
- `20260421_0015` — user_preferences key-value store (llm_mode, llm_api_key, etc.)
- `20260503_0016` — clear plaintext API keys (one-time data migration)
- `20260505_0017` — concept_registry.embedding column + HNSW index (cross-note normalisation)
- `20260506_0018` — drop unused extraction_profile column

---

## API Reference

### Notes

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/notes` | List notes (supports filters above) |
| `GET` | `/v1/notes/{note_id}` | Get a single note |
| `PUT` | `/v1/notes/{note_id}` | Create or update a note |
| `DELETE` | `/v1/notes/{note_id}` | Delete a note |
| `GET` | `/v1/notes/{note_id}/backlinks` | Note backlinks |
| `GET` | `/v1/notes/{note_id}/blocks` | Block tree for a note |
| `GET` | `/v1/notes/{note_id}/export/markdown` | Download markdown zip |

### Blocks

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/blocks/search?q=...&limit=10` | Search blocks by text |
| `GET` | `/v1/blocks/{block_uid}/backlinks` | Block backlinks |

### Processing

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/process-note` | Queue NLP processing for a note |
| `GET` | `/v1/process-status/{job_id}` | Poll job status (`queued→running→completed/failed`) |
| `GET` | `/v1/backfill-status` | Startup backfill progress |

### Graph

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/graph/local/{note_id}` | Local neighborhood graph |
| `GET` | `/v1/graph/global` | Full cross-note graph |
| `GET` | `/v1/concepts/insight` | AI concept insight (label + related notes) |

### Entity Aliases

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/entity-aliases/confirm` | Register a canonical alias |
| `POST` | `/v1/entity-aliases/resolve-preview` | Preview resolution output |
| `GET` | `/v1/entity-aliases/calibration` | Calibration metrics |

### Media

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/media/uploads` | Upload image (base64 JSON payload) |
| `GET` | `/v1/media/{asset_id}` | Retrieve media asset |
| `DELETE` | `/v1/media/{asset_id}` | Delete media asset |

### Connections

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/connections/{note_id}` | Immediate neighbors of a note |

### Authentication

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/auth/google/login` | Initiate Google OAuth flow |
| `GET` | `/v1/auth/google/callback` | Google OAuth callback |
| `GET` | `/v1/auth/github/login` | Initiate GitHub OAuth flow |
| `GET` | `/v1/auth/github/callback` | GitHub OAuth callback |
| `POST` | `/v1/auth/refresh` | Issue new access token from refresh cookie |
| `POST` | `/v1/auth/logout` | Clear both auth cookies |
| `GET` | `/v1/auth/me` | Return authenticated user profile |

### User Preferences

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/preferences` | Return all preferences (API key masked) |
| `PUT` | `/v1/preferences` | Partial-update preferences |
| `POST` | `/v1/preferences/test-connection` | Validate a cloud-mode API key |

### Import

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/notes/import` | Import a markdown or text file as a new note |

---

## Examples

### Processing pipeline

```bash
# 1. Save a note
curl -sS -X PUT http://127.0.0.1:8000/v1/notes/demo-note \
  -H 'Content-Type: application/json' \
  --data-binary @- <<'JSON'
{"note_id":"demo-note","note_title":"Graph Reasoning Notes","subject_id":"inbox","tags":["graph","ml"],"is_pinned":true,"is_archived":false,"content_json":{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"Machine Learning improves Graph Reasoning across Notes"}]}]},"content_text":"Machine Learning improves Graph Reasoning across Notes","updated_at":"2026-03-07T12:00:00Z"}
JSON

# 2. Queue NLP processing
HASH=$(printf 'Graph Reasoning Notes\n\nMachine Learning improves Graph Reasoning across Notes' | shasum -a 256 | awk '{print $1}')
curl -sS -X POST http://127.0.0.1:8000/v1/process-note \
  -H 'Content-Type: application/json' \
  -d "{\"note_id\":\"demo-note\",\"content_text\":\"Graph Reasoning Notes\n\nMachine Learning improves Graph Reasoning across Notes\",\"content_hash\":\"$HASH\",\"updated_at\":\"2026-03-07T12:00:00Z\"}"

# 3. Poll until completed
curl http://127.0.0.1:8000/v1/process-status/<job_id>
```

### Entity alias resolution

```bash
# Register a canonical alias
curl -sS -X POST http://127.0.0.1:8000/v1/entity-aliases/confirm \
  -H 'Content-Type: application/json' \
  --data-binary @- <<'JSON'
{"alias_text":"ML","canonical_entity_id":"concept-machine-learning","canonical_name":"Machine Learning","confidence":0.95}
JSON

# Preview resolution
curl -sS -X POST http://127.0.0.1:8000/v1/entity-aliases/resolve-preview \
  -H 'Content-Type: application/json' \
  --data-binary @- <<'JSON'
{"entities":[{"entity_id":"entity-1","text":"ML","label":"acronym","confidence":0.8}]}
JSON

# Calibration metrics
curl http://127.0.0.1:8000/v1/entity-aliases/calibration
```

### Backlinks

```bash
# Create two notes where one references the other via wiki-link
curl -sS -X PUT http://127.0.0.1:8000/v1/notes/target-note \
  -H 'Content-Type: application/json' \
  --data-binary @- <<'JSON'
{"note_id":"target-note","note_title":"Target Note","subject_id":"inbox","tags":[],"is_pinned":false,"is_archived":false,"content_json":{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"Target"}]}]},"content_text":"Target","updated_at":"2026-03-13T13:00:00Z"}
JSON

curl -sS -X PUT http://127.0.0.1:8000/v1/notes/source-note \
  -H 'Content-Type: application/json' \
  --data-binary @- <<'JSON'
{"note_id":"source-note","note_title":"Source Note","subject_id":"inbox","tags":[],"is_pinned":false,"is_archived":false,"content_json":{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"See [[Target Note]]"}]}]},"content_text":"See [[Target Note]]","updated_at":"2026-03-13T13:01:00Z"}
JSON

curl http://127.0.0.1:8000/v1/notes/target-note/backlinks
```

### Concept insight

```bash
curl "http://127.0.0.1:8000/v1/concepts/insight?label=machine+learning&limit_notes=10"
```

Expected response fields: `concept_label`, `notes_found`, `note_refs` (with `snippet`), `insight` (null without API key), `learning_links`, `generated_at`.

### Math + image + export

```bash
# Upload image
B64=$(printf '\x89PNG\r\n\x1a\nabc' | base64)
curl -sS -X POST http://127.0.0.1:8000/v1/media/uploads \
  -H 'Content-Type: application/json' \
  --data-binary @- <<JSON
{"note_id":"demo-note","filename":"diagram.png","mime_type":"image/png","content_base64":"$B64"}
JSON

# Export markdown zip
curl -sS http://127.0.0.1:8000/v1/notes/demo-note/export/markdown --output demo-note.zip
unzip -l demo-note.zip
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `relation "note_assets" does not exist` | Run `make compose-migrate` |
| Insight section shows config hint | Configure `llm_api_key` for the user via `PUT /v1/preferences` (or set `LLM_API_KEY` in compose env as fallback). Switch to edge mode for fully-local insight. |
| Edge mode stuck "Loading 0%" or device OOM | `EdgeCrashBanner` will appear on next reload — choose "Switch to Cloud AI" or retry. Manually clear `edge-init-pending` in `localStorage` if banner doesn't show. |
| AGE concurrent lock error in logs | Known AGE issue with parallel note processing — non-critical, retries succeed |
| Port already in use | Use `WEB_PORT=3001 API_PORT=8001 make compose-up` |
