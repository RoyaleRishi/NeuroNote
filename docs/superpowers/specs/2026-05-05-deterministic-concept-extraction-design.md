# Deterministic Concept Extraction — Design Spec

**Date:** 2026-05-05
**Status:** Approved for implementation
**Supersedes:** `2026-05-03-unified-concept-extraction-design.md`

## Problem

The current pipeline puts an LLM on the critical path of concept *identification*. Three failure surfaces have compounded:

1. **In-browser Gemma JSON output** truncates and fails to parse. Bumping `max_tokens` is a treadmill — when filtering succeeds, `classifyMeta` then truncates at 512 tokens. Each fix reveals the next layer.
2. **Rule-based candidates feeding the LLM are noisy.** Real example, `Variables` note: 50 candidates including `have been`, `can even`, `you want`, `John`, `Sally`, `ADS`, `moment you`. Tightening stopword lists is symptom-fixing.
3. **Cloud and edge modes diverge at the LLM step.** Different prompts, different schemas, different failure modes. By construction, the two cannot be consistent if the LLM is doing identification differently.

Empirical smoke testing on 4 real notes across 4 domains established that:
- A pretrained keyphrase-extraction transformer (`kbir-inspec`) gives clean output on technical/structured prose but undercounts informal/list content.
- A statistical extractor (YAKE) catches what the transformer misses — especially proper nouns in lists and concept-density in journal-style prose.
- KeyBERT (embedding-rank over n-grams) produces overlapping chunky concatenations and was rejected.

## Goal

Move concept identification, normalisation, and relation typing entirely to a deterministic server-side pipeline. The LLM is reserved for prose generation only (per-note summary, concept insight panel). Edge and cloud modes produce identical concepts and edges for identical inputs.

**Non-goals:**
- Replacing the LLM for summary or insight panel — both stay
- Changing the AGE graph schema, `MENTIONS` semantics, or pgvector embedding storage
- Multi-language support — English only, matching current scope

## Architecture

```
TipTap doc (text + block tree)
    │
    ▼
[Preprocessor]              existing — strip code, URLs, markdown
    │
    ▼
[Concept extraction]        kbir-inspec (transformer) ⊕ YAKE (statistical)
    │                       merge → cleanup filters
    ▼
[Cross-note normalisation]  embedding NN against concept_registry
    │                       cosine > τ → emit SYNONYM_OF, merge to canonical
    ▼
[Block-structure relations] walk TipTap JSON tree
    │                       MENTIONED_TOGETHER, SUBTOPIC_OF, SIBLING_OF,
    │                       REFERENCES, DEFINED_BY
    ▼
graph sync (existing) → AGE nodes + edges + summary embedding


Concurrent, mode-dependent (prose only):
   • per-note summary  →  cloud: Anthropic API   |  edge: in-browser Gemma
   • insight panel     →  cloud: Anthropic API   |  edge: in-browser Gemma
```

The same server pipeline runs for both modes. Edge mode no longer posts extraction results — it triggers `POST /v1/process-note` like cloud, optionally passing a Gemma-generated summary string.

## Components

### 1. Concept Extraction — `api/src/app/nlp/extraction.py` (new)

Two-extractor ensemble. One module, one entry point:

```python
def extract_concepts(text: str) -> list[ConceptSpan]: ...
```

**Extractor A: kbir-inspec** (`ml6team/keyphrase-extraction-kbir-inspec`)
- HuggingFace pipeline `token-classification`, `aggregation_strategy="simple"`
- Loaded once at module level, kept warm
- Threshold: `score >= 0.85`

**Extractor B: YAKE** (`yake.KeywordExtractor`)
- Config: `lan="en"`, `n=3`, `dedupLim=0.7`, `top=20`
- Threshold: YAKE returns lower-is-better; we keep `(1 - score) >= 0.85`
- Pure Python, no model files

**Merge & cleanup** (applied to combined output):
- Dedupe by `text.strip().lower()`; on collision, keep the higher-confidence one
- Strip leading determiners (`the`, `a`, `an`, `this`, `that`, `these`, `those`)
- Reject if all tokens are stopwords (closed-class word list, ~80 entries)
- Reject if length < 2 or > 60
- Reject if ends with `etc`, `:`, `.`, `,`, or other punctuation
- Reject if all-numeric
- Reject if contains `[_$]` or `^[a-z]+[A-Z]` (code tokens, camelCase)

`ConceptSpan` carries: `text`, `confidence`, `source` (one of `transformer`, `statistical`, `both`).

### 2. Cross-Note Normalisation — `api/src/app/nlp/normalisation.py` (new)

For each `ConceptSpan`, search `concept_registry` for embedding-nearest existing concept:

- Embed the candidate using existing 384d sentence-transformer
- ANN search `concept_registry` (sub-pgvector index added in migration)
- If `cosine_similarity >= 0.88`, merge to existing canonical form and emit `SYNONYM_OF` edge
- Otherwise treat as new concept; insert into registry with embedding

This replaces `ConceptMetaClassifier` entirely. Synonym detection is now deterministic and free of LLM token-budget concerns.

