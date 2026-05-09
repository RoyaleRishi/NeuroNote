# Deterministic Relations: Contract & Purge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the structural-relations regression where every note save emits 0 edges, by aligning the NLP pipeline with the existing `attrs.blockUid` storage contract; promote block-ID stamping into a shared utility; replace fragile substring concept matching with word-boundary matching; pin the contract with explicit Pydantic + TS types; and purge legacy LLM-era edges from the AGE graph.

**Architecture:** A single canonical helper (`app/utils/tiptap.py`) owns block-ID stamping, structural tree walking, and concept matching. The TipTap block-attrs contract is enumerated in `shared/contracts/`. `BlockRepository` and the NLP pipeline both consume the helper — they no longer carry their own copies. `derive_relations` reads `attrs.blockUid` only (no fallback) and returns both the edges and the concept-density metric used by a one-line health-warning log.

**Tech Stack:** Python 3.12 (uv), FastAPI, SQLAlchemy, pgvector, Apache AGE, Pydantic v2, pytest, TypeScript (frontend types only — no runtime change).

**Spec:** `docs/superpowers/specs/2026-05-09-deterministic-relations-contract-design.md`

---

## File map

**Files created:**
- `api/src/app/utils/tiptap.py` — `ensure_block_uids`, `walk_structural_blocks`, `find_concept_mentions`, `BlockInfo`, `STRUCTURAL_BLOCK_TYPES`, `extract_plain_text`
- `tests/unit/test_tiptap_utils.py`
- `shared/contracts/python/v1/document.py` — `TipTapBlockAttrs`, `STRUCTURAL_BLOCK_TYPES`
- `shared/contracts/ts/v1/document.ts` — `TipTapBlockAttrs` interface
- `tests/unit/test_document_contract.py`
- `tests/fixtures/notes/syntax_pseudonymised.json`
- `tests/fixtures/notes/goals_pseudonymised.json`
- `tests/integration/test_structure_relations_against_production_shape.py`
- `tests/unit/test_note_processing_service_relations_warning.py`
- `api/src/app/scripts/purge_legacy_relations.py`

**Files modified:**
- `api/src/app/db/repositories/block_repository.py` — import helpers from `app.utils.tiptap`; delete the local `_ensure_block_uid`, `_generate_unique_uid`, `_extract_plain_text`
- `api/src/app/nlp/structure_relations.py` — full rewrite around the shared util; return type changes to `RelationDerivation`
- `api/src/app/nlp/types.py` — add `RelationDerivation` dataclass; add `distinct_blocks_with_concepts: int = 0` to `NoteExtractionResult`
- `api/src/app/nlp/pipeline.py` — unpack `RelationDerivation`; thread the count into `NoteExtractionResult`
- `api/src/app/services/note_processing_service.py` — emit the `relation_count == 0` warning
- `tests/unit/test_structure_relations.py` — every fixture's `attrs.id` becomes `attrs.blockUid`; add the false-positive regression test
- `tests/unit/test_block_repository.py` — no behavioral change but uses the same imports as before (the helpers remain accessible via `block_repository`); kept passing as a smoke check

---

## Task 1: Add `ensure_block_uids` + `extract_plain_text` to `app/utils/tiptap.py`

**Files:**
- Create: `api/src/app/utils/tiptap.py`
- Test: `tests/unit/test_tiptap_utils.py`

These are extracted, not invented — `_ensure_block_uid` and `_extract_plain_text` already exist inside `api/src/app/db/repositories/block_repository.py:80-133`. We move them to a shared utility module, give them public names, and let the repository import them.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_tiptap_utils.py`:

```python
"""Unit tests for the shared TipTap utilities."""
from __future__ import annotations

import pytest

from app.utils.tiptap import (
    ensure_block_uids,
    extract_plain_text,
)


def test_ensure_block_uids_stamps_missing_uids() -> None:
    doc = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "hello"}]},
        ],
    }
    out = ensure_block_uids(doc)
    para = out["content"][0]
    assert isinstance(para["attrs"]["blockUid"], str)
    assert len(para["attrs"]["blockUid"]) > 0


def test_ensure_block_uids_preserves_existing() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "attrs": {"blockUid": "existing-uid"},
                "content": [{"type": "text", "text": "hello"}],
            },
        ],
    }
    out = ensure_block_uids(doc)
    assert out["content"][0]["attrs"]["blockUid"] == "existing-uid"


def test_ensure_block_uids_is_idempotent() -> None:
    doc = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "a"}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "b"}]},
        ],
    }
    once = ensure_block_uids(doc)
    twice = ensure_block_uids(once)
    assert once["content"][0]["attrs"]["blockUid"] == twice["content"][0]["attrs"]["blockUid"]
    assert once["content"][1]["attrs"]["blockUid"] == twice["content"][1]["attrs"]["blockUid"]


def test_ensure_block_uids_regenerates_collisions() -> None:
    doc = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "attrs": {"blockUid": "dup"},
             "content": [{"type": "text", "text": "a"}]},
            {"type": "paragraph", "attrs": {"blockUid": "dup"},
             "content": [{"type": "text", "text": "b"}]},
        ],
    }
    out = ensure_block_uids(doc)
    a, b = out["content"][0]["attrs"]["blockUid"], out["content"][1]["attrs"]["blockUid"]
    assert a == "dup" or b == "dup"  # one keeps the original
    assert a != b  # the other is regenerated


def test_extract_plain_text_concatenates_text_nodes() -> None:
    node = {
        "type": "paragraph",
        "content": [
            {"type": "text", "text": "Hello "},
            {"type": "text", "text": "world"},
        ],
    }
    assert extract_plain_text(node) == "Hello world"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose -f infra/docker-compose.yml exec -T api uv run --project api pytest tests/unit/test_tiptap_utils.py -v`
Expected: ImportError — `app.utils.tiptap` does not exist.

- [ ] **Step 3: Create `api/src/app/utils/tiptap.py`**

```python
"""Shared TipTap document utilities.

Single source of truth for block-ID stamping and plain-text extraction.
Owners: anything that produces a TipTap ``content_json`` (storage,
import, future paste handlers) calls ``ensure_block_uids`` before
persistence; anything that consumes one (NLP pipeline, exporters) reads
``attrs.blockUid`` and trusts it to be present.
"""
from __future__ import annotations

from uuid import uuid4


