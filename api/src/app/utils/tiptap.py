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