### 3. Block-Structure Relations — `api/src/app/nlp/structure_relations.py` (new)

Reads `notes.document_json` (TipTap tree, already stored). Walks the tree once per save. Emits typed edges between concept pairs based on structural co-location:

| Edge type | Trigger |
|---|---|
| `MENTIONED_TOGETHER` | Two concepts appear in the same paragraph or list-item block |
| `SUBTOPIC_OF` | Concept A appears inside a child block of a heading H, where H mentions concept P; emit `A → SUBTOPIC_OF → P` |
| `SIBLING_OF` | Two concepts appear in adjacent list items under the same parent list |
| `REFERENCES` | Concept appears inside a `blockRef` extension's target block |
| `DEFINED_BY` | Concept appears as a `bold` span at the start of a paragraph (`**X** is/are ...` definition pattern) — links concept to the note (not another concept) |

All edges carry `source_note_id`, `confidence` (deterministic 1.0 except `MENTIONED_TOGETHER` which is 0.7), and `created_at`. They are subject to the existing delete-and-replace sync per note.

### 4. Pipeline Entrypoint — `api/src/app/nlp/pipeline.py` (rewritten)

`NoteNlpPipeline` collapses to a single class with a single profile. No more `extraction_profile` switching.

```python
class NoteNlpPipeline:
    def extract(
        self,
        *,
        note_id: str,
        title: str,
        content_text: str,
        document_json: dict,    # NEW: TipTap tree for structure relations
        content_hash: str,
    ) -> NoteExtractionResult: ...
```

The `dictionary_terms`, `blocks`, `entity_seed_terms` parameters are removed. The result still carries `entities`, `relations`, `embedding`, `entity_mentions`, `summary` so downstream graph sync is unchanged.

### 5. Edge Mode Frontend — Simplified

`web/src/lib/orchestration/edge-processing.ts` — **deleted**. Edge mode runs the same flow as cloud mode:

1. User edits → autosave (existing)
2. After autosave debounce, frontend calls `POST /v1/process-note` (existing)
3. Server runs the new deterministic pipeline (same code regardless of mode)
4. Frontend polls `GET /v1/processing/{job_id}/status` (existing)
5. Optionally, edge mode generates a summary string via in-browser Gemma and submits it as a body field on the polling completion (TBD: small new endpoint or extend `process-note` payload)
6. Insight panel: edge calls in-browser Gemma directly when user clicks a concept; cloud hits `/v1/concepts/insight`

The summary submission detail can be deferred — initial implementation can have edge mode without an LLM-generated summary, falling back to truncated content. Spec'd here as a follow-up.

## Contracts

### Removed

- `shared/contracts/python/v1/extraction.py` and `extraction.ts`
- `shared/contracts/python/v1/extraction_candidates.py` and `.ts`
- `shared/contracts/python/v1/meta_classification.py` and `.ts`

### Modified

- `ProcessStatusResponse.extraction_summary` keeps `entity_count`, `relation_count`, `keyphrase_count`, `top_entities`. The `extraction_profile_used` field is **removed** — there is no longer a profile to fall back from.

### New

- `ConceptSpan` is internal to `api/src/app/nlp/`, not exported in shared contracts. Frontend never sees raw concept lists; it sees the final graph via existing `/v1/graph/*` endpoints.

## Migration

`alembic/versions/0017_concept_registry_embeddings.py`:
- Add `embedding vector(384)` column to `public.concept_registry` and to per-tenant `concept_registry` tables
- Add HNSW index on the new column
- Idempotent: `ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`

`alembic/versions/0018_drop_extraction_profile_columns.py`:
- Drop `nlp_extraction_cache.extraction_profile` (cache key is now just `content_hash`)
- Drop `processing_jobs.extraction_summary->>'extraction_profile_used'` field via JSONB update

**Existing graph data**: at first deploy, the startup-backfill service runs the new pipeline against all notes in all tenant schemas. The new pipeline is fully deterministic, so the resulting graph reproduces from authoritative source (notes). Old `SYNONYM_OF` and `SUBTOPIC_OF` edges from `ConceptMetaClassifier` are wiped along with everything else and rebuilt deterministically.

Migration safety: backfill runs in batches per tenant, idempotent on `content_hash`.

## Purge List (Lean Ship)

When the new pipeline lands, the following are **deleted in the same PR series**:

### Server (`api/src/app/`)

- `nlp/slm_extractor.py` — entire file
- `nlp/concept_meta.py` (`ConceptMetaClassifier`) — entire file
- `nlp/spotting.py` regex/ngram/title-case/acronym extractors — file shrinks to a small dictionary-lookup helper for `MENTIONS` offset mapping (or deleted entirely if those mentions can be derived elsewhere — to be confirmed during implementation)
- `nlp/extractors.py` — review; delete if no callers remain
- `nlp/preprocessor.py` — keep, still preprocesses input
- `nlp/llm_client.py` — keep, used by summary/insight
- `nlp/concept_registry.py` — keep, gains an embedding column
- `nlp/resolution/` — review; likely keep `EntityResolver` for alias index, but it loses extraction-time consumers
- `routes/extraction_candidates.py` — entire file
- `routes/extraction_results.py` — entire file
- `routes/meta_classification.py` — entire file
- `services/note_processing_service.py` — keep but simplify; remove `_run_concept_meta_classification` and the cache-profile branching

