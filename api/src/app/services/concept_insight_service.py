"""Concept insight generation grounded in the user's own notes.

When a user clicks a concept node in any graph view the frontend calls
``GET /v1/concepts/insight?label=<concept>``.  This service:

1. Full-text searches all notes for the concept label (title + body).
2. Builds a context string of up to ``_MAX_NOTES`` notes (600 chars each).
3. If ``LLM_API_KEY`` is configured, calls the LLM with a strictly-grounded
   system prompt that forbids external knowledge in the insight paragraph.
4. Returns note references (with snippets), the insight, and learning links.

Results are cached in the ``concept_insight_cache`` table keyed by
``(concept_label, content_digest)``.  The digest is a SHA-256 of the sorted
``note_id:content_hash`` pairs for the matching notes, so the cache entry
becomes stale automatically when any relevant note changes.

Graceful degradation:
- No API key → ``insight`` is ``None``; note references still return.
- LLM timeout / parse error → same as no API key for that request.
- No matching notes → empty ``note_refs``, ``notes_found = 0``.
- Non-PostgreSQL DB (SQLite dev) → cache ops silently skipped.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.db.models.concept_insight_cache import ConceptInsightCache
from app.db.models.note import Note
from app.nlp.config import NlpSettings, get_nlp_settings
from app.nlp.llm_client import AsyncLLMClient
from shared.contracts.python.v1.graph import (
    ConceptInsightResponse,
    ConceptLearningLink,
    ConceptNoteRef,
)

_LOGGER = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a knowledge synthesis assistant. Generate an insight about a concept based \
SOLELY on the user's own notes.

Rules:
- The insight must draw only from the provided notes. Do not add external knowledge.
- Reference note titles explicitly, e.g. "In your note 'Title'...".
- Keep the insight to 2–3 focused paragraphs.
- For learning_links: suggest 3–4 genuinely reputable URLs (Wikipedia, official \
documentation, well-known academic sources). Use only real, widely-known URLs.

Respond ONLY with valid JSON in exactly this shape (no markdown fences):
{
  "insight": "...",
  "learning_links": [
    {"title": "...", "url": "https://...", "description": "..."}
  ]
}"""

_MAX_NOTES = 10
_MAX_CONTENT_PER_NOTE = 600   # chars of content passed to LLM per note
_SNIPPET_BEFORE = 60          # chars before the match in the UI snippet
_SNIPPET_AFTER = 90           # chars after the match in the UI snippet


def _compute_digest(notes: list[Note]) -> str:
    """SHA-256 of sorted 'note_id:content_hash' pairs — stale when notes change."""
    note_keys = sorted(f"{n.note_id}:{n.content_hash}" for n in notes)
    return hashlib.sha256("|".join(note_keys).encode()).hexdigest()