def _as_object(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return value
    return None


def _generate_unique_uid(used: set[str]) -> str:
    while True:
        candidate = uuid4().hex
        if candidate not in used:
            return candidate


def _ensure_block_uid(
    node: dict[str, object],
    *,
    used: set[str],
    latest_by_raw: dict[str, str],
) -> str:
    attrs = _as_object(node.get("attrs")) or {}
    existing = attrs.get("blockUid")
    if isinstance(existing, str) and existing.strip():
        raw = existing.strip()
    else:
        raw = _generate_unique_uid(used)
        attrs["blockUid"] = raw
        node["attrs"] = attrs

    if raw in used:
        replacement = _generate_unique_uid(used)
        attrs["blockUid"] = replacement
        node["attrs"] = attrs
        used.add(replacement)
        latest_by_raw[raw] = replacement
        return replacement

    used.add(raw)
    latest_by_raw[raw] = raw
    return raw


def ensure_block_uids(doc: dict[str, object]) -> dict[str, object]:
    """Stamp ``attrs.blockUid`` on every node that has an ``attrs`` slot.

    Idempotent: nodes that already have a non-empty string ``blockUid``
    are left alone. Colliding UIDs (two nodes sharing the same value)
    are resolved by regenerating one of them. Mutates ``doc`` in place
    and returns it for chaining.
    """
    used: set[str] = set()
    latest_by_raw: dict[str, str] = {}

    def walk(node: object) -> None:
        if not isinstance(node, dict):
            return
        if "attrs" in node or _as_object(node.get("attrs")) is not None or node.get("type") not in {None, "doc", "text"}:
            # Stamp on any structural node — doc root and text leaves are skipped.
            if node.get("type") not in {"doc", "text", None}:
                _ensure_block_uid(node, used=used, latest_by_raw=latest_by_raw)
        children = node.get("content")
        if isinstance(children, list):
            for child in children:
                walk(child)

    walk(doc)
    return doc


def extract_plain_text(node: object) -> str:
    """Recursively concatenate ``text`` nodes under ``node``."""
    if isinstance(node, dict):
        text_value = node.get("text")
        if isinstance(text_value, str):
            return text_value
        content = node.get("content")
        if isinstance(content, list):
            return "".join(extract_plain_text(child) for child in content)
        return ""
    if isinstance(node, list):
        return "".join(extract_plain_text(item) for item in node)
    return ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose -f infra/docker-compose.yml exec -T api uv run --project api pytest tests/unit/test_tiptap_utils.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add api/src/app/utils/tiptap.py tests/unit/test_tiptap_utils.py
git commit -m "$(cat <<'EOF'
feat(utils): add app.utils.tiptap with ensure_block_uids + extract_plain_text

Promotes the existing private _ensure_block_uid / _extract_plain_text
helpers from block_repository.py into a shared utility module. No call
sites yet — block_repository continues using its local copies until
Task 4 migrates it.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Add `walk_structural_blocks` + `find_concept_mentions` to `app/utils/tiptap.py`

**Files:**
- Modify: `api/src/app/utils/tiptap.py`
- Modify: `tests/unit/test_tiptap_utils.py`

These two helpers replace the three local walkers (`_walk_blocks`, `_list_item_groups`, `_bold_prefix_concepts`) and the substring matcher in `structure_relations.py`. They live alongside `ensure_block_uids` because they share the same tree-traversal vocabulary.

- [ ] **Step 1: Append the failing tests**

Append to `tests/unit/test_tiptap_utils.py`:

```python
import re

from app.utils.tiptap import (
    BlockInfo,
    STRUCTURAL_BLOCK_TYPES,
    find_concept_mentions,
    walk_structural_blocks,
)


def test_walk_structural_blocks_yields_block_info() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"blockUid": "h1", "level": 1},
                "content": [{"type": "text", "text": "Variables"}],
            },
            {
                "type": "paragraph",
                "attrs": {"blockUid": "p1"},
                "content": [{"type": "text", "text": "Variables hold values."}],
            },
        ],
    }
    blocks = list(walk_structural_blocks(doc))
    assert blocks == [
        BlockInfo(block_uid="h1", kind="heading", text="Variables", parent_uid=None, depth=0),
        BlockInfo(block_uid="p1", kind="paragraph", text="Variables hold values.", parent_uid=None, depth=0),
    ]


def test_walk_structural_blocks_records_list_parents() -> None:
    doc = {
        "type": "doc",
        "content": [{
            "type": "bulletList",
            "attrs": {"blockUid": "ul1"},
            "content": [
                {"type": "listItem", "attrs": {"blockUid": "li1"},
                 "content": [{"type": "paragraph", "attrs": {"blockUid": "p1"},
                              "content": [{"type": "text", "text": "apples"}]}]},
                {"type": "listItem", "attrs": {"blockUid": "li2"},
                 "content": [{"type": "paragraph", "attrs": {"blockUid": "p2"},
                              "content": [{"type": "text", "text": "oranges"}]}]},
            ],
        }],
    }
    blocks = list(walk_structural_blocks(doc))
    by_uid = {b.block_uid: b for b in blocks}
    assert by_uid["li1"].parent_uid == "ul1"
    assert by_uid["li2"].parent_uid == "ul1"
    assert by_uid["p1"].parent_uid == "li1"
    assert by_uid["p2"].parent_uid == "li2"


def test_walk_structural_blocks_skips_text_leaves() -> None:
    doc = {
        "type": "doc",
        "content": [{
            "type": "paragraph",
            "attrs": {"blockUid": "p1"},
            "content": [{"type": "text", "text": "ignored as a yielded block"}],
        }],
    }
    kinds = [b.kind for b in walk_structural_blocks(doc)]
    assert kinds == ["paragraph"]


def test_structural_block_types_includes_listitem() -> None:
    assert "listItem" in STRUCTURAL_BLOCK_TYPES
    assert "paragraph" in STRUCTURAL_BLOCK_TYPES
    assert "text" not in STRUCTURAL_BLOCK_TYPES


def test_find_concept_mentions_word_boundary() -> None:
    found = find_concept_mentions("AI is the future. Again, AI wins.", ["AI", "JS"])
    assert found == {"AI"}


def test_find_concept_mentions_does_not_match_substring() -> None:
    found = find_concept_mentions("Again I tried adjustments", ["AI", "JS"])
    assert found == set()


def test_find_concept_mentions_is_case_insensitive() -> None:
    found = find_concept_mentions("JavaScript is great", ["javascript"])
    assert found == {"javascript"}


def test_find_concept_mentions_handles_regex_special_chars() -> None:
    # Concepts containing regex metacharacters must not break the matcher.
    found = find_concept_mentions("we use C++ for performance", ["C++"])
    assert found == {"C++"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose -f infra/docker-compose.yml exec -T api uv run --project api pytest tests/unit/test_tiptap_utils.py -v`
Expected: ImportError on the new symbols.

- [ ] **Step 3: Append to `api/src/app/utils/tiptap.py`**

Add the following near the top (after imports), then the helpers below the existing exports:

```python
import re
from dataclasses import dataclass
from typing import Iterator, Literal


STRUCTURAL_BLOCK_TYPES: frozenset[str] = frozenset({
    "paragraph", "heading", "blockquote", "codeBlock", "horizontalRule",
    "bulletList", "orderedList", "listItem",
    "taskList", "taskItem", "mathBlock", "image", "blockRef",
})

BlockKind = Literal[
    "heading", "paragraph", "listItem", "bulletList", "orderedList",
    "codeBlock", "blockquote", "blockRef", "taskList", "taskItem",
    "mathBlock", "image", "horizontalRule", "other",
]


@dataclass(frozen=True, slots=True)
class BlockInfo:
    block_uid: str
    kind: BlockKind
    text: str
    parent_uid: str | None
    depth: int


def _kind_of(node: dict[str, object]) -> BlockKind:
    t = str(node.get("type") or "")
    if t in STRUCTURAL_BLOCK_TYPES:
        return t  # type: ignore[return-value]
    return "other"


def walk_structural_blocks(doc: dict[str, object]) -> Iterator[BlockInfo]:
    """Yield one ``BlockInfo`` per structural TipTap block.

    Walks the entire tree exactly once. ``parent_uid`` is the
    ``blockUid`` of the nearest enclosing structural ancestor (None at
    the document root). Leaves like ``text`` and ``hardBreak`` are not
    yielded.
    """

    def walk(
        nodes: list[object], parent_uid: str | None, depth: int
    ) -> Iterator[BlockInfo]:
        for raw in nodes:
            if not isinstance(raw, dict):
                continue
            kind = _kind_of(raw)
            block_uid = ""
            if kind != "other":
                attrs = _as_object(raw.get("attrs")) or {}
                value = attrs.get("blockUid")
                if isinstance(value, str):
                    block_uid = value
                yield BlockInfo(
                    block_uid=block_uid,
                    kind=kind,
                    text=extract_plain_text(raw).strip(),
                    parent_uid=parent_uid,
                    depth=depth,
                )
            children = raw.get("content")
            if isinstance(children, list):
                next_parent = block_uid if kind != "other" and block_uid else parent_uid
                yield from walk(children, next_parent, depth + 1 if kind != "other" else depth)

    root = doc.get("content")
    if isinstance(root, list):
        yield from walk(root, None, 0)


def find_concept_mentions(text: str, concepts: list[str]) -> set[str]:
    """Return the subset of ``concepts`` that appear in ``text`` as whole words.

    Case-insensitive. Each concept is escaped before being interpolated
    into a ``\\b<concept>\\b`` regex, so concepts containing metacharacters
    (e.g. ``C++``) do not break the matcher.
    """
    if not text or not concepts:
        return set()
    out: set[str] = set()
    for c in concepts:
        if not c:
            continue
        if re.search(rf"\b{re.escape(c)}\b", text, flags=re.IGNORECASE):
            out.add(c)
    return out
```

Note: `_as_object` and `extract_plain_text` are already defined from Task 1.

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose -f infra/docker-compose.yml exec -T api uv run --project api pytest tests/unit/test_tiptap_utils.py -v`
Expected: PASS (13 tests total; 5 from Task 1 + 8 new).

- [ ] **Step 5: Commit**

```bash
git add api/src/app/utils/tiptap.py tests/unit/test_tiptap_utils.py
git commit -m "$(cat <<'EOF'
feat(utils): add walk_structural_blocks + find_concept_mentions

Single tree walker that all NLP / export consumers will share, plus a
word-boundary regex concept matcher that replaces the substring
matching in structure_relations.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Add shared TipTap document contract (Python + TS)

**Files:**
- Create: `shared/contracts/python/v1/document.py`
- Create: `shared/contracts/ts/v1/document.ts`
- Test: `tests/unit/test_document_contract.py`

The contract pins block attributes that the backend actually consumes. The full document tree stays as `dict` — Pydantic'ing recursive TipTap is overkill.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_document_contract.py`:

```python
"""Tests for the shared TipTap block-attrs contract."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.contracts.python.v1.document import (
    STRUCTURAL_BLOCK_TYPES,
    TipTapBlockAttrs,
)


def test_tiptap_block_attrs_requires_block_uid() -> None:
    with pytest.raises(ValidationError):
        TipTapBlockAttrs()  # type: ignore[call-arg]


def test_tiptap_block_attrs_accepts_minimum_payload() -> None:
    attrs = TipTapBlockAttrs(blockUid="abc123")
    assert attrs.blockUid == "abc123"
    assert attrs.parentBlockUid is None
    assert attrs.indentLevel is None
    assert attrs.level is None


def test_tiptap_block_attrs_accepts_optional_fields() -> None:
    attrs = TipTapBlockAttrs(
        blockUid="abc",
        parentBlockUid="parent",
        indentLevel=2,
        level=3,
    )
    assert attrs.parentBlockUid == "parent"
    assert attrs.indentLevel == 2
    assert attrs.level == 3


def test_structural_block_types_matches_util_constant() -> None:
    """Contract and util share the same set; drift would fail this test."""
    from app.utils.tiptap import STRUCTURAL_BLOCK_TYPES as UTIL_TYPES
    assert STRUCTURAL_BLOCK_TYPES == UTIL_TYPES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose -f infra/docker-compose.yml exec -T api uv run --project api pytest tests/unit/test_document_contract.py -v`
Expected: ImportError — `shared.contracts.python.v1.document` does not exist.

- [ ] **Step 3: Create the Python contract**

Create `shared/contracts/python/v1/document.py`:

```python
"""TipTap document block-attrs contract (v1).

Backend consumers (NLP pipeline, exporters) and producers
(BlockRepository, future imports) agree on this shape. Mirror in
``shared/contracts/ts/v1/document.ts`` whenever this changes.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

# Re-exported from app.utils.tiptap to keep one source of truth.
# (The contract module is the *interface*; the util module is the
# *implementation*. We intentionally couple them.)
from app.utils.tiptap import STRUCTURAL_BLOCK_TYPES  # noqa: F401  (re-exported)


class TipTapBlockAttrs(BaseModel):
    """Attributes carried by every structural TipTap block."""

    blockUid: str = Field(..., min_length=1)
    parentBlockUid: str | None = None
    indentLevel: int | None = None
    level: int | None = None  # heading-only

    model_config = {"extra": "allow"}  # tolerate fields the backend doesn't read
```

- [ ] **Step 4: Create the TS mirror**

Create `shared/contracts/ts/v1/document.ts`:

```typescript
/**
 * TipTap document block-attrs contract (v1).
 *
 * Mirror of shared/contracts/python/v1/document.py. Both files must
 * stay in sync — change one, change the other in the same commit.
 */

export interface TipTapBlockAttrs {
  blockUid: string;
  parentBlockUid?: string | null;
  indentLevel?: number | null;
  level?: number | null;
  // Tolerates additional editor-only fields.
  [extra: string]: unknown;
}

export const STRUCTURAL_BLOCK_TYPES: readonly string[] = [
  "paragraph",
  "heading",
  "blockquote",
  "codeBlock",
  "horizontalRule",
  "bulletList",
  "orderedList",
  "listItem",
  "taskList",
  "taskItem",
  "mathBlock",
  "image",
  "blockRef",
] as const;
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose -f infra/docker-compose.yml exec -T api uv run --project api pytest tests/unit/test_document_contract.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add shared/contracts/python/v1/document.py shared/contracts/ts/v1/document.ts tests/unit/test_document_contract.py
git commit -m "$(cat <<'EOF'
feat(contracts): add TipTapBlockAttrs (Python + TS) for v1 contract

Pins blockUid as required on every structural block. Re-exports
STRUCTURAL_BLOCK_TYPES from app.utils.tiptap so contract drift is
caught by test_structural_block_types_matches_util_constant.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Migrate `block_repository.py` to use `app.utils.tiptap`

**Files:**
- Modify: `api/src/app/db/repositories/block_repository.py`

Delete the local copies of `_ensure_block_uid`, `_generate_unique_uid`, `_extract_plain_text`, `_as_object`. Import them from `app.utils.tiptap`. Behavior unchanged — the existing `tests/unit/test_block_repository.py` is the regression test.

- [ ] **Step 1: Run the existing block_repository tests as a baseline**

Run: `docker compose -f infra/docker-compose.yml exec -T api uv run --project api pytest tests/unit/test_block_repository.py -v`
Expected: PASS (record the count).

- [ ] **Step 2: Refactor `block_repository.py`**

Replace the top of the file (lines 1–134, through the existing `_ensure_block_uid` function) with:

```python
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import re
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models.block import Block
from app.db.models.note import Note
from app.utils.tiptap import (
    _as_object,
    _ensure_block_uid,
    extract_plain_text as _extract_plain_text,
)

_BLOCK_REF_PATTERN = re.compile(r"\(\(([A-Za-z0-9_-]{6,128})\)\)")
_BLOCK_REF_HREF_PATTERN = re.compile(r"#block(?:=|-)([A-Za-z0-9_-]{6,128})")
_BLOCK_NODE_TYPES = {
    "paragraph",
    "heading",
    "blockquote",
    "codeBlock",
    "horizontalRule",
    "bulletList",
    "orderedList",
    "taskList",
    "taskItem",
    "listItem",
    "mathBlock",
    "image",
}
_CHILD_CONTAINER_TYPES = {
    "bulletList",
    "orderedList",
    "taskList",
    "taskItem",
    "listItem",
    "blockquote",
}


@dataclass(frozen=True, slots=True)
class BlockRecord:
    block_uid: str
    note_id: str
    parent_block_uid: str | None
    sibling_order: int
    block_index: int
    content_text: str
    rich_content: dict[str, object]


@dataclass(frozen=True, slots=True)
class BlockSearchRecord:
    block_uid: str
    note_id: str
    note_title: str
    content_text: str


@dataclass(frozen=True, slots=True)
class BlockBacklinkRecord:
    source_block_uid: str
    source_note_id: str
    source_note_title: str
    snippet: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class _ExtractionRow:
    block_uid: str
    parent_block_uid: str | None
    sibling_order: int
    block_index: int
    content_text: str
    content_hash: str
    rich_content: dict[str, object]
```

Then update the call site at the original line 253. The `_walk_nodes` helper currently calls:

```python
block_uid = _ensure_block_uid(
    node,
    used_uids=used_uids,
    latest_uid_by_raw=latest_uid_by_raw,
)
```

Change the keyword args to match `app.utils.tiptap._ensure_block_uid`:

```python
block_uid = _ensure_block_uid(
    node,
    used=used_uids,
    latest_by_raw=latest_uid_by_raw,
)
```

(All four parameter renames: `used_uids` → `used`, `latest_uid_by_raw` → `latest_by_raw`. Done at the call site only; the imported helper uses the new names.)

- [ ] **Step 3: Run block_repository tests**

Run: `docker compose -f infra/docker-compose.yml exec -T api uv run --project api pytest tests/unit/test_block_repository.py -v`
Expected: PASS (same count as Step 1).

- [ ] **Step 4: Run the full unit suite**

Run: `docker compose -f infra/docker-compose.yml exec -T api uv run --project api pytest tests/unit -v`
Expected: PASS (no regressions).

- [ ] **Step 5: Commit**

```bash
git add api/src/app/db/repositories/block_repository.py
git commit -m "$(cat <<'EOF'
refactor(block_repository): import block-uid helpers from app.utils.tiptap

Single source of truth. No behavior change — the existing
test_block_repository suite is the regression check.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Add `RelationDerivation` return type and `distinct_blocks_with_concepts` to `NoteExtractionResult`

**Files:**
- Modify: `api/src/app/nlp/types.py`

This sets up the data model the structure-relations rewrite (Task 6) and the health-metric warning (Task 8) need. No tests yet — `types.py` is a dataclass module with no behavior.

- [ ] **Step 1: Modify `types.py`**

In `api/src/app/nlp/types.py`, add the new dataclass next to the existing `ExtractedRelation`:

```python
@dataclass(frozen=True, slots=True)
class StructureEdge:
    source: str
    target: str
    relation: str  # one of MENTIONED_TOGETHER | SUBTOPIC_OF | SIBLING_OF | REFERENCES | DEFINED_BY


@dataclass(frozen=True, slots=True)
class RelationDerivation:
    edges: list[StructureEdge]
    distinct_blocks_with_concepts: int
```

And add the field to `NoteExtractionResult`:

```python
@dataclass(slots=True)
class NoteExtractionResult:
    note_id: str
    content_hash: str
    entities: list[ExtractedEntity]
    keyphrases: list[ExtractedKeyphrase]
    relations: list[ExtractedRelation]
    embedding: list[float] | None
    entity_mentions: list[ExtractedEntityMention] = field(default_factory=list)
    summary: str = ""
    distinct_blocks_with_concepts: int = 0  # new field; default keeps existing callers happy

    def with_note_id(self, note_id: str) -> "NoteExtractionResult":
        return dataclasses.replace(self, note_id=note_id)
```

- [ ] **Step 2: Run unit suite as a smoke check**

Run: `docker compose -f infra/docker-compose.yml exec -T api uv run --project api pytest tests/unit -v`
Expected: PASS — every existing caller of `NoteExtractionResult` still works because the new field has a default.

- [ ] **Step 3: Commit**

```bash
git add api/src/app/nlp/types.py
git commit -m "$(cat <<'EOF'
feat(nlp/types): add RelationDerivation and distinct_blocks_with_concepts

Sets up the data model for the structure_relations rewrite. The new
NoteExtractionResult field defaults to 0 so existing callers continue
to compile.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Rewrite `structure_relations.py` and its tests

**Files:**
- Modify (rewrite): `api/src/app/nlp/structure_relations.py`
- Modify (rewrite): `tests/unit/test_structure_relations.py`

This is the core fix. The module shrinks from ~213 lines to ~140, drops `attrs.id` entirely, drops the missing-ID gate, walks the tree once via `walk_structural_blocks`, matches concepts via `find_concept_mentions`, and returns `RelationDerivation`.

- [ ] **Step 1: Rewrite the test file**

Replace `tests/unit/test_structure_relations.py` entirely with:

```python
"""Unit tests for derive_relations.

Fixtures use ``attrs.blockUid`` to match the storage contract — the
attribute the production stamper writes and the consumer now reads.
"""
from __future__ import annotations

from app.nlp.structure_relations import derive_relations
from app.nlp.types import RelationDerivation, StructureEdge


def _edges(result: RelationDerivation) -> list[StructureEdge]:
    return result.edges


def test_concepts_in_same_paragraph_emit_mentioned_together() -> None:
    doc = {
        "type": "doc",
        "content": [{
            "type": "paragraph",
            "attrs": {"blockUid": "p1"},
            "content": [{"type": "text", "text": "Variables hold data values."}],
        }],
    }
    result = derive_relations(doc, concepts=["variables", "data values"])
    assert StructureEdge("variables", "data values", "MENTIONED_TOGETHER") in _edges(result)
    assert StructureEdge("data values", "variables", "MENTIONED_TOGETHER") in _edges(result)


def test_concept_under_heading_emits_subtopic_of() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"blockUid": "h1", "level": 2},
                "content": [{"type": "text", "text": "Casting"}],
            },
            {
                "type": "paragraph",
                "attrs": {"blockUid": "p1"},
                "content": [{"type": "text", "text": "Use the int function."}],
            },
        ],
    }
    result = derive_relations(doc, concepts=["casting", "int function"])
    assert StructureEdge("int function", "casting", "SUBTOPIC_OF") in _edges(result)


