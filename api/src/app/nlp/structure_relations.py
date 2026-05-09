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
