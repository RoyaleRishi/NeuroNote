from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.backfill_store import (
    BackfillStatusSnapshot,
    set_backfill_status,
)
from app.db.engine import get_session_factory
from app.db.repositories.note_repository import NoteRepository
from shared.contracts.python.v1.process import ProcessNoteRequest

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

    def _filter_stale_notes(self, session: "Session", note_ids: list[str]) -> list[str]:
        """Return only note_ids that have missing or stale Block nodes in AGE.

        Compares each note's relational Block rows against the AGE graph. A note
        is considered stale if any of its blocks are absent from AGE or have a
        differing content_hash (meaning the note was edited since the last sync).

        Falls back to returning all note_ids if AGE is unavailable, so backfill
        remains safe in environments without AGE support.
        """
        try:
            from sqlalchemy import select as _select

            from app.db.models.block import Block as _Block
            from app.db.repositories.graph_repository import GraphRepository

            repo = GraphRepository(session)
            stale: list[str] = []
            for note_id in note_ids:
                # Fetch {block_uid: content_hash} map from AGE for this note.
                age_states = repo.fetch_block_states(note_id=note_id, graph_name="neuronote")
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

    def run_note_reprocessing_backfill(self) -> None:
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

        session_factory = get_session_factory()
        with session_factory() as session:
            all_note_ids = NoteRepository(session).list_note_ids()
            note_ids = self._filter_stale_notes(session, all_note_ids)

        total = len(note_ids)
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

        from app.services.note_processing_service import NoteNotFoundError, NoteProcessingService

        # TODO: Multi-tenant — iterate all user schemas and create a
        # NoteProcessingService per tenant with schema_name + graph_name.
        # Currently operates on the public schema only.
        service = NoteProcessingService()
        for note_id in note_ids:
            try:
                # Payload fields are ignored for persisted snapshot processing.
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