def test_sibling_list_items_emit_sibling_of() -> None:
    doc = {
        "type": "doc",
        "content": [{
            "type": "bulletList",
            "attrs": {"blockUid": "ul1"},
            "content": [
                {"type": "listItem", "attrs": {"blockUid": "li1"},
                 "content": [{"type": "paragraph", "attrs": {"blockUid": "p1"},
                              "content": [{"type": "text", "text": "apples"}]}]},
                {"type": "listItem", "attrs": {"blockUid": "li2"},
                 "content": [{"type": "paragraph", "attrs": {"blockUid": "p2"},
                              "content": [{"type": "text", "text": "oranges"}]}]},
            ],
        }],
    }
    result = derive_relations(doc, concepts=["apples", "oranges"])
    assert StructureEdge("apples", "oranges", "SIBLING_OF") in _edges(result)
    assert StructureEdge("oranges", "apples", "SIBLING_OF") in _edges(result)


def test_blockref_emits_references() -> None:
    doc = {
        "type": "doc",
        "content": [{
            "type": "paragraph",
            "attrs": {"blockUid": "p1"},
            "content": [
                {"type": "text", "text": "See "},
                {"type": "blockRef", "attrs": {"blockUid": "br1", "refTargetText": "data types"},
                 "content": []},
                {"type": "text", "text": " also casting"},
            ],
        }],
    }
    result = derive_relations(doc, concepts=["casting", "data types"])
    assert StructureEdge("casting", "data types", "REFERENCES") in _edges(result)


