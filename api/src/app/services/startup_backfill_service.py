from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from app.core.backfill_store import (
    BackfillStatusSnapshot,
    set_backfill_status,
)
from app.db.engine import get_session_factory
from app.db.repositories.note_repository import NoteRepository
from shared.contracts.python.v1.process import ProcessNoteRequest


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
            note_ids = NoteRepository(session).list_note_ids()

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
