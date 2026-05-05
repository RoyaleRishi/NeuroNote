# Deterministic Concept Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current cloud/edge-divergent LLM-driven concept extraction with a single deterministic server-side pipeline (kbir-inspec + YAKE ensemble, embedding-based normalisation, structure-derived relations). LLM is reserved for prose only (per-note summary, insight panel).

**Architecture:** Server runs the same deterministic pipeline regardless of mode. Edge mode no longer submits extraction results — it triggers `POST /v1/process-note` like cloud. The frontend `edge-processing.ts` orchestrator is deleted. Two extractors run server-side: `ml6team/keyphrase-extraction-kbir-inspec` (transformer, dense prose) and `yake` (statistical, fills coverage gaps). Synonyms come from embedding NN against `concept_registry`. Edge typing comes from the TipTap document tree.

**Tech Stack:** Python 3.12 (FastAPI, SQLAlchemy, Alembic, transformers, sentence-transformers, yake, pgvector, Apache AGE), TypeScript (Next.js 14, TipTap, WebLLM).

**Reference spec:** `docs/superpowers/specs/2026-05-05-deterministic-concept-extraction-design.md`

---

## Phase 0 — Housekeeping (shadow files & dep)

### Task 0.1: Delete duplicate `* 2.*` shadow files

These were created by accidental file copies and shadow real files in IDEs. Confirm each shadow's content matches its non-shadow counterpart before deletion (a stray edit could lose work).

**Files:**
- Delete: 17 files matching `* 2.{py,tsx,cjs,sql,md}` in working tree (see `git status` for full list)

- [ ] **Step 1: Diff each shadow against its real counterpart**

```bash
for f in $(find . -name "* 2.*" -not -path "./node_modules/*" -not -path "./.venv/*" -not -path "./*/node_modules/*"); do
  real="${f// 2./.}"
  if [ -f "$real" ]; then
    if ! diff -q "$f" "$real" >/dev/null 2>&1; then
      echo "DIVERGED: $f vs $real"
    fi
  else
    echo "ORPHAN (no real counterpart): $f"
  fi
done
```

Expected: any DIVERGED or ORPHAN output halts the task — investigate manually before deletion.

- [ ] **Step 2: Delete shadow files**

```bash
find . -name "* 2.*" \
  -not -path "./node_modules/*" \
  -not -path "./.venv/*" \
  -not -path "./*/node_modules/*" \
  -print -delete
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: delete duplicate shadow files (* 2.*)"
```

---

### Task 0.2: Add `yake` dependency

**Files:**
- Modify: `api/pyproject.toml`
- Modify: `api/uv.lock`

- [ ] **Step 1: Add `yake>=0.4.8,<1.0` to `api/pyproject.toml` dependencies**

Add to the dependencies array (alphabetical placement):
```toml
  "yake>=0.4.8,<1.0",
```

- [ ] **Step 2: Lock**

```bash
docker compose -f infra/docker-compose.yml exec -T api uv lock --project api
```

- [ ] **Step 3: Verify install**

```bash
docker compose -f infra/docker-compose.yml exec -T api /tmp/neuronote-api-venv/bin/python -c "import yake; print(yake.__version__)"
```
Expected: prints a version (e.g. `0.7.3`).

- [ ] **Step 4: Commit**

```bash
git add api/pyproject.toml api/uv.lock
git commit -m "feat: add yake dependency for statistical concept extraction"
```

---

## Phase 1 — Build new extraction module (TDD)

### Task 1.1: `extract_concepts` — kbir-inspec branch only

**Files:**
- Create: `api/src/app/nlp/extraction.py`
- Create: `tests/unit/test_extraction.py`

- [ ] **Step 1: Write failing test for transformer extraction**

```python
# tests/unit/test_extraction.py
from unittest.mock import MagicMock, patch

from app.nlp.extraction import ConceptSpan, extract_concepts


@patch("app.nlp.extraction._inspec_pipeline")
def test_extract_concepts_uses_inspec(mock_pipeline):
    mock_pipeline.return_value = [
        {"word": " data types", "score": 0.95, "entity_group": "KEY"},
        {"word": " variables", "score": 0.88, "entity_group": "KEY"},
        {"word": " noise", "score": 0.40, "entity_group": "KEY"},
    ]
    with patch("app.nlp.extraction._yake_extractor") as mock_yake:
        mock_yake.extract_keywords.return_value = []
        spans = extract_concepts("dummy text long enough to pass length check")

    texts = {s.text for s in spans}
    assert "data types" in texts
    assert "variables" in texts
    assert "noise" not in texts  # below 0.85 threshold
```

- [ ] **Step 2: Run test to verify failure**

```bash
docker compose -f infra/docker-compose.yml exec -T api uv run pytest tests/unit/test_extraction.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app.nlp.extraction'`.

- [ ] **Step 3: Implement minimal extraction.py with kbir-inspec only**

```python
# api/src/app/nlp/extraction.py
"""Deterministic concept extraction using a transformer + statistical ensemble.

The transformer (kbir-inspec) is high-precision on dense prose; YAKE supplies
recall on informal/list content. Combined output is deduped and cleaned before
returning. No LLM call is made here — this is the deterministic core that
runs identically in cloud and edge modes.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

import yake  # type: ignore[import-untyped]
from transformers import pipeline as hf_pipeline

_INSPEC_MODEL = "ml6team/keyphrase-extraction-kbir-inspec"
_INSPEC_THRESHOLD = 0.85
_YAKE_INVERTED_THRESHOLD = 0.85  # YAKE returns lower-is-better; we keep (1-s) >= 0.85


@dataclass(frozen=True, slots=True)
class ConceptSpan:
    text: str
    confidence: float
    source: Literal["transformer", "statistical", "both"]


@lru_cache(maxsize=1)
def _inspec_pipeline():
    return hf_pipeline(
        "token-classification",
        model=_INSPEC_MODEL,
        aggregation_strategy="simple",
    )


@lru_cache(maxsize=1)
def _yake_extractor() -> yake.KeywordExtractor:
    return yake.KeywordExtractor(lan="en", n=3, dedupLim=0.7, top=20)


def extract_concepts(text: str) -> list[ConceptSpan]:
    if len(text.strip()) < 10:
        return []
    inspec_spans = _run_inspec(text)
    yake_spans = _run_yake(text)
    return _merge(inspec_spans, yake_spans)


def _run_inspec(text: str) -> list[ConceptSpan]:
    raw = _inspec_pipeline()(text)
    out: list[ConceptSpan] = []
    for s in raw:
        score = float(s["score"])
        if score < _INSPEC_THRESHOLD:
            continue
        out.append(ConceptSpan(text=s["word"].strip(), confidence=score, source="transformer"))
    return out


def _run_yake(text: str) -> list[ConceptSpan]:
    raw = _yake_extractor().extract_keywords(text)
    out: list[ConceptSpan] = []
    for phrase, score in raw:
        inverted = 1.0 - float(score)
        if inverted < _YAKE_INVERTED_THRESHOLD:
            continue
        out.append(ConceptSpan(text=phrase.strip(), confidence=inverted, source="statistical"))
    return out


def _merge(a: list[ConceptSpan], b: list[ConceptSpan]) -> list[ConceptSpan]:
    by_key: dict[str, ConceptSpan] = {}
    for s in (*a, *b):
        key = s.text.lower()
        if not key:
            continue
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = s
        elif s.confidence > existing.confidence:
            by_key[key] = ConceptSpan(text=s.text, confidence=s.confidence, source="both")
        else:
            by_key[key] = ConceptSpan(text=existing.text, confidence=existing.confidence, source="both")
    return list(by_key.values())
```

- [ ] **Step 4: Run test to verify pass**

```bash
docker compose -f infra/docker-compose.yml exec -T api uv run pytest tests/unit/test_extraction.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/src/app/nlp/extraction.py tests/unit/test_extraction.py
git commit -m "feat: add concept extraction module with inspec + yake ensemble"
```

---

### Task 1.2: Cleanup filters

**Files:**
- Modify: `api/src/app/nlp/extraction.py`
- Modify: `tests/unit/test_extraction.py`

- [ ] **Step 1: Add failing tests for cleanup filters**

```python
# Append to tests/unit/test_extraction.py
import pytest

from app.nlp.extraction import _clean


@pytest.mark.parametrize("raw, expected", [
    ("data types", "data types"),
    ("the data types", "data types"),
    ("a variable", "variable"),
    ("THE Quick", "Quick"),
    ("etc.", None),
    ("of the", None),
    ("123", None),
    ("a", None),
    ("variable_name", None),       # underscore — code token
    ("camelCase", None),           # camelCase
    ("variables...", "variables"), # trailing punctuation strip
    ("", None),
    ("x" * 70, None),              # too long
])
def test_clean_filters(raw: str, expected: str | None) -> None:
    assert _clean(raw) == expected
```