def test_bold_prefix_emits_defined_by() -> None:
    doc = {
        "type": "doc",
        "content": [{
            "type": "paragraph",
            "attrs": {"blockUid": "p1"},
            "content": [
                {"type": "text", "marks": [{"type": "bold"}], "text": "Casting"},
                {"type": "text", "text": " is the process of converting types."},
            ],
        }],
    }
    result = derive_relations(doc, concepts=["casting"])
    assert any(e.relation == "DEFINED_BY" and e.source == "casting" for e in _edges(result))


def test_substring_match_does_not_produce_false_positives() -> None:
    """Pre-fix this would emit MENTIONED_TOGETHER from substring matches."""
    doc = {
        "type": "doc",
        "content": [{
            "type": "paragraph",
            "attrs": {"blockUid": "p1"},
            "content": [{"type": "text", "text": "Again I tried adjustments"}],
        }],
    }
    result = derive_relations(doc, concepts=["AI", "JS"])
    assert _edges(result) == []


def test_distinct_blocks_with_concepts_counts_unique_blocks() -> None:
    doc = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "attrs": {"blockUid": "p1"},
             "content": [{"type": "text", "text": "casting and variables"}]},
            {"type": "paragraph", "attrs": {"blockUid": "p2"},
             "content": [{"type": "text", "text": "more on variables"}]},
            {"type": "paragraph", "attrs": {"blockUid": "p3"},
             "content": [{"type": "text", "text": "no concept here"}]},
        ],
    }
    result = derive_relations(doc, concepts=["casting", "variables"])
    assert result.distinct_blocks_with_concepts == 2
