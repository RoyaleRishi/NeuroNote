from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING

from app.core.backfill_store import (
    BackfillStatusSnapshot,
    set_backfill_status,
)
from app.db.engine import get_session_factory, set_tenant_schema
from app.db.repositories.note_repository import NoteRepository
from app.nlp.pipeline import clear_extraction_cache
from app.services.note_processing_service import NoteNotFoundError, NoteProcessingService
from shared.contracts.python.v1.process import ProcessNoteRequest

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class BackfillRunOptions:
    enabled: bool = True


class StartupBackfillService:
    def __init__(
        self,
        *,
        max_workers: int = 1,
        options: BackfillRunOptions | None = None,
    ) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._options = options or BackfillRunOptions()

    def run_async(self, runner: Callable[[], None]) -> None:
        self._executor.submit(runner)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=False)

    def _filter_stale_notes(
        self,
        session: "Session",
        note_ids: list[str],
        graph_name: str = "neuronote",
    ) -> list[str]:
        """Return only note_ids that have missing or stale Block nodes in AGE.

        Compares each note's relational Block rows against the AGE graph. A note
        is considered stale if any of its blocks are absent from AGE or have a
        differing content_hash (meaning the note was edited since the last sync).

        Falls back to returning all note_ids if AGE is unavailable, so backfill
        remains safe in environments without AGE support.

        Args:
            graph_name: AGE graph to query. Defaults to ``"neuronote"`` (single-tenant).
                Pass a per-tenant graph name (e.g. ``"nn_user_abc123"``) for multi-tenant
                deployments.
        """
        try:
            from sqlalchemy import select as _select

            from app.db.models.block import Block as _Block
            from app.db.repositories.graph_repository import GraphRepository

            repo = GraphRepository(session)
            stale: list[str] = []
            for note_id in note_ids:
                # Fetch {block_uid: content_hash} map from AGE for this note.
                age_states = repo.fetch_block_states(note_id=note_id, graph_name=graph_name)
                # Fetch the authoritative block rows from the relational DB.
                block_rows = session.execute(
                    _select(_Block.block_uid, _Block.content_hash).where(
                        _Block.note_id == note_id
                    )
                ).all()
                # Note is stale when any block is absent or has a hash mismatch.
                if any(age_states.get(str(uid)) != str(chash) for uid, chash in block_rows):
                    stale.append(note_id)
            return stale
        except Exception:
            # AGE unavailable or unexpected error — process all notes to be safe.
            return note_ids

    @staticmethod
    def _list_tenant_schemas() -> list[str]:
        """Return all schema_names from public.users. Falls back to empty list."""
        try:
            from sqlalchemy import text as _text
            session_factory = get_session_factory()
            with session_factory() as session:
                rows = session.execute(
                    _text("SELECT schema_name FROM public.users WHERE schema_name IS NOT NULL ORDER BY schema_name")
                ).all()
            return [row[0] for row in rows]
        except Exception:
            _LOGGER.debug("could not list tenant schemas from public.users", exc_info=True)
            return []

    def run_note_reprocessing_backfill(self, *, force: bool = False) -> None:
        if not self._options.enabled:
            set_backfill_status(
                BackfillStatusSnapshot(
                    total_notes=0,
                    processed_notes=0,
                    failed_notes=0,
                    in_progress=False,
                )
            )
            return

        tenant_schemas = self._list_tenant_schemas()
        if not tenant_schemas:
            # Single-tenant or test environment — operate on default schema.
            tenant_schemas = [None]  # type: ignore[list-item]

        # Build (note_id, schema_name, graph_name) tuples across all tenants.
        work_items: list[tuple[str, str | None, str]] = []
        session_factory = get_session_factory()

        for schema_name in tenant_schemas:
            graph_name = f"nn_{schema_name}" if schema_name else "neuronote"
            set_tenant_schema(schema_name)
            try:
                with session_factory() as session:
                    if force:
                        clear_extraction_cache()
                        try:
                            from sqlalchemy import text as _text
                            session.execute(_text("DELETE FROM nlp_extraction_cache"))
                            session.execute(_text("DELETE FROM concept_insight_cache"))
                            session.execute(_text("DELETE FROM concept_registry"))
                            session.commit()
                            _LOGGER.info(
                                "force reprocess: cleared caches for schema=%s", schema_name or "default"
                            )
                        except Exception:
                            _LOGGER.debug(
                                "force reprocess: cache clear failed for schema=%s",
                                schema_name or "default",
                                exc_info=True,
                            )
                        note_ids = NoteRepository(session).list_note_ids()
                    else:
                        all_ids = NoteRepository(session).list_note_ids()
                        note_ids = self._filter_stale_notes(session, all_ids, graph_name=graph_name)
                work_items.extend((nid, schema_name, graph_name) for nid in note_ids)
            finally:
                set_tenant_schema(None)

        total = len(work_items)
        processed = 0
        failed = 0
        set_backfill_status(
            BackfillStatusSnapshot(
                total_notes=total,
                processed_notes=processed,
                failed_notes=failed,
                in_progress=True,
            )
        )

        for note_id, schema_name, graph_name in work_items:
            service = NoteProcessingService(schema_name=schema_name, graph_name=graph_name)
            try:
                service.process_note(
                    ProcessNoteRequest(
                        note_id=note_id,
                        content_text="backfill",
                        content_hash="backfill",
                        updated_at="backfill",
                    )
                )
            except (NoteNotFoundError, Exception):
                failed += 1
            finally:
                processed += 1
                set_backfill_status(
                    BackfillStatusSnapshot(
                        total_notes=total,
                        processed_notes=processed,
                        failed_notes=failed,
                        in_progress=True,
                    )
                )

        set_backfill_status(
            BackfillStatusSnapshot(
                total_notes=total,
                processed_notes=processed,
                failed_notes=failed,
                in_progress=False,
            )
        )