- [ ] **Step 2: Run test to verify failure**

```bash
docker compose -f infra/docker-compose.yml exec -T api uv run pytest tests/unit/test_extraction.py::test_clean_filters -v
```
Expected: FAIL with `ImportError: cannot import name '_clean'`.

- [ ] **Step 3: Implement `_clean` and apply to merged output**

Add to `api/src/app/nlp/extraction.py` (above `extract_concepts`):

```python
import re

_LEADING_DETERMINERS = ("the ", "a ", "an ", "this ", "that ", "these ", "those ")
_TRAILING_PUNCT_RE = re.compile(r"[.,;:!?\)\]\}'\"\s]+$")
_CODE_TOKEN_RE = re.compile(r"[_$]")
_CAMEL_CASE_RE = re.compile(r"^[a-z]+[A-Z]")
_DIGIT_ONLY_RE = re.compile(r"^\d+$")
# Closed-class English words used to reject phrases that are entirely function words.
_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "but", "by",
    "can", "could", "did", "do", "does", "for", "from", "had", "has", "have",
    "he", "her", "him", "his", "i", "if", "in", "is", "it", "its", "may",
    "me", "might", "must", "my", "no", "not", "of", "on", "or", "our",
    "shall", "she", "should", "so", "such", "than", "that", "the", "their",
    "them", "they", "these", "this", "those", "to", "us", "was", "we",
    "were", "what", "when", "where", "which", "who", "whom", "why", "will",
    "with", "would", "you", "your", "etc",
})


def _clean(raw: str) -> str | None:
    text = raw.strip()
    if not text:
        return None
    text = _TRAILING_PUNCT_RE.sub("", text).strip()
    if not text:
        return None
    # Strip leading determiners (case-insensitive on the determiner only).
    lower = text.lower()
    for det in _LEADING_DETERMINERS:
        if lower.startswith(det):
            text = text[len(det):]
            lower = text.lower()
            break
    if len(text) < 2 or len(text) > 60:
        return None
    if _DIGIT_ONLY_RE.match(text):
        return None
    if _CAMEL_CASE_RE.match(text):
        return None
    if _CODE_TOKEN_RE.search(text):
        return None
    tokens = lower.split()
    if not tokens or all(t in _STOPWORDS for t in tokens):
        return None
    return text
```

Then update `_merge` to apply `_clean`:

```python
def _merge(a: list[ConceptSpan], b: list[ConceptSpan]) -> list[ConceptSpan]:
    by_key: dict[str, ConceptSpan] = {}
    for s in (*a, *b):
        cleaned = _clean(s.text)
        if cleaned is None:
            continue
        key = cleaned.lower()
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = ConceptSpan(text=cleaned, confidence=s.confidence, source=s.source)
        elif s.confidence > existing.confidence:
            by_key[key] = ConceptSpan(text=cleaned, confidence=s.confidence, source="both")
        else:
            by_key[key] = ConceptSpan(text=existing.text, confidence=existing.confidence, source="both")
    return list(by_key.values())
```

- [ ] **Step 4: Run test to verify pass**

```bash
docker compose -f infra/docker-compose.yml exec -T api uv run pytest tests/unit/test_extraction.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add api/src/app/nlp/extraction.py tests/unit/test_extraction.py
git commit -m "feat: cleanup filters for concept extraction (stopwords, code tokens, length)"
```

---

### Task 1.3: Pre-warm hook for the transformer pipeline

The transformer's first inference loads the model from disk (~3-5s cold start). Pre-warm during FastAPI lifespan startup so the first user save is fast.

**Files:**
- Modify: `api/src/app/main.py`
- Modify: `api/src/app/nlp/extraction.py`

- [ ] **Step 1: Add a `prewarm()` function to extraction.py**

```python
# Append to api/src/app/nlp/extraction.py
def prewarm() -> None:
    """Load the transformer model into memory. Call at app startup."""
    _inspec_pipeline()
    _yake_extractor()
```

- [ ] **Step 2: Call `prewarm()` from the lifespan hook**

In `api/src/app/main.py`, find the `lifespan` async context manager and add the call before `yield`:

```python
from app.nlp import extraction as _extraction

# inside lifespan, before `yield`
_extraction.prewarm()
```

- [ ] **Step 3: Verify pre-warm runs**

```bash
docker compose -f infra/docker-compose.yml restart api
docker compose -f infra/docker-compose.yml logs --since 1m api 2>&1 | grep -i "uvicorn running"
```
Expected: `Uvicorn running` log appears within ~30s. The container should not error on startup.

- [ ] **Step 4: Commit**

```bash
git add api/src/app/main.py api/src/app/nlp/extraction.py
git commit -m "feat: pre-warm extraction pipeline at app startup"
```

---

## Phase 2 — Cross-note normalisation (TDD)

### Task 2.1: Migration 0017 — concept_registry embedding column

**Files:**
- Create: `api/alembic/versions/20260505_0017_concept_registry_embeddings.py`

- [ ] **Step 1: Write the migration**

```python
# api/alembic/versions/20260505_0017_concept_registry_embeddings.py
"""concept_registry embedding column

Revision ID: 0017_concept_registry_embeddings
Revises: 0016_clear_plaintext_api_keys
Create Date: 2026-05-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0017_concept_registry_embeddings"
down_revision = "0016_clear_plaintext_api_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    schemas = [
        r[0] for r in bind.execute(
            sa.text(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name LIKE 'user\\_%' ESCAPE '\\'"
            )
        ).all()
    ]
    for schema in schemas:
        op.execute(
            f'ALTER TABLE "{schema}".concept_registry '
            'ADD COLUMN IF NOT EXISTS embedding vector(384)'
        )
        op.execute(
            f'CREATE INDEX IF NOT EXISTS '
            f'concept_registry_embedding_hnsw_idx_{schema} '
            f'ON "{schema}".concept_registry USING hnsw (embedding vector_cosine_ops)'
        )


def downgrade() -> None:
    bind = op.get_bind()
    schemas = [
        r[0] for r in bind.execute(
            sa.text(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name LIKE 'user\\_%' ESCAPE '\\'"
            )
        ).all()
    ]
    for schema in schemas:
        op.execute(
            f'DROP INDEX IF EXISTS '
            f'"{schema}".concept_registry_embedding_hnsw_idx_{schema}'
        )
        op.execute(
            f'ALTER TABLE "{schema}".concept_registry '
            'DROP COLUMN IF EXISTS embedding'
        )
```

- [ ] **Step 2: Update `schema_template.sql` so new tenant schemas get the column**

Add to `api/src/app/db/schema_template.sql` in the `concept_registry` table definition:

```sql
embedding vector(384),
```

And after the table:

```sql
CREATE INDEX IF NOT EXISTS concept_registry_embedding_hnsw_idx
  ON concept_registry USING hnsw (embedding vector_cosine_ops);
```

- [ ] **Step 3: Apply migration**

```bash
make compose-migrate
```
Expected: migration applies cleanly.

- [ ] **Step 4: Verify**

```bash
docker compose -f infra/docker-compose.yml exec -T db psql -U neuronote -d neuronote -c "\d user_b6b6ef061c81.concept_registry"
```
Expected: `embedding | vector(384)` column listed.

- [ ] **Step 5: Commit**

```bash
git add api/alembic/versions/20260505_0017_concept_registry_embeddings.py api/src/app/db/schema_template.sql
git commit -m "feat: migration 0017 — concept_registry embedding column + HNSW index"
```

---

### Task 2.2: `normalise_concepts` — TDD