```

- [ ] **Step 2: Run the rewritten tests to verify they fail**

Run: `docker compose -f infra/docker-compose.yml exec -T api uv run --project api pytest tests/unit/test_structure_relations.py -v`
Expected: many failures — the old `derive_relations` returns a `list`, the imports `RelationDerivation`/`StructureEdge` from `app.nlp.types` don't yet exist there (we created `StructureEdge` in `types.py` Task 5; the old `StructureEdge` lives in `structure_relations.py`).

- [ ] **Step 3: Rewrite `structure_relations.py`**

Replace `api/src/app/nlp/structure_relations.py` entirely with:

```python
"""Derive typed relations from TipTap document structure.

Reads ``attrs.blockUid`` (guaranteed present after
``app.utils.tiptap.ensure_block_uids`` has run on the document at the
storage boundary). Walks the tree exactly once via
``walk_structural_blocks``. Matches concepts with word-boundary regex
via ``find_concept_mentions``.

Relation types:
  - MENTIONED_TOGETHER: both concepts present in the same block
  - SUBTOPIC_OF: concept in a non-heading block following a heading
    that names another concept
  - SIBLING_OF: concepts in adjacent list items under the same parent
  - REFERENCES: concept in a block that contains a blockRef pointing at
    another concept
  - DEFINED_BY: concept appears as a bold span at the start of a
    paragraph (target="" sentinel — concept→note, not concept→concept)
"""
from __future__ import annotations

from typing import Iterator

from app.nlp.types import RelationDerivation, StructureEdge
from app.utils.tiptap import (
    BlockInfo,
    extract_plain_text,
    find_concept_mentions,
    walk_structural_blocks,
)


def _list_item_groups(
    doc: dict[str, object], parent_uid: str | None = None
) -> Iterator[list[BlockInfo]]:
    """Yield groups of sibling listItem BlockInfo objects."""
    content = doc.get("content")
    if not isinstance(content, list):
        return
    for node in content:
        if not isinstance(node, dict):
            continue
        if node.get("type") in {"bulletList", "orderedList", "taskList"}:
            group: list[BlockInfo] = []
            list_attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
            list_uid = (list_attrs or {}).get("blockUid") if isinstance(list_attrs, dict) else None
            for item in node.get("content", []) or []:
                if not isinstance(item, dict):
                    continue
                item_attrs = item.get("attrs") if isinstance(item.get("attrs"), dict) else {}
                item_uid = (item_attrs or {}).get("blockUid") if isinstance(item_attrs, dict) else ""
                if not isinstance(item_uid, str):
                    item_uid = ""
                group.append(BlockInfo(
                    block_uid=item_uid,
                    kind="listItem",
                    text=extract_plain_text(item).strip(),
                    parent_uid=list_uid if isinstance(list_uid, str) else None,
                    depth=1,
                ))
            if group:
                yield group
        # Recurse into other containers for nested lists.
        sub = node.get("content")
        if isinstance(sub, list):
            yield from _list_item_groups(node)


def _blockref_targets(doc: dict[str, object]) -> Iterator[tuple[str, str]]:
    """Yield (source_block_text, refTargetText) for every blockRef."""
    content = doc.get("content")
    if not isinstance(content, list):
        return
    for node in content:
        if not isinstance(node, dict):
            continue
        node_text = extract_plain_text(node)
        for sub in node.get("content", []) or []:
            if isinstance(sub, dict) and sub.get("type") == "blockRef":
                attrs = sub.get("attrs") if isinstance(sub.get("attrs"), dict) else {}
                target = (attrs or {}).get("refTargetText", "")
                if isinstance(target, str) and target:
                    yield (node_text, target)
        if node.get("content"):
            yield from _blockref_targets(node)


def _bold_prefix_concepts(
    doc: dict[str, object], concepts: list[str]
) -> set[str]:
    """Concepts that appear as a bold span at the start of a paragraph."""
    out: set[str] = set()
    content = doc.get("content")
    if not isinstance(content, list):
        return out
    for node in content:
        if not isinstance(node, dict):
            continue
        if node.get("type") != "paragraph":
            sub = node.get("content")
            if isinstance(sub, list):
                out |= _bold_prefix_concepts(node, concepts)
            continue
        children = node.get("content") or []
        if not children:
            continue
        first = children[0]
        if not isinstance(first, dict) or first.get("type") != "text":
            continue
        marks = first.get("marks") or []
        if not any(isinstance(m, dict) and m.get("type") == "bold" for m in marks):
            continue
        bold_text = str(first.get("text", "")).strip().lower()
        for c in concepts:
            if c.lower() == bold_text:
                out.add(c)
    return out


def derive_relations(
    document_json: dict[str, object], *, concepts: list[str]
) -> RelationDerivation:
    """Walk TipTap blocks and emit typed structure edges between concepts.

    Returns a ``RelationDerivation`` carrying the edges plus the count
    of distinct structural blocks where ≥1 concept was matched
    (used by the health metric).
    """
    if not concepts:
        return RelationDerivation(edges=[], distinct_blocks_with_concepts=0)

    edges: set[StructureEdge] = set()
    distinct_blocks_with_concepts = 0
    current_heading_concepts: set[str] = set()

    for block in walk_structural_blocks(document_json):
        present = find_concept_mentions(block.text, concepts)
        if present:
            distinct_blocks_with_concepts += 1

        listed = sorted(present)
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
            a_concepts = find_concept_mentions(a_block.text, concepts)
            for b_block in group[i + 1:]:
                b_concepts = find_concept_mentions(b_block.text, concepts)
                for a in a_concepts:
                    for b in b_concepts:
                        if a != b:
                            edges.add(StructureEdge(a, b, "SIBLING_OF"))
                            edges.add(StructureEdge(b, a, "SIBLING_OF"))

    # REFERENCES: concept in a block that contains a blockRef.
    for source_text, target_text in _blockref_targets(document_json):
        source_concepts = find_concept_mentions(source_text, concepts)
        target_concepts = find_concept_mentions(target_text, concepts)
        for s in source_concepts:
            for t in target_concepts:
                if s != t:
                    edges.add(StructureEdge(s, t, "REFERENCES"))

    # DEFINED_BY: concept appears as a bold span at start of a paragraph.
    for c in _bold_prefix_concepts(document_json, concepts):
        edges.add(StructureEdge(c, "", "DEFINED_BY"))

    sorted_edges = sorted(edges, key=lambda e: (e.relation, e.source, e.target))
    return RelationDerivation(
        edges=sorted_edges,
        distinct_blocks_with_concepts=distinct_blocks_with_concepts,
    )
```

- [ ] **Step 4: Run the rewritten tests**

Run: `docker compose -f infra/docker-compose.yml exec -T api uv run --project api pytest tests/unit/test_structure_relations.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Run the unit suite to catch downstream breakage**

Run: `docker compose -f infra/docker-compose.yml exec -T api uv run --project api pytest tests/unit -v`
Expected: failures in tests that import `StructureEdge` or `BlockInfo` from `app.nlp.structure_relations`. Find them with:

```bash
docker compose -f infra/docker-compose.yml exec -T api grep -rn "from app.nlp.structure_relations import" tests api/src
```

Update each importer to use `app.nlp.types.StructureEdge` (and `app.utils.tiptap.BlockInfo` if needed). Re-run the unit suite until green.

- [ ] **Step 6: Commit**

