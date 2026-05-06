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