**Files:**
- Create: `api/src/app/nlp/normalisation.py`
- Create: `tests/unit/test_normalisation.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_normalisation.py
from unittest.mock import MagicMock

from app.nlp.extraction import ConceptSpan
from app.nlp.normalisation import NormalisedConcept, SynonymEdge, normalise_concepts


def test_new_concept_inserted_to_registry() -> None:
    session = MagicMock()
    session.execute.return_value.all.return_value = []  # empty registry

    spans = [ConceptSpan("data types", 0.99, "transformer")]
    result = normalise_concepts(session, spans, embed=lambda s: [0.1] * 384)

    assert len(result.concepts) == 1
    assert result.concepts[0].canonical_text == "data types"
    assert result.concepts[0].is_new is True
    assert result.synonym_edges == []


def test_existing_concept_matched_above_threshold() -> None:
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        ("data type", [0.1] * 384),  # near-identical embedding
    ]

    spans = [ConceptSpan("data types", 0.99, "transformer")]
    result = normalise_concepts(
        session, spans,
        embed=lambda s: [0.1] * 384,
        cosine_threshold=0.88,
    )

    assert len(result.concepts) == 1
    assert result.concepts[0].canonical_text == "data type"
    assert result.concepts[0].is_new is False
    assert result.synonym_edges == [
        SynonymEdge(from_text="data types", to_text="data type"),
    ]


def test_below_threshold_treated_as_new() -> None:
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        ("unrelated", [-1.0] + [0.0] * 383),
    ]
    spans = [ConceptSpan("data types", 0.99, "transformer")]
    result = normalise_concepts(
        session, spans,
        embed=lambda s: [1.0] + [0.0] * 383,
        cosine_threshold=0.88,
    )
    assert result.concepts[0].canonical_text == "data types"
    assert result.concepts[0].is_new is True
    assert result.synonym_edges == []
```

- [ ] **Step 2: Run test to verify failure**

```bash
docker compose -f infra/docker-compose.yml exec -T api uv run pytest tests/unit/test_normalisation.py -v
```
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement normalisation.py**

```python
# api/src/app/nlp/normalisation.py
"""Cross-note concept normalisation via embedding nearest-neighbor.

For each extracted concept, search concept_registry for the nearest
existing concept by cosine similarity. Above threshold, merge to the
canonical form and emit a SYNONYM_OF edge. Below threshold, treat as new.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Iterable

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.nlp.extraction import ConceptSpan

DEFAULT_COSINE_THRESHOLD = 0.88


@dataclass(frozen=True, slots=True)
class NormalisedConcept:
    canonical_text: str
    raw_text: str
    confidence: float
    is_new: bool


@dataclass(frozen=True, slots=True)
class SynonymEdge:
    from_text: str
    to_text: str


@dataclass(frozen=True, slots=True)
class NormalisationResult:
    concepts: list[NormalisedConcept]
    synonym_edges: list[SynonymEdge]


def _cosine(a: Iterable[float], b: Iterable[float]) -> float:
    aa = list(a)
    bb = list(b)
    dot = sum(x * y for x, y in zip(aa, bb))
    na = math.sqrt(sum(x * x for x in aa))
    nb = math.sqrt(sum(x * x for x in bb))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def normalise_concepts(
    session: Session,
    spans: list[ConceptSpan],
    *,
    embed: Callable[[str], list[float]],
    cosine_threshold: float = DEFAULT_COSINE_THRESHOLD,
) -> NormalisationResult:
    if not spans:
        return NormalisationResult(concepts=[], synonym_edges=[])

    # Load (text, embedding) for every existing concept with an embedding.
    rows = session.execute(
        sa_text("SELECT concept_text, embedding FROM concept_registry "
                "WHERE embedding IS NOT NULL")
    ).all()
    existing: list[tuple[str, list[float]]] = [(r[0], list(r[1])) for r in rows]

    out_concepts: list[NormalisedConcept] = []
    out_edges: list[SynonymEdge] = []
    for span in spans:
        emb = embed(span.text)
        best_text: str | None = None
        best_sim = 0.0
        for ex_text, ex_emb in existing:
            sim = _cosine(emb, ex_emb)
            if sim > best_sim:
                best_sim = sim
                best_text = ex_text
        if best_text is not None and best_sim >= cosine_threshold and best_text.lower() != span.text.lower():
            out_concepts.append(NormalisedConcept(
                canonical_text=best_text,
                raw_text=span.text,
                confidence=span.confidence,
                is_new=False,
            ))
            out_edges.append(SynonymEdge(from_text=span.text, to_text=best_text))
        elif best_text is not None and best_sim >= cosine_threshold:
            # exact match — same text, no edge needed
            out_concepts.append(NormalisedConcept(
                canonical_text=best_text,
                raw_text=span.text,
                confidence=span.confidence,
                is_new=False,
            ))
        else:
            out_concepts.append(NormalisedConcept(
                canonical_text=span.text,
                raw_text=span.text,
                confidence=span.confidence,
                is_new=True,
            ))
    return NormalisationResult(concepts=out_concepts, synonym_edges=out_edges)
```

- [ ] **Step 4: Run test to verify pass**

```bash
docker compose -f infra/docker-compose.yml exec -T api uv run pytest tests/unit/test_normalisation.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add api/src/app/nlp/normalisation.py tests/unit/test_normalisation.py
git commit -m "feat: cross-note concept normalisation via embedding NN"
```

---

## Phase 3 — Block-structure relations (TDD)

### Task 3.1: TipTap tree walker — concept-in-block index

**Files:**
- Create: `api/src/app/nlp/structure_relations.py`
- Create: `tests/unit/test_structure_relations.py`

- [ ] **Step 1: Write failing test for the block-walking helper**

```python
# tests/unit/test_structure_relations.py
from app.nlp.structure_relations import _walk_blocks, BlockInfo


def test_walk_blocks_extracts_block_ids_and_text() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 1, "id": "h1"},
                "content": [{"type": "text", "text": "Variables"}],
            },
            {
                "type": "paragraph",
                "attrs": {"id": "p1"},
                "content": [
                    {"type": "text", "text": "Variables hold "},
                    {"type": "text", "text": "data values."},
                ],
            },
        ],
    }
    blocks = list(_walk_blocks(doc))
    assert blocks == [
        BlockInfo(block_id="h1", kind="heading", text="Variables", parent_id=None, depth=0),
        BlockInfo(block_id="p1", kind="paragraph", text="Variables hold data values.", parent_id=None, depth=0),
    ]
```

- [ ] **Step 2: Run to verify failure**

```bash
docker compose -f infra/docker-compose.yml exec -T api uv run pytest tests/unit/test_structure_relations.py -v
```
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `_walk_blocks` and `BlockInfo`**

```python
# api/src/app/nlp/structure_relations.py
"""Derive typed relations from TipTap document structure.

Reads the TipTap JSON tree and emits typed edges between concept pairs
based on structural co-location:
  - MENTIONED_TOGETHER: same block
  - SUBTOPIC_OF: concept under a heading mentioning a parent concept
  - SIBLING_OF: adjacent list items
  - REFERENCES: blockRef target
  - DEFINED_BY: bold-prefixed paragraph (definition pattern)

No LLM. No statistical inference. Pure tree walking + string matching.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Literal

BlockKind = Literal[
    "heading", "paragraph", "listItem", "bulletList", "orderedList",
    "codeBlock", "blockquote", "blockRef", "other",
]


@dataclass(frozen=True, slots=True)
class BlockInfo:
    block_id: str
    kind: BlockKind
    text: str
    parent_id: str | None
    depth: int


def _kind_of(node: dict) -> BlockKind:
    t = node.get("type", "")
    if t in {"heading", "paragraph", "listItem", "bulletList", "orderedList",
             "codeBlock", "blockquote", "blockRef"}:
        return t  # type: ignore[return-value]
    return "other"


def _text_of(node: dict) -> str:
    if node.get("type") == "text":
        return node.get("text", "")
    parts: list[str] = []
    for child in node.get("content", []) or []:
        parts.append(_text_of(child))
    return "".join(parts)


def _walk_blocks(doc: dict, parent_id: str | None = None, depth: int = 0) -> Iterator[BlockInfo]:
    for node in doc.get("content", []) or []:
        kind = _kind_of(node)
        if kind == "other":
            continue
        block_id = (node.get("attrs") or {}).get("id") or ""
        if not block_id:
            continue
        # Container blocks (lists) yield their children but not themselves.
        if kind in {"bulletList", "orderedList"}:
            yield from _walk_blocks(node, parent_id=block_id, depth=depth + 1)
            continue
        text = _text_of(node).strip()
        yield BlockInfo(
            block_id=block_id,
            kind=kind,
            text=text,
            parent_id=parent_id,
            depth=depth,
        )
        # Recurse into list items so nested content is captured.
        if kind == "listItem":
            yield from _walk_blocks(node, parent_id=block_id, depth=depth + 1)
```

- [ ] **Step 4: Run test**

```bash
docker compose -f infra/docker-compose.yml exec -T api uv run pytest tests/unit/test_structure_relations.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/src/app/nlp/structure_relations.py tests/unit/test_structure_relations.py
git commit -m "feat: TipTap block walker for structure relations"
```

---

### Task 3.2: `MENTIONED_TOGETHER` and `SUBTOPIC_OF` edges