```bash
git add api/src/app/nlp/structure_relations.py tests/unit/test_structure_relations.py
git commit -m "$(cat <<'EOF'
feat(nlp): rewrite structure_relations around shared TipTap util

- Reads attrs.blockUid (no attrs.id fallback)
- Drops the missing-ID gate (contract guarantees blockUid is present)
- Single tree walk via walk_structural_blocks
- Word-boundary concept matching via find_concept_mentions
- Returns RelationDerivation carrying both edges and the
  distinct_blocks_with_concepts metric for the health log

Closes the structural-relations regression introduced in the
deterministic-extraction refactor.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Update `pipeline.py` to consume `RelationDerivation`

**Files:**
- Modify: `api/src/app/nlp/pipeline.py`

The pipeline previously did `struct_edges = derive_relations(...)` and iterated `struct_edges` directly. After Task 6 it returns a `RelationDerivation`. Update both the iteration and thread the count into `NoteExtractionResult`.

- [ ] **Step 1: Edit `pipeline.py`**

In `api/src/app/nlp/pipeline.py`, find the block (currently lines 94–107):

```python
struct_edges = derive_relations(document_json, concepts=canonicals)
relations: list[ExtractedRelation] = []
for edge in struct_edges:
    if edge.relation == "DEFINED_BY":
        # DEFINED_BY links concept → note; graph sync handles it separately.
        continue
    relations.append(ExtractedRelation(
        ...
    ))
```

Replace with:

```python
derivation = derive_relations(document_json, concepts=canonicals)
relations: list[ExtractedRelation] = []
for edge in derivation.edges:
    if edge.relation == "DEFINED_BY":
        # DEFINED_BY links concept → note; graph sync handles it separately.
        continue
    relations.append(ExtractedRelation(
        subject_id=f"concept-{_slugify(edge.source)}",
        subject_text=edge.source,
        predicate=edge.relation,
        object_id=f"concept-{_slugify(edge.target)}",
        object_text=edge.target,
        confidence=0.7 if edge.relation == "MENTIONED_TOGETHER" else 1.0,
    ))
```

Then in the `NoteExtractionResult(...)` construction (currently lines 125–134), add the new field:

```python
result = NoteExtractionResult(
    note_id=note_id,
    content_hash=content_hash,
    entities=entities,
    keyphrases=[],
    relations=relations,
    embedding=embedding,
    entity_mentions=[],
    summary="",
    distinct_blocks_with_concepts=derivation.distinct_blocks_with_concepts,
)
```

- [ ] **Step 2: Run the unit suite**

Run: `docker compose -f infra/docker-compose.yml exec -T api uv run --project api pytest tests/unit -v`
Expected: PASS.

- [ ] **Step 3: Run integration tests**

Run: `docker compose -f infra/docker-compose.yml exec -T api uv run --project api pytest tests/integration -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add api/src/app/nlp/pipeline.py
git commit -m "$(cat <<'EOF'
refactor(nlp/pipeline): consume RelationDerivation; thread block count

Threads distinct_blocks_with_concepts through NoteExtractionResult so
the upcoming health-metric warning can surface silent regressions.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Add the `relation_count == 0` health-metric warning

**Files:**
- Modify: `api/src/app/services/note_processing_service.py`
- Test: `tests/unit/test_note_processing_service_relations_warning.py`

A single log line that fires when extraction looks suspicious. No alerting.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_note_processing_service_relations_warning.py`:

```python
"""Health-metric: warn when relations=0 despite enough concepts/blocks."""
from __future__ import annotations

import logging

import pytest

from app.nlp.types import (
    ExtractedEntity,
    ExtractedRelation,
    NoteExtractionResult,
)
from app.services.note_processing_service import _maybe_log_zero_relations_warning


def _make_result(*, entities: int, relations: int, blocks: int) -> NoteExtractionResult:
    return NoteExtractionResult(
        note_id="note-1",
        content_hash="h1",
        entities=[
            ExtractedEntity(entity_id=f"c-{i}", text=f"c{i}", label="concept", confidence=0.9)
            for i in range(entities)
        ],
        keyphrases=[],
        relations=[
            ExtractedRelation(
                subject_id="c-0", subject_text="c0",
                predicate="MENTIONED_TOGETHER",
                object_id="c-1", object_text="c1",
                confidence=0.7,
            )
            for _ in range(relations)
        ],
        embedding=None,
        distinct_blocks_with_concepts=blocks,
    )


def test_warning_fires_when_zero_relations_with_enough_signal(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="app.services.note_processing_service")
    result = _make_result(entities=4, relations=0, blocks=3)
    _maybe_log_zero_relations_warning(result)
    assert any(
        "relation_count=0" in rec.message and "note-1" in rec.message
        for rec in caplog.records
    )


def test_warning_does_not_fire_when_legitimately_sparse(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="app.services.note_processing_service")
    result = _make_result(entities=1, relations=0, blocks=1)
    _maybe_log_zero_relations_warning(result)
    assert not [r for r in caplog.records if "relation_count=0" in r.message]


def test_warning_does_not_fire_when_relations_present(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="app.services.note_processing_service")
    result = _make_result(entities=4, relations=2, blocks=3)
    _maybe_log_zero_relations_warning(result)
    assert not [r for r in caplog.records if "relation_count=0" in r.message]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose -f infra/docker-compose.yml exec -T api uv run --project api pytest tests/unit/test_note_processing_service_relations_warning.py -v`
Expected: ImportError on `_maybe_log_zero_relations_warning`.

- [ ] **Step 3: Add the helper to `note_processing_service.py`**

In `api/src/app/services/note_processing_service.py`, near the top (after imports, before the class), add:

```python
def _maybe_log_zero_relations_warning(result: "NoteExtractionResult") -> None:
    """Emit a warning when relation extraction looks suspiciously empty.

    Heuristic: warn when the note has ≥3 concepts spread across ≥3
    distinct structural blocks (so the algorithm had something to chew
    on) yet emitted zero concept→concept relations. Catches regressions
    of the same shape as the deterministic-refactor blockUid contract
    drift.
    """
    relation_count = len(result.relations)
    entity_count = len(result.entities)
    blocks = result.distinct_blocks_with_concepts
    if relation_count == 0 and entity_count >= 3 and blocks >= 3:
        _LOGGER.warning(
            "Suspicious extraction: note_id=%s relation_count=0 entity_count=%d "
            "distinct_blocks_with_concepts=%d",
            result.note_id, entity_count, blocks,
        )
```

Make sure `from app.nlp.types import NoteExtractionResult` is imported at the top of the file (or `from app.nlp.types import ...` already exists — add `NoteExtractionResult` to it). Also add `_LOGGER = logging.getLogger(__name__)` if absent (check the file's existing logger; reuse it).

Then call the helper inside `process_note` after the pipeline runs and before returning the summary. Find the place where the pipeline returns its result (around `_persist_graph_and_vector` or wherever `NoteExtractionResult` is in scope) and call:

```python
_maybe_log_zero_relations_warning(extraction_result)
```

If the extraction result isn't currently kept in scope at the call site, thread it from `_persist_graph_and_vector` back to `process_note` (return it instead of `ExtractionSummary`, then build the summary and call the helper at the top level).

- [ ] **Step 4: Run the test**

Run: `docker compose -f infra/docker-compose.yml exec -T api uv run --project api pytest tests/unit/test_note_processing_service_relations_warning.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full suite**

Run: `docker compose -f infra/docker-compose.yml exec -T api uv run --project api pytest tests -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/src/app/services/note_processing_service.py tests/unit/test_note_processing_service_relations_warning.py
git commit -m "$(cat <<'EOF'
feat(processing): warn when extraction emits 0 relations despite signal

Single log line that surfaces silent regressions of the structural-
relations bug class. Heuristic: ≥3 concepts × ≥3 blocks × 0 relations.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Add production-shape fixture + integration test

**Files:**
- Create: `tests/fixtures/notes/syntax_pseudonymised.json`
- Create: `tests/fixtures/notes/goals_pseudonymised.json`
- Create: `tests/integration/test_structure_relations_against_production_shape.py`

This is the keystone test. It runs `derive_relations` against real document shape (block UIDs, real nesting) so future contract drifts can't pass tests.

- [ ] **Step 1: Export the two production notes as fixtures**

Run:

```bash
mkdir -p tests/fixtures/notes
docker compose -f infra/docker-compose.yml exec -T db psql -U neuronote -d neuronote -tAc \
  "SELECT content_json::text FROM user_b6b6ef061c81.notes WHERE note_id='note-1777849708116-379';" \
  > /tmp/syntax.json
