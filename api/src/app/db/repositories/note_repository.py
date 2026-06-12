from __future__ import annotations

from dataclasses import dataclass
import hashlib

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db.models.note import Note
from app.db.models.note_tag import NoteTag
from app.db.models.subject import Subject
from app.db.models.tag import Tag
from app.db.repositories.block_repository import BlockRepository
from app.utils.text import collapse_whitespace, extract_wiki_link_titles, normalize_title, normalize_title_key

DEFAULT_SUBJECT_ID = "inbox"
DEFAULT_SUBJECT_NAME = "Inbox"


@dataclass(slots=True)
class NoteRecord:
    note_id: str
    subject_id: str
    note_title: str
    tags: list[str]
    is_pinned: bool
    is_archived: bool
    content_json: dict[str, object]
    content_text: str
    content_hash: str
    updated_at: str
    version: int


@dataclass(slots=True)
class NoteSummaryRecord:
    note_id: str
    note_title: str
    subject_id: str
    tags: list[str]
    is_pinned: bool
    is_archived: bool
    content_text: str
    updated_at: str
    version: int


@dataclass(slots=True)
class BacklinkRecord:
    source_note_id: str
    source_note_title: str
    matched_title: str
    snippet: str
    updated_at: str


class NoteTitleConflictError(Exception):
    def __init__(self, normalized_title: str) -> None:
        super().__init__(f"A note with title '{normalized_title}' already exists")
        self.normalized_title = normalized_title


