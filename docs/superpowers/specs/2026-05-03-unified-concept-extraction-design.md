# Unified Concept Extraction — Design Spec

**Date:** 2026-05-03
**Status:** Approved for implementation

## Problem

Cloud mode (server-side LLM) and edge mode (browser Gemma) use fundamentally different extraction architectures:

- **Cloud mode** (`slm_extractor.py`): LLM free-generates concepts from raw note text. Result: garbage concepts like "can", camelCase variable names from inline code, non-reproducible output.
- **Edge mode** (`candidates.ts`): Rule-based patterns generate candidates; LLM filters by index. Result: higher quality, but candidate rules diverge from server-side rules — two code paths to maintain.

`temperature=0` does not guarantee determinism (MoE routing, floating-point parallelism, no provider guarantee). True reproducibility requires **deterministic candidates**, not LLM control.

## Goal

Single source of truth for candidate extraction: the server always generates candidates. Both cloud and edge modes receive the same candidate list for the same note content and use their respective LLMs only to filter by index.

## Architecture

```
Note saved
    │
    ▼
[Preprocessor]          strips inline code, code blocks, markdown syntax
    │
    ▼
[spaCy noun chunks + NER]   deterministic; POS filtering eliminates
[+ regex fallback]          function words structurally ("can" is a verb)
    │
    ▼
[Quality gate]          len ≥ 3, not camelCase, not code token blocklist
    │
    ▼
candidates[]  ──────────────────────────────────────────────────────────┐
    │                                                                    │
    │  CLOUD MODE                                          EDGE MODE     │
    ▼                                                         ▼          │
server LLM                                           browser Gemma      │
picks indices                                        picks indices      │
from list                                            from same list     │
    │                                                         │          │
    └─────────────────────────┬───────────────────────────────┘          │
                              ▼                                          │
              POST /v1/extraction-results                                │
              (same endpoint, same contract)         new endpoint ◄──────┘
                                               POST /v1/extract-candidates
```

`candidates.ts` is deleted. Edge mode fetches candidates from the server instead of generating them locally.

## Components

### 1. Preprocessor — `api/src/app/nlp/preprocessor.py` (new)

Strips noise from note content before any extraction runs. Applied in both the `/v1/extract-candidates` endpoint and the cloud `NoteNlpPipeline.extract()` path.

Rules applied in order:
1. Strip fenced code blocks (` ```...``` `)
2. Strip inline code (`` `...` ``)
3. Strip markdown link syntax (`[text](url)` → `text`)
4. Strip image syntax (`![alt](url)` → `alt`)
5. Collapse whitespace

Returns a plain-text string. No external dependencies — pure regex.

### 2. Enhanced Candidate Extraction — `api/src/app/nlp/spotting.py` (updated)

Primary layer: **spaCy noun chunks + NER** (when spaCy model is available).
- Noun chunks are POS-filtered by spaCy — function words ("can", "is", "the") are structurally excluded, no stopwords list needed.
- NER provides named entities (people, places, organisations, products).

Fallback layer (no spaCy): existing regex patterns (title-case phrases, acronyms, hyphenated compounds). These already work; they just get the quality gate applied before output.

**Quality gate** (applied to all candidates, regardless of source layer):
- `len(token) < 3` → reject
- `len(token) > 80` → reject
- camelCase pattern `^[a-z]+[A-Z]` → reject (variable names)
- snake_case/dollar pattern `[_$]` → reject (code tokens)
- Pure digit string → reject
- Custom code keyword blocklist: `var`, `let`, `const`, `return`, `import`, `from`, `export`, `function`, `class`, `async`, `await`, `null`, `true`, `false`, `undefined`

### 3. New API Endpoint — `POST /v1/extract-candidates`

**Purpose:** Edge mode calls this to get the same candidate list the server would use for cloud extraction.

**Request contract** (`shared/contracts/python/v1/extraction_candidates.py` + `.ts`):
```python
class ExtractCandidatesRequest(BaseModel):
    note_id: str
    title: str
    content_text: str
    content_hash: str

class ExtractCandidatesResponse(BaseModel):
    candidates: list[str]
    content_hash: str
```

**Behaviour:**
- Runs preprocessor → spotting → quality gate.
- Returns up to 50 candidates (same MAX_CANDIDATES cap as the current edge `candidates.ts`).
- Requires auth (`Depends(get_current_user)`).
- Response is deterministic for the same `content_hash` — can be cached.

### 4. Refactored Cloud Extractor — `api/src/app/nlp/slm_extractor.py` (updated)

`SLMExtractor.extract()` signature changes from free-generation to index-filter:

```python
def extract(
    self,
    *,
    title: str,
    preprocessed_content: str,  # already stripped by preprocessor in pipeline.py
    candidates: list[str],      # pre-generated by spotting.py
    known_concepts: list[str],
) -> SLMExtractionResult | None
```

New system prompt instructs the LLM to:
1. Pick which candidates are real, meaningful concepts — return their indices in `keep`.
2. List semantic relations between kept candidates as `[srcIdx, type, tgtIdx]` triples.
3. Be conservative — prefer fewer, high-quality picks.

