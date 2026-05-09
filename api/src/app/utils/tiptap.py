"""Shared TipTap document utilities.

Single source of truth for block-ID stamping and plain-text extraction.
Owners: anything that produces a TipTap ``content_json`` (storage,
import, future paste handlers) calls ``ensure_block_uids`` before
persistence; anything that consumes one (NLP pipeline, exporters) reads
``attrs.blockUid`` and trusts it to be present.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator, Literal
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

    Case-insensitive. Uses ``(?<![\\w])`` / ``(?![\\w])`` lookarounds instead of
    bare ``\\b`` so that concepts ending in non-word characters (e.g. ``C++``)
    are matched correctly — ``\\b`` only anchors at word/non-word transitions,
    so it would fail to bound a ``+`` character.
    """
    if not text or not concepts:
        return set()
    out: set[str] = set()
    for c in concepts:
        if not c:
            continue
        pattern = rf"(?<!\w){re.escape(c)}(?!\w)"
        if re.search(pattern, text, flags=re.IGNORECASE):
            out.add(c)
    return out