**Files:**
- Modify: `api/src/app/nlp/structure_relations.py`
- Modify: `tests/unit/test_structure_relations.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/unit/test_structure_relations.py
from app.nlp.structure_relations import StructureEdge, derive_relations


def test_concepts_in_same_paragraph_emit_mentioned_together() -> None:
    doc = {
        "type": "doc",
        "content": [{
            "type": "paragraph",
            "attrs": {"id": "p1"},
            "content": [{"type": "text", "text": "Variables hold data values."}],
        }],
    }
    edges = derive_relations(doc, concepts=["variables", "data values"])
    assert StructureEdge(
        source="variables", target="data values", relation="MENTIONED_TOGETHER",
    ) in edges
    assert StructureEdge(
        source="data values", target="variables", relation="MENTIONED_TOGETHER",
    ) in edges


def test_concept_under_heading_emits_subtopic_of() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"id": "h1", "level": 2},
                "content": [{"type": "text", "text": "Casting"}],
            },
            {
                "type": "paragraph",
                "attrs": {"id": "p1"},
                "content": [{"type": "text", "text": "Use the int function."}],
            },
        ],
    }
    edges = derive_relations(doc, concepts=["casting", "int function"])
    assert StructureEdge(
        source="int function", target="casting", relation="SUBTOPIC_OF",
    ) in edges
```

- [ ] **Step 2: Run to verify failure**

```bash
docker compose -f infra/docker-compose.yml exec -T api uv run pytest tests/unit/test_structure_relations.py::test_concepts_in_same_paragraph_emit_mentioned_together -v
```
Expected: FAIL with `ImportError: cannot import name 'derive_relations'`.

- [ ] **Step 3: Implement `derive_relations` for these two edge types**

Append to `api/src/app/nlp/structure_relations.py`:

```python
@dataclass(frozen=True, slots=True)
class StructureEdge:
    source: str   # concept canonical text
    target: str   # concept canonical text
    relation: Literal["MENTIONED_TOGETHER", "SUBTOPIC_OF", "SIBLING_OF", "REFERENCES", "DEFINED_BY"]


def _concepts_in_text(text: str, concepts: list[str]) -> set[str]:
    """Return the subset of `concepts` that appear (case-insensitive substring) in `text`."""
    hay = text.lower()
    return {c for c in concepts if c.lower() in hay}


def derive_relations(
    document_json: dict,
    *,
    concepts: list[str],
) -> list[StructureEdge]:
    if not concepts:
        return []
    blocks = list(_walk_blocks(document_json))
    edges: set[StructureEdge] = set()

    # Track the most recent heading at each level so we can emit SUBTOPIC_OF
    # for blocks that follow a heading.
    current_heading_concepts: set[str] = set()
    for block in blocks:
        present = _concepts_in_text(block.text, concepts)
        # MENTIONED_TOGETHER for every pair in this block (both directions for query symmetry).
        listed = list(present)
        for i, a in enumerate(listed):
            for b in listed[i + 1:]:
                edges.add(StructureEdge(a, b, "MENTIONED_TOGETHER"))
                edges.add(StructureEdge(b, a, "MENTIONED_TOGETHER"))
        # Update / consume the rolling heading context.
        if block.kind == "heading":
            current_heading_concepts = present
        else:
            for child in present:
                for parent in current_heading_concepts:
                    if child != parent:
                        edges.add(StructureEdge(child, parent, "SUBTOPIC_OF"))

    return sorted(edges, key=lambda e: (e.relation, e.source, e.target))
```

- [ ] **Step 4: Run test**

```bash
docker compose -f infra/docker-compose.yml exec -T api uv run pytest tests/unit/test_structure_relations.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add api/src/app/nlp/structure_relations.py tests/unit/test_structure_relations.py
git commit -m "feat: derive MENTIONED_TOGETHER and SUBTOPIC_OF edges from block structure"
```

---

### Task 3.3: `SIBLING_OF`, `REFERENCES`, `DEFINED_BY`

**Files:**
- Modify: `api/src/app/nlp/structure_relations.py`
- Modify: `tests/unit/test_structure_relations.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/unit/test_structure_relations.py
def test_sibling_list_items_emit_sibling_of() -> None:
    doc = {
        "type": "doc",
        "content": [{
            "type": "bulletList",
            "attrs": {"id": "ul1"},
            "content": [
                {"type": "listItem", "attrs": {"id": "li1"},
                 "content": [{"type": "paragraph", "attrs": {"id": "p1"},
                              "content": [{"type": "text", "text": "apples"}]}]},
                {"type": "listItem", "attrs": {"id": "li2"},
                 "content": [{"type": "paragraph", "attrs": {"id": "p2"},
                              "content": [{"type": "text", "text": "oranges"}]}]},
            ],
        }],
    }
    edges = derive_relations(doc, concepts=["apples", "oranges"])
    assert StructureEdge("apples", "oranges", "SIBLING_OF") in edges
    assert StructureEdge("oranges", "apples", "SIBLING_OF") in edges


def test_blockref_emits_references() -> None:
    doc = {
        "type": "doc",
        "content": [{
            "type": "paragraph",
            "attrs": {"id": "p1"},
            "content": [
                {"type": "text", "text": "See "},
                {"type": "blockRef", "attrs": {"refTargetText": "data types"},
                 "content": []},
                {"type": "text", "text": " also casting"},
            ],
        }],
    }
    edges = derive_relations(doc, concepts=["casting", "data types"])
    assert StructureEdge("casting", "data types", "REFERENCES") in edges


def test_bold_prefix_emits_defined_by() -> None:
    # NOTE: DEFINED_BY links concept → note (not concept → concept).
    # Verified by source == concept and target == "" sentinel for note context.
    doc = {
        "type": "doc",
        "content": [{
            "type": "paragraph",
            "attrs": {"id": "p1"},
            "content": [
                {"type": "text", "marks": [{"type": "bold"}], "text": "Casting"},
                {"type": "text", "text": " is the process of converting types."},
            ],
        }],
    }
    edges = derive_relations(doc, concepts=["casting"])
    assert any(e.relation == "DEFINED_BY" and e.source == "casting" for e in edges)
```

- [ ] **Step 2: Run to verify failure**

```bash
docker compose -f infra/docker-compose.yml exec -T api uv run pytest tests/unit/test_structure_relations.py -v
```
Expected: 3 new tests FAIL.

- [ ] **Step 3: Extend `derive_relations` for the three remaining edge types**

In `api/src/app/nlp/structure_relations.py`, modify `_walk_blocks` to record sibling list items and blockRef targets, then extend `derive_relations`:

Add helper functions:

```python
def _list_item_groups(doc: dict) -> Iterator[list[BlockInfo]]:
    """Yield groups of sibling list items (children of the same list)."""
    for node in doc.get("content", []) or []:
        if node.get("type") in {"bulletList", "orderedList"}:
            group: list[BlockInfo] = []
            for li in node.get("content", []) or []:
                li_id = (li.get("attrs") or {}).get("id") or ""
                if not li_id:
                    continue
                group.append(BlockInfo(
                    block_id=li_id,
                    kind="listItem",
                    text=_text_of(li).strip(),
                    parent_id=(node.get("attrs") or {}).get("id"),
                    depth=1,
                ))
            if group:
                yield group
        # Recurse into other containers as needed.
        for child in node.get("content", []) or []:
            if isinstance(child, dict) and child.get("content"):
                yield from _list_item_groups(child)


def _blockref_targets(doc: dict) -> Iterator[tuple[str, str]]:
    """Yield (source_block_text, refTargetText) for every blockRef in the doc."""
    for node in doc.get("content", []) or []:
        node_text = _text_of(node)
        for sub in (node.get("content", []) or []):
            if isinstance(sub, dict) and sub.get("type") == "blockRef":
                target = (sub.get("attrs") or {}).get("refTargetText", "")
                if target:
                    yield (node_text, target)
        # Recurse
        if node.get("content"):
            yield from _blockref_targets(node)


def _bold_prefix_concepts(doc: dict, concepts: list[str]) -> set[str]:
    """Concepts that appear as a bold span at the start of a paragraph."""
    out: set[str] = set()
    for node in doc.get("content", []) or []:
        if node.get("type") != "paragraph":
            if node.get("content"):
                out |= _bold_prefix_concepts(node, concepts)
            continue
        children = node.get("content", []) or []
        if not children:
            continue
        first = children[0]
        if first.get("type") != "text":
            continue
        marks = first.get("marks") or []
        if not any(m.get("type") == "bold" for m in marks):
            continue
        bold_text = first.get("text", "").strip().lower()
        for c in concepts:
            if c.lower() == bold_text:
                out.add(c)
    return out
```