docker compose -f infra/docker-compose.yml exec -T db psql -U neuronote -d neuronote -tAc \
  "SELECT content_json::text FROM user_b6b6ef061c81.notes WHERE note_id='note-1777988937929-19';" \
  > /tmp/goals.json
```

- [ ] **Step 2: Pseudonymise**

Pseudonymisation: replace text content (every `text` leaf node's `text` field) with a deterministic hash-derived placeholder while preserving structure and `blockUid`s. The cleanest approach is a one-shot Python script — write it inline:

```bash
docker compose -f infra/docker-compose.yml exec -T api python3 -c "
import json, hashlib, sys
def pseudonymise(node):
    if isinstance(node, dict):
        if node.get('type') == 'text' and isinstance(node.get('text'), str):
            t = node['text']
            if t.strip():
                h = hashlib.sha256(t.encode('utf-8')).hexdigest()[:8]
                node['text'] = f'concept_{h}_{len(t)}c'
        for v in node.values():
            pseudonymise(v)
    elif isinstance(node, list):
        for item in node:
            pseudonymise(item)

for src, dst in [('/tmp/syntax.json','/tmp/syntax_pseudo.json'),
                 ('/tmp/goals.json','/tmp/goals_pseudo.json')]:
    with open(src) as f:
        d = json.load(f)
    pseudonymise(d)
    with open(dst, 'w') as f:
        json.dump(d, f, indent=2)
print('done')
"
docker compose -f infra/docker-compose.yml cp api:/tmp/syntax_pseudo.json tests/fixtures/notes/syntax_pseudonymised.json
docker compose -f infra/docker-compose.yml cp api:/tmp/goals_pseudo.json tests/fixtures/notes/goals_pseudonymised.json
```

(After this command, **manually inspect** the two fixture files. If any non-text fields contain personal info — heading attrs are fine, but check `refTargetText` etc. — pseudonymise those too before committing.)

- [ ] **Step 3: Write the integration test**

Create `tests/integration/test_structure_relations_against_production_shape.py`:

```python
"""Integration test: derive_relations against real production document shape.

These fixtures were pseudonymised from real notes in the running
database. Their *structure* (block UIDs, nesting, list / heading
arrangement) matches what the frontend produces; their *content* has
been replaced with deterministic placeholders.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.nlp.structure_relations import derive_relations
from app.utils.tiptap import walk_structural_blocks

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "notes"


def _load(name: str) -> dict:
    with (FIXTURES / name).open() as f:
        return json.load(f)


def _all_concepts(doc: dict) -> list[str]:
    """Collect every distinct text token (>=4 chars) appearing in the doc.

    This mimics what the real concept extractor produces — a list of
    surface forms — without invoking the kbir model in the integration
    test.
    """
    seen: set[str] = set()
    for block in walk_structural_blocks(doc):
        for token in block.text.split():
            token = token.strip(",.;:()[]{}!?")
            if len(token) >= 4:
                seen.add(token)
    return sorted(seen)


@pytest.mark.parametrize("fixture", [
    "syntax_pseudonymised.json",
    "goals_pseudonymised.json",
])
def test_walk_structural_blocks_yields_block_uids(fixture: str) -> None:
    doc = _load(fixture)
    blocks = list(walk_structural_blocks(doc))
    assert blocks, f"{fixture} produced zero structural blocks"
    missing_uid = [b for b in blocks if not b.block_uid]
    assert not missing_uid, (
        f"{fixture} has {len(missing_uid)} blocks without blockUid — "
        "ensure_block_uids contract violated upstream"
    )


@pytest.mark.parametrize("fixture", [
    "syntax_pseudonymised.json",
    "goals_pseudonymised.json",
])
def test_derive_relations_emits_edges_against_real_shape(fixture: str) -> None:
    doc = _load(fixture)
    concepts = _all_concepts(doc)
    result = derive_relations(doc, concepts=concepts)

    assert len(result.edges) > 0, (
        f"{fixture}: derive_relations produced 0 edges — likely a "
        "contract drift between attrs.blockUid stamping and "
        "structure_relations consumer"
    )
    for edge in result.edges:
        assert edge.source != "" or edge.relation == "DEFINED_BY", (
            f"empty source on non-DEFINED_BY edge: {edge}"
        )
        assert edge.target is not None
```

- [ ] **Step 4: Run the integration test**

Run: `docker compose -f infra/docker-compose.yml exec -T api uv run --project api pytest tests/integration/test_structure_relations_against_production_shape.py -v`
Expected: PASS (4 parametrized cases — 2 fixtures × 2 tests).

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/notes/ tests/integration/test_structure_relations_against_production_shape.py
git commit -m "$(cat <<'EOF'
test(nlp): integration test for derive_relations against real document shape

Pseudonymised fixtures captured from production user_b6b6ef061c81
notes. Structure preserved exactly (blockUids, nesting, lists,
headings); text content replaced with deterministic placeholders.
This is the test that would have caught the original blockUid
contract regression.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Add the AGE legacy-edge purge script

**Files:**
- Create: `api/src/app/scripts/purge_legacy_relations.py`

One-shot data migration. Iterates `public.users.schema_name`; for each tenant graph, deletes legacy LLM-era edge types.

- [ ] **Step 1: Create the script**

Create `api/src/app/scripts/purge_legacy_relations.py`:

```python
"""One-shot data migration: purge legacy LLM-era AGE edges.

Deletes concept→concept edges of types CAUSES, IS_A, RELATED_TO, USES,
BELONGS_TO, APPEARS_IN, PART_OF, CONTRASTS_WITH from every tenant graph.
These edges were emitted by the pre-refactor LLM pipeline. They have no
``source_note_id``, so per-note delete-and-replace sync never removes
them — they're stuck unless explicitly purged.

Idempotent: re-running deletes nothing (counts go to 0).

Usage:
    docker compose -f infra/docker-compose.yml exec -T api \\
        uv run --project api python -m app.scripts.purge_legacy_relations
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from app.db.engine import bind_session_to_tenant, get_session_factory

LEGACY_EDGE_TYPES: list[str] = [
    "CAUSES", "IS_A", "RELATED_TO", "USES",
    "BELONGS_TO", "APPEARS_IN", "PART_OF", "CONTRASTS_WITH",
]

_LOG = logging.getLogger(__name__)