class NoteRepository:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._blocks = BlockRepository(session)

    def _subject_name_from_id(self, subject_id: str) -> str:
        stripped = subject_id.strip()
        if not stripped:
            return DEFAULT_SUBJECT_NAME
        return stripped

    def _ensure_subject(self, subject_id: str) -> None:
        existing_subject = self._session.get(Subject, subject_id)
        if existing_subject is not None:
            return
        self._session.add(
            Subject(
                id=subject_id,
                name=self._subject_name_from_id(subject_id),
            )
        )
        self._session.flush()

    def _normalize_tags(self, tags: list[str] | None) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for tag in tags or []:
            cleaned = tag.strip().lower()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            normalized.append(cleaned)
        return normalized

    def _assert_unique_title_for_note(self, *, note_id: str, note_title: str) -> None:
        normalized_key = normalize_title_key(note_title)
        conflict = self._session.execute(
            select(Note.note_id).where(
                Note.note_id != note_id,
                func.lower(Note.note_title) == normalized_key,
            ).limit(1),
        ).first()
        if conflict is not None:
            raise NoteTitleConflictError(normalize_title(note_title))

    def _make_backlink_snippet(self, content_text: str, matched_title: str) -> str:
        token = f"[[{matched_title}]]"
        lower_content = content_text.lower()
        lower_token = token.lower()
        start = lower_content.find(lower_token)
        if start < 0:
            compact = collapse_whitespace(content_text)
            return compact[:140] if compact else matched_title

        window_start = max(0, start - 40)
        window_end = min(len(content_text), start + len(token) + 80)
        snippet = collapse_whitespace(content_text[window_start:window_end])
        if window_start > 0:
            snippet = f"...{snippet}"
        if window_end < len(content_text):
            snippet = f"{snippet}..."
        return snippet or matched_title

    def _replace_tags(self, *, note_id: str, tags: list[str]) -> None:
        self._session.execute(
            delete(NoteTag).where(NoteTag.note_id == note_id),
        )
        self._session.flush()
        if not tags:
            return

        for tag_name in tags:
            tag = self._session.execute(
                select(Tag).where(func.lower(Tag.name) == tag_name),
            ).scalar_one_or_none()
            if tag is None:
                tag = Tag(name=tag_name)
                self._session.add(tag)
                self._session.flush()

            self._session.add(
                NoteTag(
                    note_id=note_id,
                    tag_id=tag.id,
                )
            )

        self._session.flush()

    def _load_tag_names(self, note_id: str) -> list[str]:
        rows = self._session.execute(
            select(Tag.name)
            .join(NoteTag, NoteTag.tag_id == Tag.id)
            .where(NoteTag.note_id == note_id)
            .order_by(Tag.name.asc()),
        ).all()
        return [str(row[0]) for row in rows]

    def _build_list_query(
        self,
        *,
        search: str | None,
        subject_id: str | None,
        tag: str | None,
        is_archived: bool | None,
        is_pinned: bool | None,
    ):
        statement = select(Note)

        normalized_tag = (tag or "").strip().lower()
        if normalized_tag:
            tag_match_exists = (
                select(NoteTag.note_id)
                .join(Tag, Tag.id == NoteTag.tag_id)
                .where(
                    NoteTag.note_id == Note.note_id,
                    func.lower(Tag.name) == normalized_tag,
                )
                .exists()
            )
            statement = statement.where(tag_match_exists)

        normalized_search = (search or "").strip().lower()
        if normalized_search:
            like_pattern = f"%{normalized_search}%"
            statement = statement.where(
                or_(
                    func.lower(Note.note_title).like(like_pattern),
                    func.lower(Note.content_text).like(like_pattern),
                )
            )

        normalized_subject = (subject_id or "").strip()
        if normalized_subject:
            statement = statement.where(Note.subject_id == normalized_subject)

        if is_archived is not None:
            statement = statement.where(Note.is_archived == is_archived)

        if is_pinned is not None:
            statement = statement.where(Note.is_pinned == is_pinned)

        return statement

    def upsert_note(
        self,
        *,
        note_id: str,
        note_title: str,
        subject_id: str = DEFAULT_SUBJECT_ID,
        tags: list[str] | None = None,
        is_pinned: bool = False,
        is_archived: bool = False,
        content_json: dict[str, object],
        content_text: str,
        updated_at: str,
    ) -> NoteRecord:
        resolved_subject_id = subject_id.strip() or DEFAULT_SUBJECT_ID
        normalized_title = normalize_title(note_title)
        normalized_tags = self._normalize_tags(tags)

        self._assert_unique_title_for_note(note_id=note_id, note_title=normalized_title)
        self._ensure_subject(resolved_subject_id)

        existing = self._session.execute(
            select(Note).where(Note.note_id == note_id),
        ).scalar_one_or_none()

        combined_for_hash = f"{normalized_title}\n\n{content_text}"
        content_hash = hashlib.sha256(combined_for_hash.encode("utf-8")).hexdigest()
        if existing is None:
            existing = Note(
                note_id=note_id,
                subject_id=resolved_subject_id,
                note_title=normalized_title,
                is_pinned=is_pinned,
                is_archived=is_archived,
                content_json=content_json,
                content_text=content_text,
                content_hash=content_hash,
                updated_at=updated_at,
                version=1,
            )
            self._session.add(existing)
        else:
            existing.subject_id = resolved_subject_id
            existing.note_title = normalized_title
            existing.is_pinned = is_pinned
            existing.is_archived = is_archived
            existing.content_json = content_json
            existing.content_text = content_text
            existing.content_hash = content_hash
            existing.updated_at = updated_at
            existing.version += 1

        self._session.flush()
        self._replace_tags(note_id=note_id, tags=normalized_tags)
        normalized_content_json = self._blocks.replace_blocks(
            note_id=note_id,
            content_json=content_json,
            fallback_text=content_text,
        )
        existing.content_json = normalized_content_json
        self._session.flush()

        return NoteRecord(
            note_id=existing.note_id,
            subject_id=existing.subject_id,
            note_title=existing.note_title,
            tags=self._load_tag_names(existing.note_id),
            is_pinned=bool(existing.is_pinned),
            is_archived=bool(existing.is_archived),
            content_json=dict(existing.content_json),
            content_text=existing.content_text,
            content_hash=existing.content_hash,
            updated_at=existing.updated_at,
            version=existing.version,
        )

    def get_note(self, note_id: str) -> NoteRecord | None:
        existing = self._session.execute(
            select(Note).where(Note.note_id == note_id),
        ).scalar_one_or_none()
        if existing is None:
            return None

        return NoteRecord(
            note_id=existing.note_id,
            subject_id=existing.subject_id,
            note_title=existing.note_title,
            tags=self._load_tag_names(existing.note_id),
            is_pinned=bool(existing.is_pinned),
            is_archived=bool(existing.is_archived),
            content_json=dict(existing.content_json),
            content_text=existing.content_text,
            content_hash=existing.content_hash,
            updated_at=existing.updated_at,
            version=existing.version,
        )

    def list_notes(
        self,
        *,
        limit: int,
        offset: int,
        search: str | None = None,
        subject_id: str | None = None,
        tag: str | None = None,
        is_archived: bool | None = False,
        is_pinned: bool | None = None,
    ) -> tuple[list[NoteSummaryRecord], int]:
        base_query = self._build_list_query(
            search=search,
            subject_id=subject_id,
            tag=tag,
            is_archived=is_archived,
            is_pinned=is_pinned,
        )

        rows = self._session.execute(
            base_query
            .options(selectinload(Note.tags))
            .order_by(Note.is_pinned.desc(), Note.saved_at.desc(), Note.note_id.asc())
            .limit(limit)
            .offset(offset),
        ).scalars().all()

        total = self._session.execute(
            select(func.count()).select_from(
                base_query.order_by(None).limit(None).offset(None).subquery()
            ),
        ).scalar_one()

        items = [
            NoteSummaryRecord(
                note_id=row.note_id,
                note_title=row.note_title,
                subject_id=row.subject_id,
                tags=sorted(tag.name for tag in row.tags),
                is_pinned=bool(row.is_pinned),
                is_archived=bool(row.is_archived),
                content_text=row.content_text,
                updated_at=row.updated_at,
                version=row.version,
            )
            for row in rows
        ]
        return items, int(total)

    def list_backlinks_for_note(self, note_id: str) -> list[BacklinkRecord]:
        target = self._session.execute(
            select(Note.note_id, Note.note_title).where(Note.note_id == note_id),
        ).one_or_none()
        if target is None:
            return []

        _, target_title = target
        normalized_target_title = normalize_title(str(target_title))
        normalized_target_key = normalized_target_title.lower()
        if not normalized_target_title:
            return []

        # Use a LIKE filter to pre-filter notes containing [[...target_title...]] without
        # a full table scan. Spaces are replaced with % to tolerate non-normalised whitespace
        # in stored content (e.g. [[Graph   Reasoning]] still matches "graph reasoning").
        # False positives survive to the Python-side exact-match check below.
        word_fragment = "%".join(normalized_target_key.split())
        wiki_link_pattern = f"%[[%{word_fragment}%]]%"
        rows = self._session.execute(
            select(Note.note_id, Note.note_title, Note.content_text, Note.updated_at).where(
                Note.note_id != note_id,
                func.lower(Note.content_text).like(wiki_link_pattern),
            ),
        ).all()

        backlinks: list[BacklinkRecord] = []
        for source_note_id, source_note_title, source_content_text, source_updated_at in rows:
            # Confirm the LIKE hit is an actual wiki-link (not a false positive substring).
            linked_titles = {
                title.lower() for title in extract_wiki_link_titles(str(source_content_text))
            }
            if normalized_target_key not in linked_titles:
                continue
            backlinks.append(
                BacklinkRecord(
                    source_note_id=str(source_note_id),
                    source_note_title=str(source_note_title),
                    matched_title=normalized_target_title,
                    snippet=self._make_backlink_snippet(str(source_content_text), normalized_target_title),
                    updated_at=str(source_updated_at),
                )
            )

        backlinks.sort(key=lambda item: item.source_note_id)
        backlinks.sort(key=lambda item: item.updated_at, reverse=True)
        return backlinks

    def list_note_ids(self) -> list[str]:
        rows = self._session.execute(
            select(Note.note_id).order_by(Note.note_id.asc()),
        ).all()
        return [str(row[0]) for row in rows]

    def delete_note(self, note_id: str) -> bool:
        existing = self._session.get(Note, note_id)
        if existing is None:
            return False

        self._session.delete(existing)
        self._session.flush()
        return True