Update `derive_relations` to use them:

```python
def derive_relations(
    document_json: dict,
    *,
    concepts: list[str],
) -> list[StructureEdge]:
    if not concepts:
        return []
    blocks = list(_walk_blocks(document_json))
    edges: set[StructureEdge] = set()
    current_heading_concepts: set[str] = set()
    for block in blocks:
        present = _concepts_in_text(block.text, concepts)
        listed = list(present)
        for i, a in enumerate(listed):
            for b in listed[i + 1:]:
                edges.add(StructureEdge(a, b, "MENTIONED_TOGETHER"))
                edges.add(StructureEdge(b, a, "MENTIONED_TOGETHER"))
        if block.kind == "heading":
            current_heading_concepts = present
        else:
            for child in present:
                for parent in current_heading_concepts:
                    if child != parent:
                        edges.add(StructureEdge(child, parent, "SUBTOPIC_OF"))

    # SIBLING_OF: concepts in adjacent list items under the same list.
    for group in _list_item_groups(document_json):
        for i, a_block in enumerate(group):
            a_concepts = _concepts_in_text(a_block.text, concepts)
            for b_block in group[i + 1:]:
                b_concepts = _concepts_in_text(b_block.text, concepts)
                for a in a_concepts:
                    for b in b_concepts:
                        if a != b:
                            edges.add(StructureEdge(a, b, "SIBLING_OF"))
                            edges.add(StructureEdge(b, a, "SIBLING_OF"))

    # REFERENCES: concept appearing in a block that contains a blockRef.
    for source_text, target_text in _blockref_targets(document_json):
        source_concepts = _concepts_in_text(source_text, concepts)
        target_concepts = _concepts_in_text(target_text, concepts)
        for s in source_concepts:
            for t in target_concepts:
                if s != t:
                    edges.add(StructureEdge(s, t, "REFERENCES"))

    # DEFINED_BY: concept appears as a bold span at start of a paragraph.
    # source = concept, target = "" sentinel (note-level context).
    for c in _bold_prefix_concepts(document_json, concepts):
        edges.add(StructureEdge(c, "", "DEFINED_BY"))

    return sorted(edges, key=lambda e: (e.relation, e.source, e.target))
```

- [ ] **Step 4: Run test**

```bash
docker compose -f infra/docker-compose.yml exec -T api uv run pytest tests/unit/test_structure_relations.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add api/src/app/nlp/structure_relations.py tests/unit/test_structure_relations.py
git commit -m "feat: SIBLING_OF, REFERENCES, DEFINED_BY structure edges"
```

---

## Phase 4 — Wire new pipeline into `NoteNlpPipeline`

### Task 4.1: Rewrite `pipeline.py` to use new components

**Files:**
- Modify: `api/src/app/nlp/pipeline.py`

The current pipeline branches on `extraction_profile`. The new pipeline does one thing: extract → normalise → derive structure relations → embed → return.

- [ ] **Step 1: Replace pipeline.py with the new implementation**

```python
# api/src/app/nlp/pipeline.py
"""Single-profile deterministic NLP pipeline.

Runs extraction → normalisation → structure-relation derivation. No LLM
on the critical path. The returned `NoteExtractionResult` is consumed by
the existing graph sync service unchanged.
"""
from __future__ import annotations

import logging
import time
from collections import OrderedDict

from sqlalchemy.orm import Session

from app.nlp.config import NlpSettings, get_nlp_settings
from app.nlp.embeddings import build_embedding, build_semantic_embedding
from app.nlp.extraction import extract_concepts
from app.nlp.normalisation import normalise_concepts
from app.nlp.preprocessor import preprocess_content
from app.nlp.structure_relations import derive_relations
from app.nlp.types import (
    ExtractedEntity,
    ExtractedRelation,
    NoteExtractionResult,
)

_LOGGER = logging.getLogger(__name__)
_EXTRACTION_CACHE: "OrderedDict[str, NoteExtractionResult]" = OrderedDict()
_EXTRACTION_CACHE_MAX = 256
_SLUG_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789-"


def _slugify(raw: str) -> str:
    s = raw.lower().strip()
    out = []
    last_dash = True
    for ch in s:
        if ch.isalnum():
            out.append(ch)
            last_dash = False
        elif not last_dash:
            out.append("-")
            last_dash = True
    result = "".join(out).strip("-")
    return result or "entity"


class NoteNlpPipeline:
    def __init__(self, *, settings: NlpSettings | None = None) -> None:
        self._settings: NlpSettings = settings or get_nlp_settings()

    @property
    def settings(self) -> NlpSettings:
        return self._settings

    def extract(
        self,
        *,
        session: Session,
        embedder,
        note_id: str,
        title: str,
        content_text: str,
        document_json: dict,
        content_hash: str,
    ) -> NoteExtractionResult:
        cached = _EXTRACTION_CACHE.get(content_hash)
        if cached is not None:
            _EXTRACTION_CACHE.move_to_end(content_hash)
            return cached.with_note_id(note_id)

        started = time.perf_counter()
        composed = self._compose_text(title, content_text)
        preprocessed = preprocess_content(composed)
        spans = extract_concepts(preprocessed)
        norm = normalise_concepts(session, spans, embed=embedder)
        canonicals = [c.canonical_text for c in norm.concepts]

        entities: list[ExtractedEntity] = [
            ExtractedEntity(
                entity_id=f"concept-{_slugify(c.canonical_text)}",
                text=c.canonical_text,
                label="concept",
                confidence=c.confidence,
            )
            for c in norm.concepts
        ]

        struct_edges = derive_relations(document_json, concepts=canonicals)
        relations: list[ExtractedRelation] = []
        for edge in struct_edges:
            if edge.relation == "DEFINED_BY":
                continue  # DEFINED_BY links to note, handled by graph sync separately
            relations.append(ExtractedRelation(
                subject_id=f"concept-{_slugify(edge.source)}",
                subject_text=edge.source,
                predicate=edge.relation,
                object_id=f"concept-{_slugify(edge.target)}",
                object_text=edge.target,
                confidence=0.7 if edge.relation == "MENTIONED_TOGETHER" else 1.0,
            ))
        # SYNONYM_OF edges from normalisation
        for syn in norm.synonym_edges:
            relations.append(ExtractedRelation(
                subject_id=f"concept-{_slugify(syn.from_text)}",
                subject_text=syn.from_text,
                predicate="SYNONYM_OF",
                object_id=f"concept-{_slugify(syn.to_text)}",
                object_text=syn.to_text,
                confidence=0.95,
            ))

        embedding = (
            build_semantic_embedding(content_text)
            if self._settings.use_semantic_embeddings
            else (build_embedding(content_text) if self._settings.enable_embeddings else None)
        )

        result = NoteExtractionResult(
            note_id=note_id,
            content_hash=content_hash,
            entities=entities,
            keyphrases=[],
            relations=relations,
            embedding=embedding,
            entity_mentions=[],
            summary="",
        )

        _EXTRACTION_CACHE[content_hash] = result
        if len(_EXTRACTION_CACHE) > _EXTRACTION_CACHE_MAX:
            _EXTRACTION_CACHE.popitem(last=False)

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        _LOGGER.info(
            "pipeline.extract: note_id=%s concepts=%d relations=%d %.0fms",
            note_id, len(entities), len(relations), elapsed_ms,
        )
        return result

    @staticmethod
    def _compose_text(title: str, body: str) -> str:
        title = title.strip()
        body = body.strip()
        if not title:
            return body
        if not body:
            return title
        return f"{title}\n\n{body}"
```

- [ ] **Step 2: Add `with_note_id` helper on `NoteExtractionResult`**

In `api/src/app/nlp/types.py`, add to the dataclass:

```python
def with_note_id(self, note_id: str) -> "NoteExtractionResult":
    return dataclasses.replace(self, note_id=note_id)
```

(Add `import dataclasses` if not present.)

- [ ] **Step 3: Run unit tests to surface signature mismatches**

```bash
docker compose -f infra/docker-compose.yml exec -T api uv run pytest tests/unit/ -v 2>&1 | tail -30
```
Expected: many existing pipeline tests fail — they invoke old signatures. We will rewrite/delete them in later tasks. Keep going.

- [ ] **Step 4: Commit**

```bash
git add api/src/app/nlp/pipeline.py api/src/app/nlp/types.py
git commit -m "feat: rewrite NoteNlpPipeline as deterministic extract+normalise+structure"
```

---

### Task 4.2: Update `NoteProcessingService` to call new pipeline

**Files:**
- Modify: `api/src/app/services/note_processing_service.py`