def _purge_for_tenant(schema_name: str) -> dict[str, int]:
    """Run the purge against one tenant graph; return {edge_type: deleted_count}."""
    graph_name = f"nn_{schema_name}"
    factory = get_session_factory()
    types_literal = ", ".join(f"'{t}'" for t in LEGACY_EDGE_TYPES)
    counts: dict[str, int] = {}

    # First: pre-purge tally (per type) for the comparison check.
    with factory() as session:
        bind_session_to_tenant(session, schema_name)
        for edge_type in LEGACY_EDGE_TYPES:
            sql = (
                "SELECT * FROM ag_catalog.cypher("
                f"'{graph_name}', "
                f"$$ MATCH ()-[r:{edge_type}]->() RETURN count(r) $$"
                ") AS (n ag_catalog.agtype)"
            )
            row = session.connection().exec_driver_sql(sql, None).first()
            counts[edge_type] = int(str(row[0])) if row and row[0] is not None else 0

    pre_total = sum(counts.values())
    _LOG.info("tenant=%s pre-purge counts=%s total=%d", schema_name, counts, pre_total)

    # Then: delete.
    with factory() as session:
        bind_session_to_tenant(session, schema_name)
        sql = (
            "SELECT * FROM ag_catalog.cypher("
            f"'{graph_name}', "
            f"$$ MATCH ()-[r]->() WHERE type(r) IN [{types_literal}] DELETE r $$"
            ") AS (v ag_catalog.agtype)"
        )
        session.connection().exec_driver_sql(sql, None).all()
        session.commit()

    # Verify post-purge: every type should report 0.
    with factory() as session:
        bind_session_to_tenant(session, schema_name)
        for edge_type in LEGACY_EDGE_TYPES:
            sql = (
                "SELECT * FROM ag_catalog.cypher("
                f"'{graph_name}', "
                f"$$ MATCH ()-[r:{edge_type}]->() RETURN count(r) $$"
                ") AS (n ag_catalog.agtype)"
            )
            row = session.connection().exec_driver_sql(sql, None).first()
            remaining = int(str(row[0])) if row and row[0] is not None else 0
            assert remaining == 0, (
                f"tenant {schema_name} still has {remaining} {edge_type} edges after purge"
            )

    _LOG.info("tenant=%s purge complete; deleted=%d", schema_name, pre_total)
    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    factory = get_session_factory()
    with factory() as session:
        rows = session.execute(text("SELECT schema_name FROM public.users")).all()

    grand_total = 0
    for (schema_name,) in rows:
        try:
            counts = _purge_for_tenant(schema_name)
        except Exception:  # noqa: BLE001
            _LOG.exception("purge failed for tenant %s", schema_name)
            raise
        grand_total += sum(counts.values())

    _LOG.info("All tenants done. Total legacy edges deleted: %d", grand_total)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-test the script imports cleanly (dry run via --help isn't supported; just import)**

Run: `docker compose -f infra/docker-compose.yml exec -T api uv run --project api python -c "from app.scripts.purge_legacy_relations import LEGACY_EDGE_TYPES; print(LEGACY_EDGE_TYPES)"`
Expected: prints the list, no errors.

- [ ] **Step 3: Commit**

```bash
git add api/src/app/scripts/purge_legacy_relations.py
git commit -m "$(cat <<'EOF'
feat(scripts): add purge_legacy_relations one-shot data migration

Deletes pre-refactor LLM-era AGE edges (CAUSES, IS_A, RELATED_TO,
USES, BELONGS_TO, APPEARS_IN, PART_OF, CONTRASTS_WITH) from every
tenant graph. Includes pre-purge tally, delete, and post-purge
verification per tenant. Idempotent.

Operator-run, not Alembic — this is a property-graph data migration,
not a schema migration.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Operator runbook — backfill execution

**Files:** none (operator instructions only)

This task is run **manually** after the previous ten tasks have all merged. It is *not* part of the automated implementation; the engineer hands off here.

- [ ] **Step 1: Take an AGE-graph backup**

```bash
mkdir -p infra/backups
docker compose -f infra/docker-compose.yml exec -T db pg_dump \
  -U neuronote -d neuronote \
  --schema='nn_user_*' --schema='user_*' \
  > infra/backups/age-graph-pre-purge-2026-05-09.sql
ls -lh infra/backups/age-graph-pre-purge-2026-05-09.sql
```

- [ ] **Step 2: Capture the pre-purge tally**

```bash
docker compose -f infra/docker-compose.yml exec -T db psql -U neuronote -d neuronote -c "
LOAD 'age'; SET search_path = ag_catalog, '\$user', public;
SELECT * FROM cypher('nn_user_b6b6ef061c81',
  \$\$ MATCH ()-[r]->()
       WHERE type(r) IN ['CAUSES','IS_A','RELATED_TO','USES','BELONGS_TO','APPEARS_IN','PART_OF','CONTRASTS_WITH']
       RETURN type(r) AS rel, count(*) AS n \$\$
) AS (rel agtype, n agtype);
" | tee infra/backups/age-graph-pre-purge-counts.txt
```

- [ ] **Step 3: Run the purge**

```bash
docker compose -f infra/docker-compose.yml exec -T api \
  uv run --project api python -m app.scripts.purge_legacy_relations 2>&1 \
  | tee infra/backups/age-graph-purge-log.txt
```

Verify: the log's reported deletion totals match the tally captured in Step 2.

- [ ] **Step 4: Re-extract every existing note**

```bash
docker compose -f infra/docker-compose.yml exec -T api \
  uv run --project api python -m app.scripts.reextract_all_notes \
  --schema user_b6b6ef061c81 2>&1 \
  | tee infra/backups/reextract-log.txt
```

- [ ] **Step 5: Spot-check the resulting graph**

```bash
docker compose -f infra/docker-compose.yml exec -T db psql -U neuronote -d neuronote -c "
LOAD 'age'; SET search_path = ag_catalog, '\$user', public;
SELECT * FROM cypher('nn_user_b6b6ef061c81',
  \$\$ MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS n \$\$
) AS (rel agtype, n agtype) ORDER BY rel;
"
```

Expected edge types and **only** these edge types: `MENTIONS`, `CONTAINS`, `HAS_CHILD`, `MENTIONED_TOGETHER`, `SUBTOPIC_OF`, `SYNONYM_OF`, `SIBLING_OF`, `REFERENCES`, `DEFINED_BY`. Any of `CAUSES / IS_A / RELATED_TO / USES / BELONGS_TO / APPEARS_IN / PART_OF / CONTRASTS_WITH` appearing means the purge failed for some tenant — investigate.

- [ ] **Step 6: Spot-check `extraction_summary` for non-zero relations**

```bash
docker compose -f infra/docker-compose.yml exec -T db psql -U neuronote -d neuronote -c "
SELECT note_id, status, extraction_summary
FROM user_b6b6ef061c81.processing_jobs
WHERE status='completed'
ORDER BY updated_at DESC LIMIT 7;
"
```

Expected: `extraction_summary.relation_count > 0` on at least the longer notes (Syntax, 2026 Goals, JS, Variables). Short notes (English movies) may legitimately be 0.

- [ ] **Step 7: Tail the API logs for `relation_count=0` warnings**

```bash
docker compose -f infra/docker-compose.yml logs api --since 5m | grep "Suspicious extraction" || echo "no warnings — good"
```

If any warnings appear, those notes deserve a manual look — they have ≥3 concepts × ≥3 blocks but produced 0 relations.

---

## Self-review

**Spec coverage check** — every spec section maps to tasks:

- §Architecture (write/read boundaries, contract location) → Tasks 1–4 (write), 5–7 (read)
- §Components new (`app/utils/tiptap.py`, contracts, health metric) → Tasks 1, 2, 3, 8
- §Modified components (`structure_relations`, `block_repository`, `note_processing_service`) → Tasks 4, 6, 7, 8
- §Purge list items 1–6 (code-level) → Tasks 6, 9
- §Purge list items 7 (AGE edges) → Tasks 10, 11
- §Purge list item 8 (BlockInfo.block_id audit) → handled in Task 6's rewrite (the new `BlockInfo` lives in `app.utils.tiptap` with `block_uid` as the field; the old `block_id` field is gone)
- §Purge list item 9 (`_ensure_block_uid` promotion) → Task 1, 4
- §Testing — production-shape fixture, unit rewrites, contract test, health-metric test, coverage matrix → Tasks 2, 3, 6, 8, 9
- §Rollout & ordering → Tasks 1–10 are the seven-commit ordering (Task 10 = step 7 of the spec); Task 11 = deploy steps 2–6
- §Rollback — covered by the AGE backup in Task 11 step 1; revert plan is implicit (revert commits)

**Placeholder scan:** none — every code step has actual code.

**Type consistency:** `BlockInfo` carries `block_uid` (snake_case) consistently across the new util (Task 2) and the rewritten `structure_relations` (Task 6). `RelationDerivation.edges` and `.distinct_blocks_with_concepts` consistent across Tasks 5–8. `StructureEdge` lives in `app.nlp.types` after Task 5; structure_relations imports it from there (Task 6).

**Unresolved item from the spec's "Open questions"**: `BlockInfo.block_id` — the rewrite uses `block_uid` directly, so no audit needed. Resolved.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-09-deterministic-relations-contract.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