class ConceptInsightService:
    def __init__(
        self,
        session: Session,
        settings: NlpSettings | None = None,
        graph_name: str = "neuronote",
    ) -> None:
        self._session = session
        self._graph_name = graph_name
        cfg = settings or get_nlp_settings()
        self._api_key: str = cfg.llm_api_key
        self._model: str = cfg.llm_model
        self._base_url: str = cfg.llm_base_url

    # ── Public ──────────────────────────────────────────────────────────────

    async def get_insight(
        self,
        concept_label: str,
        limit_notes: int = _MAX_NOTES,
    ) -> ConceptInsightResponse:
        notes = self._find_notes(
            concept_label,
            limit=min(limit_notes, _MAX_NOTES),
        )
        note_refs = [self._make_ref(note, concept_label) for note in notes]

        insight: str | None = None
        insight_error: str | None = None
        links: list[ConceptLearningLink] = []

        if notes and self._api_key:
            content_digest = _compute_digest(notes)
            cached = self._get_cached_insight(concept_label, content_digest)
            if cached is not None:
                insight = cached["insight"]
                links = [
                    ConceptLearningLink(**lnk)
                    for lnk in cached["learning_links"]
                    if isinstance(lnk, dict)
                    and all(k in lnk for k in ("title", "url", "description"))
                ]
            else:
                context = self._build_context(concept_label, notes)
                raw, insight_error = await self._call_llm(concept_label, context)
                insight = raw.get("insight") or None
                links = [
                    ConceptLearningLink(**lnk)
                    for lnk in raw.get("learning_links", [])
                    if isinstance(lnk, dict)
                    and all(k in lnk for k in ("title", "url", "description"))
                ]
                if insight:
                    insight_error = None  # success overrides any prior error
                    self._save_cached_insight(
                        concept_label, content_digest, insight, links, len(notes)
                    )

        return ConceptInsightResponse(
            concept_label=concept_label,
            notes_found=len(notes),
            note_refs=note_refs,
            insight=insight,
            insight_error=insight_error,
            learning_links=links,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    # ── Cache helpers ────────────────────────────────────────────────────────

    def _get_cached_insight(self, label: str, digest: str) -> dict | None:  # type: ignore[type-arg]
        try:
            row = self._session.execute(
                select(ConceptInsightCache).where(
                    ConceptInsightCache.concept_label == label,
                    ConceptInsightCache.content_digest == digest,
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return {
                "insight": row.insight,
                "learning_links": json.loads(row.learning_links),
            }
        except Exception:  # noqa: BLE001
            # Roll back so the session is clean for subsequent queries
            # (a failed SELECT aborts the PostgreSQL transaction).
            try:
                self._session.rollback()
            except Exception:  # noqa: BLE001
                pass
            return None

    def _save_cached_insight(
        self,
        label: str,
        digest: str,
        insight: str,
        links: list[ConceptLearningLink],
        count: int,
    ) -> None:
        try:
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            links_json = json.dumps([lnk.model_dump() for lnk in links])
            now = datetime.now(timezone.utc)
            stmt = (
                pg_insert(ConceptInsightCache)
                .values(
                    concept_label=label,
                    content_digest=digest,
                    insight=insight,
                    learning_links=links_json,
                    notes_count=count,
                    generated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["concept_label"],
                    set_={
                        "content_digest": digest,
                        "insight": insight,
                        "learning_links": links_json,
                        "notes_count": count,
                        "generated_at": now,
                    },
                )
            )
            self._session.execute(stmt)
            self._session.commit()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("concept_insight_cache write skipped", exc_info=True)

    # ── Private ─────────────────────────────────────────────────────────────

    def _find_notes(self, label: str, limit: int) -> list[Note]:
        """Find notes mentioning *label*.

        Phase 1 — case-insensitive **whole-word** search on title + content
        (fast, covers verbatim matches without false hits like "art" inside
        "smart"). On PostgreSQL this uses a word-boundary regex (``~*`` with
        ``\\y``); on the SQLite test fallback it degrades to a substring LIKE.
        Phase 2 — query the AGE graph for MENTIONS edges (direct match) plus
        SYNONYM_OF and SUBTOPIC_OF traversal, catching concepts that were
        normalised during extraction (e.g. note says "ML" but concept is
        "machine learning") or are subtopics of the searched concept.
        """
        bind = self._session.bind
        if bind is not None and bind.dialect.name == "postgresql":
            # \y = word boundary in Postgres POSIX regex; ~* = case-insensitive.
            pattern = rf"\y{re.escape(label)}\y"
            title_match = Note.note_title.op("~*")(pattern)
            content_match = Note.content_text.op("~*")(pattern)
        else:
            like = f"%{label.lower()}%"
            title_match = func.lower(Note.note_title).like(like)
            content_match = func.lower(Note.content_text).like(like)

        rows = self._session.execute(
            select(Note)
            .where(or_(title_match, content_match))
            .order_by(Note.updated_at.desc())
            .limit(limit)
        ).scalars().all()

        if rows:
            return list(rows)

        # Phase 2: find note IDs via graph traversal (MENTIONS + SYNONYM_OF + SUBTOPIC_OF).
        note_ids = self._find_note_ids_via_graph(label, limit)
        if note_ids:
            fallback_rows = self._session.execute(
                select(Note)
                .where(Note.note_id.in_(note_ids))
                .order_by(Note.updated_at.desc())
                .limit(limit)
            ).scalars().all()
            if fallback_rows:
                return list(fallback_rows)

        return []

    def _find_note_ids_via_graph(self, label: str, limit: int) -> list[str]:
        """Return note IDs from AGE MENTIONS edges for entities matching *label*.

        Silently returns [] on non-PostgreSQL connections or any AGE error.
        """
        try:
            bind = self._session.bind
            if bind is None or bind.dialect.name != "postgresql":
                return []

            self._session.execute(text("LOAD 'age'"))
            self._session.execute(
                text('SET search_path = ag_catalog, "$user", public')
            )

            label_json = json.dumps(label.lower())
            cypher_query = f"""
                MATCH ()-[m:MENTIONS]->(e:Entity)
                WHERE toLower(e.name) = {label_json}
                RETURN DISTINCT m.source_note_id
                UNION
                MATCH ()-[m:MENTIONS]->(e:Entity)-[:SYNONYM_OF]-(syn:Entity)
                WHERE toLower(syn.name) = {label_json}
                RETURN DISTINCT m.source_note_id
                UNION
                MATCH ()-[m:MENTIONS]->(specific:Entity)-[:SUBTOPIC_OF]->(broader:Entity)
                WHERE toLower(broader.name) = {label_json}
                RETURN DISTINCT m.source_note_id
            """
            # Use exec_driver_sql so the Cypher query is a bound driver parameter.
            # This bypasses SQLAlchemy's _pyformat_pattern scanner, which would
            # misinterpret %(name)s patterns in user-controlled label text.
            conn = self._session.connection()
            rows = conn.exec_driver_sql(
                "SELECT * FROM ag_catalog.cypher(%s, %s) AS (source_note_id ag_catalog.agtype)",
                (self._graph_name, cypher_query),
            ).fetchall()

            note_ids: list[str] = []
            for row in rows:
                raw = str(row[0])
                # AGE returns string values as JSON-encoded: "\"note-id\""
                note_ids.append(json.loads(raw) if raw.startswith('"') else raw)
            return note_ids[:limit]
        except Exception:  # noqa: BLE001
            _LOGGER.debug("graph MENTIONS lookup skipped for label=%r", label, exc_info=True)
            return []

    def _make_ref(self, note: Note, label: str) -> ConceptNoteRef:
        raw_text: str = note.content_text or ""
        lower_text = raw_text.lower()
        pos = lower_text.find(label.lower())
        if pos >= 0:
            start = max(0, pos - _SNIPPET_BEFORE)
            end = min(len(raw_text), pos + len(label) + _SNIPPET_AFTER)
            snippet = ("…" if start > 0 else "") + raw_text[start:end].strip() + "…"
        else:
            snippet = raw_text[:150].strip() + ("…" if len(raw_text) > 150 else "")
        return ConceptNoteRef(
            note_id=note.note_id,
            note_title=note.note_title,
            snippet=snippet,
        )

    def _build_context(self, label: str, notes: list[Note]) -> str:
        parts: list[str] = []
        for i, note in enumerate(notes, 1):
            content = (note.content_text or "")[:_MAX_CONTENT_PER_NOTE]
            parts.append(f"[Note {i}: {note.note_title!r}]\n{content}")
        return "\n\n---\n\n".join(parts)

    async def _call_llm(self, label: str, context: str) -> tuple[dict, str | None]:  # type: ignore[type-arg]
        """Run the grounded-insight prompt.

        Returns ``(parsed_json_or_empty_dict, error_message_or_none)``.
        ``error_message`` is the upstream LLM exception (e.g. "model not
        found") when the call failed, or ``"LLM returned malformed JSON"``
        when the response could not be parsed.
        """
        user_msg = (
            f'Concept to analyse: "{label}"\n\n'
            f"User notes mentioning this concept:\n\n{context}"
        )
        client = AsyncLLMClient(
            api_key=self._api_key,
            model=self._model,
            base_url=self._base_url,
            timeout_s=12.0,
        )
        raw = await client.complete(system=_SYSTEM_PROMPT, user=user_msg, max_tokens=1024)
        if not raw:
            return {}, client.last_error or "LLM returned no response."
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.S).strip()
        try:
            return json.loads(raw), None  # type: ignore[no-any-return]
        except Exception:  # noqa: BLE001
            return {}, "LLM returned malformed JSON."