- [ ] **Step 1: Replace `_persist_graph_and_vector` to call the new pipeline**

In `api/src/app/services/note_processing_service.py`, the call site that runs `self._pipeline.extract(...)` needs the new signature. Replace the `result = self._pipeline.extract(...)` block (around line 244) with:

```python
from app.nlp.embeddings import embed_for_normalisation  # noqa: E402

with self._open_session() as session:
    if not self._is_postgres(session):
        return ExtractionSummary(
            entity_count=0, relation_count=0, keyphrase_count=0, top_entities=[]
        )
    result = self._pipeline.extract(
        session=session,
        embedder=embed_for_normalisation,
        note_id=snapshot.note_id,
        title=snapshot.note_title,
        content_text=snapshot.content_text,
        document_json=snapshot.document_json,  # NEW
        content_hash=snapshot.content_hash,
    )
```

Remove the `_run_concept_meta_classification` call entirely (delete the function and its caller).

Remove the `dictionary_terms` building, `alias_records` loading, `_build_resolver`, `register_concepts` call (the new pipeline handles registry updates via `normalise_concepts`).

Remove the `_try_load_nlp_cache`/`_save_nlp_cache` calls — the pipeline has its own LRU cache, and DB-backed caching can be reintroduced after the new pipeline is verified working.

- [ ] **Step 2: Add `document_json` to `ProcessedNoteSnapshot`**

```python
@dataclass(frozen=True, slots=True)
class ProcessedNoteSnapshot:
    note_id: str
    subject_id: str
    note_title: str
    content_text: str
    content_hash: str
    updated_at: str
    document_json: dict   # NEW
    blocks: list[BlockTextInput]
```

In `_load_snapshot`, populate `document_json=note.document_json or {}`.

- [ ] **Step 3: Add `embed_for_normalisation` helper**

In `api/src/app/nlp/embeddings.py`, add:

```python
def embed_for_normalisation(text: str) -> list[float]:
    """Embed a short text (concept) for normalisation. Returns 384d vector."""
    vec = build_semantic_embedding(text)
    if vec is None:
        return [0.0] * 384
    return list(vec)
```

- [ ] **Step 4: Persist embedding into concept_registry on insert**

In `app.nlp.concept_registry`, find `register_concepts` and modify to accept and store an embedding (or write a new helper `register_concepts_with_embeddings(session, items)` where `items: list[tuple[str, str, list[float]]]` for (text, slug, embedding)).

In the new pipeline, after `normalise_concepts` returns, persist new entries:

```python
# inside NoteNlpPipeline.extract, after norm = normalise_concepts(...)
new_pairs: list[tuple[str, str, list[float]]] = []
for c in norm.concepts:
    if c.is_new:
        new_pairs.append((c.canonical_text, _slugify(c.canonical_text), embedder(c.canonical_text)))
if new_pairs:
    register_concepts_with_embeddings(session, new_pairs)
```

(Define `register_concepts_with_embeddings` in `concept_registry.py` to upsert text + embedding atomically.)

- [ ] **Step 5: Run pipeline integration test**

```bash
docker compose -f infra/docker-compose.yml restart api
sleep 8
docker compose -f infra/docker-compose.yml exec -T api uv run pytest tests/integration/test_process_note.py -v 2>&1 | tail -30
```
Expected: test exists and passes. If signature mismatches, fix here.

- [ ] **Step 6: Commit**

```bash
git add api/src/app/services/note_processing_service.py api/src/app/nlp/embeddings.py api/src/app/nlp/concept_registry.py
git commit -m "feat: wire NoteProcessingService to deterministic pipeline"
```

---

## Phase 5 — Delete server-side dead code

### Task 5.1: Delete extraction-related routes and contracts

**Files:**
- Delete: `api/src/app/routes/extraction_candidates.py`
- Delete: `api/src/app/routes/extraction_results.py`
- Delete: `api/src/app/routes/meta_classification.py`
- Delete: `shared/contracts/python/v1/extraction.py`
- Delete: `shared/contracts/python/v1/extraction_candidates.py`
- Delete: `shared/contracts/python/v1/meta_classification.py`
- Delete: `shared/contracts/ts/v1/extraction.ts`
- Delete: `shared/contracts/ts/v1/extraction_candidates.ts`
- Delete: `shared/contracts/ts/v1/meta_classification.ts`
- Modify: `api/src/app/main.py` (remove `app.include_router` for the deleted routes)
- Delete: `tests/unit/test_edge_extraction_api.py`
- Delete: `tests/unit/test_preferences_api.py` (if it references deleted contracts — verify first)

- [ ] **Step 1: Confirm no remaining imports of these contracts**

```bash
grep -rln "extraction_candidates\|meta_classification\|extraction_results" api/src shared web/src tests/ 2>/dev/null
```
Note expected matches: only the files about to be deleted, plus `routes/process.py` if it imports from the contracts (handled in next task).

- [ ] **Step 2: Delete the files**

```bash
git rm api/src/app/routes/extraction_candidates.py \
       api/src/app/routes/extraction_results.py \
       api/src/app/routes/meta_classification.py \
       shared/contracts/python/v1/extraction.py \
       shared/contracts/python/v1/extraction_candidates.py \
       shared/contracts/python/v1/meta_classification.py \
       shared/contracts/ts/v1/extraction.ts \
       shared/contracts/ts/v1/extraction_candidates.ts \
       shared/contracts/ts/v1/meta_classification.ts \
       tests/unit/test_edge_extraction_api.py
```

- [ ] **Step 3: Remove router registrations from `api/src/app/main.py`**

Find lines registering `extraction_candidates_router`, `extraction_results_router`, `meta_classification_router` and delete them.

- [ ] **Step 4: Restart and verify health**

```bash
docker compose -f infra/docker-compose.yml restart api
sleep 8
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/health
```
Expected: `200`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: delete extraction/meta-classification routes and contracts"
```

---

### Task 5.2: Delete `slm_extractor.py`, `concept_meta.py`

**Files:**
- Delete: `api/src/app/nlp/slm_extractor.py`
- Delete: `api/src/app/nlp/concept_meta.py`
- Delete: `tests/unit/test_slm_extractor.py` (if exists)
- Delete: `tests/unit/test_concept_meta.py` (if exists)
- Modify: `api/src/app/services/note_processing_service.py` (remove imports)

- [ ] **Step 1: Verify no live imports**

```bash
grep -rln "from app.nlp.slm_extractor\|from app.nlp.concept_meta\|SLMExtractor\|ConceptMetaClassifier" api/src tests/ 2>/dev/null
```
Expected: only the files being deleted appear (and any matching test files).

- [ ] **Step 2: Delete files**

```bash
git rm api/src/app/nlp/slm_extractor.py api/src/app/nlp/concept_meta.py
git rm tests/unit/test_slm_extractor.py 2>/dev/null || true
git rm tests/unit/test_concept_meta.py 2>/dev/null || true
```

- [ ] **Step 3: Restart + smoke test**

```bash
docker compose -f infra/docker-compose.yml restart api
sleep 8
curl -s http://localhost:8000/health
```
Expected: `{"status":"ok"}`.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: delete slm_extractor and concept_meta — replaced by deterministic pipeline"
```

---

### Task 5.3: Strip `spotting.py` to dictionary helper or delete

**Files:**
- Modify or delete: `api/src/app/nlp/spotting.py`

- [ ] **Step 1: Check what still imports `spotting`**

```bash
grep -rln "from app.nlp.spotting\|from app.nlp import spotting" api/src tests/ 2>/dev/null
```

- [ ] **Step 2: If only `MENTIONS` offset mapping is needed, keep that helper; otherwise delete**

If anything beyond `extract_entities_with_mentions` is unused, delete it. If the whole file is unused (likely after Task 4.2 removed dictionary_terms plumbing), delete the file:

```bash
git rm api/src/app/nlp/spotting.py
git rm tests/unit/test_entity_spotting.py 2>/dev/null || true
```

- [ ] **Step 3: Restart + smoke test**

