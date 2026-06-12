from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import re
from uuid import uuid4  # used for fallback_uid in _extract_blocks

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models.block import Block
from app.db.models.note import Note
from app.utils.text import collapse_whitespace
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


def _make_ref_snippet(content_text: str, block_uid: str) -> str:
    token = f"(({block_uid}))"
    start = content_text.find(token)
    if start < 0:
        compact = collapse_whitespace(content_text)
        return compact[:140]

    window_start = max(0, start - 40)
    window_end = min(len(content_text), start + len(token) + 80)
    snippet = collapse_whitespace(content_text[window_start:window_end])
    if window_start > 0:
        snippet = f"...{snippet}"
    if window_end < len(content_text):
        snippet = f"{snippet}..."
    return snippet


def _extract_mark_ref_uid(node: dict[str, object]) -> str | None:
    marks = node.get("marks")
    if not isinstance(marks, list):
        return None

    for mark_value in marks:
        mark = _as_object(mark_value)
        if mark is None:
            continue
        if str(mark.get("type") or "") != "referenceLink":
            continue
        attrs = _as_object(mark.get("attrs"))
        if attrs is None:
            continue
        ref_type = str(attrs.get("dataRefType") or "").strip().lower()
        if ref_type != "block":
            continue

        raw_uid = attrs.get("dataBlockUid")
        if isinstance(raw_uid, str) and raw_uid.strip():
            return raw_uid.strip()

        href = attrs.get("href")
        if isinstance(href, str):
            href_match = _BLOCK_REF_HREF_PATTERN.search(href)
            if href_match:
                return href_match.group(1).strip()
    return None


def _extract_node_ref_uids(node: object, refs: list[str], seen: set[str]) -> None:
    if isinstance(node, list):
        for item in node:
            _extract_node_ref_uids(item, refs, seen)
        return

    if not isinstance(node, dict):
        return

    mark_uid = _extract_mark_ref_uid(node)
    if mark_uid and mark_uid not in seen:
        seen.add(mark_uid)
        refs.append(mark_uid)

    text_value = node.get("text")
    if isinstance(text_value, str):
        for match in _BLOCK_REF_PATTERN.finditer(text_value):
            candidate = match.group(1).strip()
            if candidate and candidate not in seen:
                seen.add(candidate)
                refs.append(candidate)

    content_value = node.get("content")
    if isinstance(content_value, list):
        for child in content_value:
            _extract_node_ref_uids(child, refs, seen)


def _extract_explicit_parent_uid(
    node: dict[str, object],
    *,
    self_uid: str,
    latest_uid_by_raw: dict[str, str],
) -> str | None:
    attrs = _as_object(node.get("attrs"))
    if attrs is None:
        return None
    raw_parent_uid = attrs.get("parentBlockUid")
    if not isinstance(raw_parent_uid, str):
        return None
    parent_uid = raw_parent_uid.strip()
    if not parent_uid or parent_uid == self_uid:
        return None
    mapped_parent_uid = latest_uid_by_raw.get(parent_uid, parent_uid)
    if mapped_parent_uid != parent_uid:
        attrs["parentBlockUid"] = mapped_parent_uid
        node["attrs"] = attrs
    if mapped_parent_uid == self_uid:
        return None
    return mapped_parent_uid