### Server config / env

- `NLP_EXTRACTION_PROFILE` — removed from `NlpSettings`, compose, docs
- `NLP_MODEL_NAME` — removed (no spaCy)
- `NLP_ENTITY_SEED_TERMS` — removed
- `enable_regex_fallback` setting — removed
- The `extraction_profile` parameter throughout — removed

### Frontend (`web/src/lib/`)

- `orchestration/edge-processing.ts` — entire file
- `edge-llm/inference-client.ts` — delete `filterCandidates`, `classifyMeta`. Keep `generateSummary`, `generateInsight`.
- `edge-llm/schemas.ts` — delete `CHUNK_EXTRACTION_SCHEMA`, `META_SCHEMA`. Keep `SUMMARY_SCHEMA`, `INSIGHT_SCHEMA`.
- `edge-llm/prompts.ts` — delete `buildFilterPrompt`, `buildMetaPrompt`. Keep summary + insight prompt builders.
- `api-client.ts` — delete `fetchCandidates`, `fetchKnownConcepts`, `submitExtractionResults`, `submitMetaClassification`.
- Editor wiring in `NoteEditor.tsx` — collapse the cloud and edge processing branches into one (existing cloud path). Edge mode only differs in calling Gemma for the summary post-completion.

### Tests

- `tests/unit/test_edge_extraction_api.py` — delete (endpoints gone)
- `tests/unit/test_meta_classification.py` (if exists) — delete
- `tests/unit/test_entity_spotting.py` — rewrite or delete depending on what survives in `spotting.py`
- `tests/unit/test_slm_extractor.py` (if exists) — delete
- `tests/integration/test_backfill_api.py` — verify still passes after profile-column drop
- New: `tests/unit/test_extraction.py`, `tests/unit/test_normalisation.py`, `tests/unit/test_structure_relations.py`

### Housekeeping

The repo currently has duplicated `* 2.py`, `* 2.tsx`, `next.config 2.cjs` etc. files in the working tree. These are removed as part of this work since they shadow the real files and are unrelated leftovers.

## Test Plan

### Unit

- `test_extraction.py`:
  - kbir-inspec mocked to return canned spans → verify threshold filtering, dedup, cleanup
  - YAKE input fixtures with known noisy outputs → verify cleanup catches `etc.`, punctuation-trailing, all-stopword phrases
  - Combined ensemble: collisions resolve to higher confidence; both extractors empty → returns `[]`
- `test_normalisation.py`:
  - New concept inserted to registry with embedding
  - Existing concept matched → returns canonical form, emits `SYNONYM_OF`
  - No match below threshold → returns as-is
- `test_structure_relations.py`:
  - Fixture TipTap docs covering each edge type
  - Heading + sub-paragraph → `SUBTOPIC_OF`
  - Two concepts in same paragraph → `MENTIONED_TOGETHER`
  - Adjacent list items → `SIBLING_OF`
  - blockRef → `REFERENCES`
  - Bold-prefixed paragraph → `DEFINED_BY`

### Integration

- End-to-end via existing `tests/integration/test_process_note.py` (rename of current test): note saved → poll → verify graph contains expected concepts and edge types
- Determinism: same note processed twice → identical graph state (modulo timestamps)
- Cross-mode equivalence: simulate "edge" code path (no LLM key) and "cloud" code path (with LLM key) — both produce identical concept and edge sets

### Quality regression — held-out fixtures

The 4 smoke-test notes (Variables, Info Session, 2026 Goals, English Movies) become permanent fixtures under `tests/fixtures/concept_extraction/`. Each has a hand-curated expected concept list. The test asserts ≥80% precision and ≥70% recall against the curated set. This catches future regressions to the extraction pipeline.

## Open Items (deferred to plan)

1. Edge-mode summary submission detail — does `/v1/process-note` accept a pre-generated `summary` string, or is there a separate endpoint? Decision in plan.
2. Whether `spotting.py` survives at all or `MENTIONS` offset mapping moves into `extraction.py`. Decision after first implementation pass.
3. Tuning of cosine threshold τ for cross-note normalisation. Initial value 0.88; revisit after backfill of existing notes shows real merge behavior.

## Risks

- **kbir-inspec model size** (~470MB on disk, ~250MB resident) increases the API container memory footprint. Verified the existing compose has headroom; if SaaS deployment surfaces memory pressure, fall back to `distilbert-inspec` (270MB on disk, smaller resident).
- **YAKE noise on technical content** (e.g. it picks up `John`, `print` in code-heavy notes) — the cleanup filter list must catch single-word low-content tokens. Held-out fixtures gate this.
- **Domain coverage of kbir-inspec** is verified-good on tech tutorials and personal notes, less tested on long-form journals or transcripts. Production logging will surface gaps.
- **First-load latency** of the transformer pipeline (~3–5s cold start). Lifespan hook pre-warms the model in the API process startup.