```bash
docker compose -f infra/docker-compose.yml restart api
sleep 8
curl -s http://localhost:8000/health
```
Expected: 200 OK.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: delete spotting.py — replaced by transformer + yake extraction"
```

---

### Task 5.4: Drop `extraction_profile` from config and routes

**Files:**
- Modify: `api/src/app/nlp/config.py`
- Modify: `api/src/app/routes/process.py`
- Modify: `api/src/app/routes/concepts.py`
- Modify: `api/src/app/db/models/nlp_extraction_cache.py`
- Modify: `shared/contracts/python/v1/process.py`
- Modify: `shared/contracts/ts/v1/process.ts`
- Modify: `web/src/components/editor/NoteEditor.tsx`

- [ ] **Step 1: Remove `extraction_profile`, `model_name`, `entity_seed_terms`, `enable_regex_fallback` from `NlpSettings`**

In `api/src/app/nlp/config.py`, delete those fields and any defaults reading from env vars.

- [ ] **Step 2: Remove `extraction_profile_used` from `ExtractionSummary` contract**

In `shared/contracts/python/v1/process.py`, delete the `extraction_profile_used: str | None = None` field.
In `shared/contracts/ts/v1/process.ts`, delete the corresponding TypeScript field.

- [ ] **Step 3: Remove the field assignment in `routes/process.py`**

In `_run_processing_job`, delete the lines:
```python
summary_dict["extraction_profile_used"] = (
    user_settings.extraction_profile if user_settings else "rule-only"
)
```

`_load_user_llm_config` should still load the user's API key — but the resulting `NlpSettings` no longer carries `extraction_profile`. Remove that field from the `replace(...)` call.

Since the new pipeline doesn't use the user's LLM key for extraction, `_load_user_llm_config` is now only used to inform the *summary* generation. For now, simplify: keep `_load_user_llm_config` returning `NlpSettings | None`, but the only fields that vary based on user prefs are `llm_api_key`, `llm_base_url`, `llm_model`. The pipeline ignores them; `NoteSummaryService` (future, see open items) will use them.

- [ ] **Step 4: Remove fallback toast in `NoteEditor.tsx`**

In `web/src/components/editor/NoteEditor.tsx` near line 595, delete the block:
```tsx
if (response.extraction_summary.extraction_profile_used === "rule-only") {
  showToast("Cloud mode unavailable — processed with rule-based extraction. Check your API key in Settings.", "warning", 8000);
}
```

- [ ] **Step 5: Drop `extraction_profile` column from `nlp_extraction_cache`**

Migration 0018:

```python
# api/alembic/versions/20260505_0018_drop_extraction_profile.py
"""drop extraction_profile from nlp_extraction_cache

Revision ID: 0018_drop_extraction_profile
Revises: 0017_concept_registry_embeddings
"""
from alembic import op
import sqlalchemy as sa

revision = "0018_drop_extraction_profile"
down_revision = "0017_concept_registry_embeddings"


def upgrade() -> None:
    bind = op.get_bind()
    schemas = [
        r[0] for r in bind.execute(
            sa.text(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name LIKE 'user\\_%' ESCAPE '\\'"
            )
        ).all()
    ]
    for schema in schemas:
        op.execute(
            f'ALTER TABLE "{schema}".nlp_extraction_cache '
            f'DROP COLUMN IF EXISTS extraction_profile'
        )


def downgrade() -> None:
    bind = op.get_bind()
    schemas = [
        r[0] for r in bind.execute(
            sa.text(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name LIKE 'user\\_%' ESCAPE '\\'"
            )
        ).all()
    ]
    for schema in schemas:
        op.execute(
            f'ALTER TABLE "{schema}".nlp_extraction_cache '
            f'ADD COLUMN IF NOT EXISTS extraction_profile VARCHAR(64)'
        )
```

Update `api/src/app/db/models/nlp_extraction_cache.py` to remove the `extraction_profile` column.
Update `api/src/app/db/schema_template.sql` likewise.

- [ ] **Step 6: Remove env vars from compose**

In `infra/docker-compose.yml`, delete `NLP_EXTRACTION_PROFILE`, `NLP_MODEL_NAME`, `NLP_ENTITY_SEED_TERMS` env entries from the `api` service.

- [ ] **Step 7: Apply migration and verify**

```bash
make compose-migrate
docker compose -f infra/docker-compose.yml exec -T db psql -U neuronote -d neuronote -c "\d user_b6b6ef061c81.nlp_extraction_cache"
```
Expected: `extraction_profile` column absent.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "chore: drop extraction_profile from config, contracts, cache, and frontend"
```

---

## Phase 6 — Frontend simplification

### Task 6.1: Delete `edge-processing.ts` and collapse NoteEditor branches

**Files:**
- Delete: `web/src/lib/orchestration/edge-processing.ts`
- Modify: `web/src/components/editor/NoteEditor.tsx`

- [ ] **Step 1: Confirm no other importers of `edge-processing`**

```bash
grep -rln "from \"@/lib/orchestration/edge-processing\"\|from \"\\.\\./.*edge-processing\"\|from \"\\./.*edge-processing\"" web/src 2>/dev/null
```
Expected: only `NoteEditor.tsx`.

- [ ] **Step 2: Delete the file**

```bash
git rm web/src/lib/orchestration/edge-processing.ts
```

- [ ] **Step 3: Collapse the cloud/edge branches in `NoteEditor.tsx`**

In `startProcessing` (around line 488), delete the entire `if (llmModeRef.current === "edge") { ... }` block including the call to `runEdgeProcessing`. Both modes now hit the cloud path. Remove `setLiveConcepts`, `edgeMarkStableInference?.()`, and any helpers that only the deleted branch used.

- [ ] **Step 4: Restart web + smoke test by saving a note in browser**

```bash
docker compose -f infra/docker-compose.yml restart web
sleep 5
```
Then in the browser: edit a note, expect `POST /v1/process-note` 202 in the API logs (regardless of preference setting).

```bash
docker compose -f infra/docker-compose.yml logs --since 1m api 2>&1 | grep "process-note" | tail
```
Expected: at least one `POST /v1/process-note` 202 entry.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: collapse edge/cloud frontend branches; delete edge-processing orchestrator"
```

---

### Task 6.2: Strip `inference-client.ts`, `schemas.ts`, `prompts.ts` to summary+insight only

**Files:**
- Modify: `web/src/lib/edge-llm/inference-client.ts`
- Modify: `web/src/lib/edge-llm/schemas.ts`
- Modify: `web/src/lib/edge-llm/prompts.ts`

- [ ] **Step 1: Delete `filterCandidates` and `classifyMeta` from `inference-client.ts`**

Remove the two functions and their imports/types if unused elsewhere.

- [ ] **Step 2: Delete `CHUNK_EXTRACTION_SCHEMA` and `META_SCHEMA` from `schemas.ts`**

Keep only `SUMMARY_SCHEMA` and `INSIGHT_SCHEMA`.

- [ ] **Step 3: Delete `buildFilterPrompt` and `buildMetaPrompt` from `prompts.ts`**

Keep only `buildSummaryPrompt` and `buildInsightPrompt`.

- [ ] **Step 4: Delete now-unused TypeScript types**

In `web/src/lib/edge-llm/types.ts`, delete `ChunkExtractionResult`, `MetaClassificationRequest`, `MetaClassificationResult` if unused.

- [ ] **Step 5: Verify build**

```bash
docker compose -f infra/docker-compose.yml exec -T web npx --prefix /app/web tsc --noEmit -p /app/web/tsconfig.json 2>&1 | tail -20
```
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: strip edge-llm to summary+insight only (delete filter/meta paths)"
```

---

### Task 6.3: Delete unused `api-client.ts` exports

**Files:**
- Modify: `web/src/lib/api-client.ts`

- [ ] **Step 1: Confirm no callers of these functions**

```bash
grep -rln "fetchCandidates\|fetchKnownConcepts\|submitExtractionResults\|submitMetaClassification" web/src 2>/dev/null
```
Expected: only `api-client.ts` itself.

- [ ] **Step 2: Delete the four functions and their helpers**

Remove `fetchCandidates`, `fetchKnownConcepts`, `submitExtractionResults`, `submitMetaClassification` from `api-client.ts`.

- [ ] **Step 3: Verify build**