def _walk_nodes(
    *,
    nodes: list[object],
    parent_block_uid: str | None,
    rows: list[_ExtractionRow],
    sibling_counter_by_parent: dict[str | None, int],
    used_uids: set[str],
    latest_uid_by_raw: dict[str, str],
    next_block_index: int,
) -> int:
    for raw_node in nodes:
        node = _as_object(raw_node)
        if node is None:
            continue

        node_type = str(node.get("type") or "")
        child_parent_uid = parent_block_uid
        if node_type in _BLOCK_NODE_TYPES:
            block_uid = _ensure_block_uid(
                node,
                used=used_uids,
                latest_by_raw=latest_uid_by_raw,
            )
            explicit_parent_uid = _extract_explicit_parent_uid(
                node,
                self_uid=block_uid,
                latest_uid_by_raw=latest_uid_by_raw,
            )
            effective_parent_uid = explicit_parent_uid or parent_block_uid
            content_text = _extract_plain_text(node).strip()
            sibling_order = sibling_counter_by_parent.get(effective_parent_uid, 0)
            sibling_counter_by_parent[effective_parent_uid] = sibling_order + 1
            rows.append(
                _ExtractionRow(
                    block_uid=block_uid,
                    parent_block_uid=effective_parent_uid,
                    sibling_order=sibling_order,
                    block_index=next_block_index,
                    content_text=content_text,
                    content_hash=hashlib.sha256(content_text.encode("utf-8")).hexdigest(),
                    rich_content=node,
                )
            )
            next_block_index += 1
            if node_type in _CHILD_CONTAINER_TYPES:
                child_parent_uid = block_uid

        children = node.get("content")
        if isinstance(children, list):
            next_block_index = _walk_nodes(
                nodes=children,
                parent_block_uid=child_parent_uid,
                rows=rows,
                sibling_counter_by_parent=sibling_counter_by_parent,
                used_uids=used_uids,
                latest_uid_by_raw=latest_uid_by_raw,
                next_block_index=next_block_index,
            )

    return next_block_index


def _extract_blocks(
    content_json: dict[str, object],
    *,
    fallback_text: str,
) -> tuple[list[_ExtractionRow], dict[str, object]]:
    rows: list[_ExtractionRow] = []
    raw_content = content_json.get("content")
    if isinstance(raw_content, list):
        sibling_counter_by_parent: dict[str | None, int] = {}
        used_uids: set[str] = set()
        latest_uid_by_raw: dict[str, str] = {}
        _walk_nodes(
            nodes=raw_content,
            parent_block_uid=None,
            rows=rows,
            sibling_counter_by_parent=sibling_counter_by_parent,
            used_uids=used_uids,
            latest_uid_by_raw=latest_uid_by_raw,
            next_block_index=0,
        )

    if not rows:
        fallback_uid = uuid4().hex
        rows.append(
            _ExtractionRow(
                block_uid=fallback_uid,
                parent_block_uid=None,
                sibling_order=0,
                block_index=0,
                content_text=fallback_text,
                content_hash=hashlib.sha256(fallback_text.encode("utf-8")).hexdigest(),
                rich_content=content_json,
            )
        )

    return rows, content_json


class BlockRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def replace_blocks(
        self,
        *,
        note_id: str,
        content_json: dict[str, object],
        fallback_text: str,
    ) -> dict[str, object]:
        normalized_source = deepcopy(content_json)
        rows, normalized_json = _extract_blocks(normalized_source, fallback_text=fallback_text)
        self._session.execute(delete(Block).where(Block.note_id == note_id))

        for row in rows:
            self._session.add(
                Block(
                    note_id=note_id,
                    block_uid=row.block_uid,
                    parent_block_uid=row.parent_block_uid,
                    sibling_order=row.sibling_order,
                    block_index=row.block_index,
                    content_text=row.content_text,
                    content_hash=row.content_hash,
                    rich_content=row.rich_content,
                )
            )
        return normalized_json

    def list_blocks_for_note(self, note_id: str) -> list[BlockRecord]:
        rows = self._session.execute(
            select(Block)
            .where(Block.note_id == note_id)
            .order_by(Block.block_index.asc()),
        ).scalars()
        return [
            BlockRecord(
                block_uid=row.block_uid,
                note_id=row.note_id,
                parent_block_uid=row.parent_block_uid,
                sibling_order=row.sibling_order,
                block_index=row.block_index,
                content_text=row.content_text,
                rich_content=dict(row.rich_content),
            )
            for row in rows
        ]

    def _search_rows(self, *, query: str, note_id: str | None, limit: int) -> list[BlockSearchRecord]:
        like = f"%{query.strip().lower()}%"
        statement = (
            select(Block, Note.note_title)
            .join(Note, Note.note_id == Block.note_id)
            .where(func.lower(Block.content_text).like(like))
            .order_by(Note.updated_at.desc(), Note.note_id.asc(), Block.block_index.asc())
            .limit(limit)
        )
        if note_id is not None:
            statement = statement.where(Block.note_id == note_id)

        rows = self._session.execute(statement).all()
        return [
            BlockSearchRecord(
                block_uid=block.block_uid,
                note_id=block.note_id,
                note_title=str(note_title),
                content_text=block.content_text,
            )
            for block, note_title in rows
        ]

    def search_blocks(self, *, query: str, note_id: str | None, limit: int) -> list[BlockSearchRecord]:
        normalized = query.strip()
        if not normalized:
            statement = (
                select(Block, Note.note_title)
                .join(Note, Note.note_id == Block.note_id)
                .order_by(Note.updated_at.desc(), Note.note_id.asc(), Block.block_index.asc())
                .limit(limit)
            )
            if note_id is not None:
                statement = statement.where(Block.note_id == note_id)
            rows = self._session.execute(statement).all()
            return [
                BlockSearchRecord(
                    block_uid=block.block_uid,
                    note_id=block.note_id,
                    note_title=str(note_title),
                    content_text=block.content_text,
                )
                for block, note_title in rows
            ]

        return self._search_rows(query=normalized, note_id=note_id, limit=limit)

    def get_blocks_by_uid(self, block_uids: list[str]) -> list[BlockRecord]:
        if not block_uids:
            return []

        rows = self._session.execute(
            select(Block)
            .where(Block.block_uid.in_(block_uids))
            .order_by(Block.note_id.asc(), Block.block_index.asc()),
        ).scalars()
        return [
            BlockRecord(
                block_uid=row.block_uid,
                note_id=row.note_id,
                parent_block_uid=row.parent_block_uid,
                sibling_order=row.sibling_order,
                block_index=row.block_index,
                content_text=row.content_text,
                rich_content=dict(row.rich_content),
            )
            for row in rows
        ]

    def list_block_backlinks(self, block_uid: str) -> list[BlockBacklinkRecord] | None:
        target_exists = self._session.execute(
            select(Block.block_uid).where(Block.block_uid == block_uid),
        ).scalar_one_or_none()
        if target_exists is None:
            return None

        rows = self._session.execute(
            select(Block, Note.note_title, Note.updated_at)
            .join(Note, Note.note_id == Block.note_id)
            .where(Block.block_uid != block_uid)
            .order_by(Note.updated_at.desc(), Block.note_id.asc(), Block.block_uid.asc()),
        ).all()

        backlinks: list[BlockBacklinkRecord] = []
        for block, note_title, updated_at in rows:
            refs = self.extract_block_refs_from_rich_content(dict(block.rich_content))
            if not refs:
                refs = self.extract_block_refs(block.content_text)
            if block_uid not in refs:
                continue
            backlinks.append(
                BlockBacklinkRecord(
                    source_block_uid=block.block_uid,
                    source_note_id=block.note_id,
                    source_note_title=str(note_title),
                    snippet=_make_ref_snippet(block.content_text, block_uid),
                    updated_at=str(updated_at),
                )
            )
        return backlinks

    def extract_block_refs(self, content_text: str) -> list[str]:
        refs: list[str] = []
        seen: set[str] = set()
        for match in _BLOCK_REF_PATTERN.finditer(content_text):
            candidate = match.group(1).strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            refs.append(candidate)
        return refs

    def extract_block_refs_from_rich_content(self, rich_content: dict[str, object]) -> list[str]:
        refs: list[str] = []
        seen: set[str] = set()
        _extract_node_ref_uids(rich_content, refs, seen)
        return refs