Returns `{keep: [int], relations: [[int, str, int]], summary: str}`. No free text.

`pipeline.py` updated: runs preprocessor + spotting first to build `candidates[]`, then passes to `SLMExtractor`. Index → string mapping happens in `pipeline.py` after the LLM response.

### 5. Simplified Edge Orchestration — `web/src/lib/orchestration/edge-processing.ts` (updated)

`runEdgeProcessing()` replaces the call to `extractCandidates(chunk.text)` with a single call to `POST /v1/extract-candidates` over the full note content. The per-chunk candidate extraction loop is removed — the server returns at most 50 candidates for the whole note. Gemma receives all candidates in one call (the index list is small enough to fit in Gemma's context window at ≤50 items). The per-chunk loop is replaced with a single LLM inference call.

Inference prompt (`prompts.ts`) is updated to match the new server-side prompt semantics: same instructions, same JSON schema `{keep: [...], relations: [...]}`, same "be conservative" constraint.

`candidates.ts` is deleted.

### 6. Shared Contracts

New files:
- `shared/contracts/python/v1/extraction_candidates.py` — `ExtractCandidatesRequest`, `ExtractCandidatesResponse`
- `shared/contracts/ts/v1/extractionCandidates.ts` — matching TypeScript interfaces

`api-client.ts` gets a new `fetchCandidates(baseUrl, req)` wrapper.

## Data Flow

### Cloud mode (unchanged trigger, refactored internals)
1. Note save → `NoteNlpPipeline.extract(note_id, title, content_text, content_hash)`
2. Preprocessor strips inline code / markdown from `content_text`
3. spaCy noun chunks + quality gate → `candidates[]`
4. If `llm-enhanced` + API key: `SLMExtractor.extract(candidates)` → indices → concept strings
5. If LLM fails or profile is `rule-only` / `hybrid-spacy`: all quality-gated candidates used directly
6. `NoteExtractionResult` → graph sync (unchanged)

### Edge mode (new candidate fetch step)
1. Note save → `runEdgeProcessing()`
2. `POST /v1/extract-candidates` → `candidates[]` + `content_hash`
3. Gemma receives candidates list + filter prompt → returns `{keep, relations}`
4. Map indices → concept strings
5. `POST /v1/extraction-results` (unchanged)
6. Meta-classification (unchanged)

## Error Handling

| Failure | Behaviour |
|---|---|
| `/v1/extract-candidates` network error | `runEdgeProcessing` returns `status: "failed"`, note saved, no graph update |
| LLM returns out-of-bounds index | Silently skip that index during mapping |
| spaCy model missing | Fall through to regex candidates + quality gate |
| Preprocessor (regex only) | No failure mode; worst case returns lightly cleaned content |

## Testing

### Unit tests
- `test_preprocessor.py`: inline code stripping, code block stripping, markdown link stripping, edge cases (empty string, no matches)
- `test_spotting.py` (updated): quality gate rejects `can`, `myVar`, `setState`, `foo`, `_bar`; noun chunks from a sample ML note produce `["machine learning", "gradient descent", "neural network"]`
- `test_slm_extractor.py` (updated): mock LLM returns index list; verify correct string mapping; out-of-bounds index skipped safely

### Integration tests
- `test_extract_candidates_api.py`: authenticated POST returns deterministic candidates for a given content hash; two calls with same body return identical `candidates[]`
- Parity test: same note content processed through cloud path and through `/v1/extract-candidates` → assert `candidates[]` sets are identical (order may differ)

### Regression tests
- Fixture notes containing inline code (`` `setState` ``, `` `myVar` ``) — assert none of these appear in final extracted concepts
- Fixture note with sentence "We can use this approach" — assert "can" does not appear in candidates

## Files Affected

| File | Change |
|---|---|
| `api/src/app/nlp/preprocessor.py` | New |
| `api/src/app/nlp/spotting.py` | Add quality gate; spaCy noun chunks as primary layer |
| `api/src/app/nlp/slm_extractor.py` | Refactor: takes candidates[], returns indices |
| `api/src/app/nlp/pipeline.py` | Pass candidates to SLMExtractor; run preprocessor first |
| `api/src/app/routes/extraction_candidates.py` | New route: POST /v1/extract-candidates |
| `api/src/app/main.py` | Register new router |
| `shared/contracts/python/v1/extraction_candidates.py` | New |
| `shared/contracts/ts/v1/extractionCandidates.ts` | New |
| `web/src/lib/api-client.ts` | Add fetchCandidates() |
| `web/src/lib/orchestration/edge-processing.ts` | Replace extractCandidates() with server fetch |
| `web/src/lib/edge-llm/prompts.ts` | Align filter prompt to server prompt semantics |
| `web/src/lib/edge-llm/candidates.ts` | Delete |
| `tests/unit/test_preprocessor.py` | New |
| `tests/unit/test_slm_extractor.py` | Update for new signature |
| `tests/integration/test_extract_candidates_api.py` | New |