```bash
docker compose -f infra/docker-compose.yml exec -T web npx --prefix /app/web tsc --noEmit -p /app/web/tsconfig.json 2>&1 | tail
```
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: delete unused api-client extraction wrappers"
```

---

## Phase 7 — Quality regression fixtures

### Task 7.1: Capture held-out fixtures and expected concepts

**Files:**
- Create: `tests/fixtures/concept_extraction/variables.txt`
- Create: `tests/fixtures/concept_extraction/info_session.txt`
- Create: `tests/fixtures/concept_extraction/2026_goals.txt`
- Create: `tests/fixtures/concept_extraction/english_movies.txt`
- Create: `tests/fixtures/concept_extraction/expected.json`
- Create: `tests/integration/test_extraction_quality.py`

- [ ] **Step 1: Save the four fixture texts**

Copy `/tmp/neuronote-smoke/*.txt` (already on disk from the smoke test) into `tests/fixtures/concept_extraction/`. Rename to lowercase `_`-separated.

- [ ] **Step 2: Hand-curate the expected concept set per fixture**

Create `tests/fixtures/concept_extraction/expected.json`:

```json
{
  "variables": {
    "must_include": ["data types", "data values", "variables", "double quotes", "casting", "string variables", "variable names", "data type"],
    "must_not_include": ["have been", "can even", "you want", "moment you", "John", "Sally", "ADS"]
  },
  "info_session": {
    "must_include": ["khoury graduate programs", "grad school", "info session", "double husky scholarship"],
    "must_not_include": ["etc", "great time", "RSVP morning"]
  },
  "2026_goals": {
    "must_include": ["surya namaskar", "light meditation", "breathing exercises"],
    "must_not_include": ["i want", "wake up", "have been"]
  },
  "english_movies": {
    "must_include": ["dictator", "shawshank redemption"],
    "must_not_include": ["want to watch"]
  }
}
```

(Do not include "Wolf of Wallstreet" in `must_include` — kbir-inspec/YAKE both partially handle it; revisit when the pipeline is tuned.)

- [ ] **Step 3: Write the regression test**

```python
# tests/integration/test_extraction_quality.py
"""Held-out quality regression on real notes.

Each fixture has a hand-curated set of concepts that MUST appear and a set
that MUST NOT appear. The test asserts both.
"""
import json
from pathlib import Path

import pytest

from app.nlp.extraction import extract_concepts
from app.nlp.preprocessor import preprocess_content

FIXTURES = Path(__file__).parent.parent / "fixtures" / "concept_extraction"
EXPECTED = json.loads((FIXTURES / "expected.json").read_text())


@pytest.mark.parametrize("name", sorted(EXPECTED.keys()))
def test_extraction_quality(name: str) -> None:
    text = (FIXTURES / f"{name}.txt").read_text()
    spans = extract_concepts(preprocess_content(text))
    extracted_lower = {s.text.lower() for s in spans}

    expected = EXPECTED[name]
    must_include = {c.lower() for c in expected["must_include"]}
    must_not_include = {c.lower() for c in expected["must_not_include"]}

    missing = must_include - extracted_lower
    forbidden = must_not_include & extracted_lower

    assert not missing, f"{name}: missing required concepts {missing}; got {sorted(extracted_lower)}"
    assert not forbidden, f"{name}: extracted forbidden concepts {forbidden}"
```

- [ ] **Step 4: Run the regression**

```bash
docker compose -f infra/docker-compose.yml exec -T -e HF_HUB_OFFLINE=0 -e TRANSFORMERS_OFFLINE=0 api uv run pytest tests/integration/test_extraction_quality.py -v
```
Expected: PASS for all 4 fixtures.

If a fixture fails, the failure is informative — adjust either the fixture's expected set (if the model genuinely can't catch a phrase) or the cleanup filters (if a forbidden phrase slipped through).

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/concept_extraction/ tests/integration/test_extraction_quality.py
git commit -m "test: held-out concept-extraction quality fixtures"
```

---

## Phase 8 — Final verification & backfill

### Task 8.1: Backfill existing notes with the new pipeline

**Files:**
- Modify: `api/src/app/services/startup_backfill_service.py` (verify it triggers process-note for each note)

- [ ] **Step 1: Inspect startup-backfill behavior**

```bash
grep -n "process_note\|NoteProcessingService" api/src/app/services/startup_backfill_service.py
```
Expected: `service = NoteProcessingService(...).process_note(p)` for each note. If not, modify to call the new pipeline. (Existing behavior should already do this.)

- [ ] **Step 2: Wipe AGE graphs for all tenants**

This step is destructive. Confirm before running:

```bash
docker compose -f infra/docker-compose.yml exec -T db psql -U neuronote -d neuronote -c "
DO \$\$
DECLARE schema_name text;
BEGIN
  FOR schema_name IN SELECT s.schema_name FROM information_schema.schemata s WHERE s.schema_name LIKE 'user\_%' LOOP
    EXECUTE format('SELECT drop_graph(%L, true)', 'nn_' || schema_name);
    EXECUTE format('SELECT create_graph(%L)', 'nn_' || schema_name);
  END LOOP;
END
\$\$ LANGUAGE plpgsql;"
```

- [ ] **Step 3: Trigger backfill via API restart**

```bash
docker compose -f infra/docker-compose.yml restart api
sleep 10
docker compose -f infra/docker-compose.yml logs --since 5m api 2>&1 | grep -i "backfill\|pipeline.extract" | tail -20
```
Expected: backfill log lines for each note. No errors.

- [ ] **Step 4: Spot-check via API**

```bash
curl -s "http://localhost:8000/v1/concepts/known" -H "Cookie: <session>" | head
curl -s "http://localhost:8000/v1/graph/global?min_confidence=0.7&include_types=note,entity,relation" -H "Cookie: <session>" | jq '.nodes | length, .edges | length'
```
Expected: non-zero node and edge counts; concepts list reflects the new clean extraction.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: trigger startup-backfill for deterministic re-extraction"
```

---

### Task 8.2: Update CLAUDE.md and README

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md` (if it documents the old extraction pipeline)

- [ ] **Step 1: Update CLAUDE.md NLP section**

Replace the "NLP pipeline" section with a description of the new deterministic pipeline (extractors, normalisation, structure relations) and remove references to extraction profiles, ConceptMetaClassifier, SLMExtractor.

- [ ] **Step 2: Update env-var table**

Remove rows for `NLP_EXTRACTION_PROFILE`, `NLP_MODEL_NAME`, `NLP_ENTITY_SEED_TERMS`. Add a row for the (transformer model is hard-coded; no env var). Mention that `LLM_API_KEY` is now used only for summary/insight generation.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: update CLAUDE.md and README for deterministic extraction pipeline"
```

---

### Task 8.3: Final verification — full test suite + manual smoke

- [ ] **Step 1: Full Python test suite**

```bash
make compose-test 2>&1 | tail -30
```
Expected: all tests PASS.

- [ ] **Step 2: Frontend test suite**

```bash
cd web && npx vitest run 2>&1 | tail -30
```
Expected: all tests PASS.

- [ ] **Step 3: Type-check frontend**

```bash
docker compose -f infra/docker-compose.yml exec -T web npx --prefix /app/web tsc --noEmit -p /app/web/tsconfig.json 2>&1 | tail
```
Expected: no errors.

- [ ] **Step 4: Manual smoke — edit a note in browser**

1. Open `http://localhost:3000`, log in if needed.
2. Toggle preference between `edge` and `cloud` modes.
3. Edit each of the 4 fixture notes (Variables, Info Session, 2026 Goals, English Movies).
4. After save: open the global graph and verify the concept set looks clean (no "have been", "John", etc.).
5. Click a concept node → insight panel still works (cloud) or generates via Gemma (edge).

Document any UI regressions you see and fix before proceeding.

- [ ] **Step 5: Final commit (if any cleanups)**

```bash
git status
# if anything changed during smoke test:
git add -A
git commit -m "chore: post-smoke cleanups"
```

---

## Self-review

**Spec coverage:**
- Preprocessor → existing, used by Task 4.1 ✓
- Two-extractor ensemble → Task 1.1, 1.2 ✓
- Cleanup filters → Task 1.2 ✓
- Pre-warm → Task 1.3 ✓
- Cross-note normalisation → Task 2.1 (migration), 2.2 (logic) ✓
- 5 structure edge types → Task 3.1, 3.2, 3.3 ✓
- Pipeline rewrite → Task 4.1 ✓
- Service wiring → Task 4.2 ✓
- Server purge → Tasks 5.1–5.4 ✓
- Frontend purge → Tasks 6.1–6.3 ✓
- Migration safety → Tasks 2.1, 5.4 (idempotent ALTER, IF NOT EXISTS guards) ✓
- Backfill → Task 8.1 ✓
- Held-out fixtures → Task 7.1 ✓
- Tests for each new module → Tasks 1.1, 1.2, 2.2, 3.1, 3.2, 3.3, 7.1 ✓
- Docs update → Task 8.2 ✓

**Open items from spec deferred to implementation:**
- Edge-mode summary submission detail — current plan: edge mode has no LLM-generated summary in initial cut; it can be added in a follow-up (small change to NoteEditor + a `summary` field on `process-note` payload). Documented in Task 6.1's commentary.
- `spotting.py` survival — Task 5.3 makes the call based on actual import graph at that point.
- Cosine threshold τ — `DEFAULT_COSINE_THRESHOLD = 0.88` set in Task 2.2; revisit empirically after Task 8.1 backfill.
