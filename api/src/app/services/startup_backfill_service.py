from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
import logging
import os
import threading
from typing import TYPE_CHECKING

from app.core.backfill_store import (
    BackfillStatusSnapshot,
    set_backfill_status,
)
from app.db.engine import get_session_factory, set_tenant_schema
from app.db.repositories.note_repository import NoteRepository
from app.nlp.pipeline import clear_extraction_cache
from app.services.graph_reconciliation_service import GraphReconciliationService
from app.services.note_processing_service import NoteNotFoundError, NoteProcessingService
from shared.contracts.python.v1.process import ProcessNoteRequest

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class BackfillRunOptions:
    enabled: bool = True


@dataclass
class _Totals:
    """Thread-safe counters shared between tenant workers.

    All mutations and ``set_backfill_status`` publishes happen under ``lock``
    so concurrent workers can't clobber each other's running totals.
    """

    total: int
    processed: int = 0
    failed: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, *, failed: bool) -> None:
        with self.lock:
            self.processed += 1
            if failed:
                self.failed += 1
            set_backfill_status(
                BackfillStatusSnapshot(
                    total_notes=self.total,
                    processed_notes=self.processed,
                    failed_notes=self.failed,
                    in_progress=True,
                )
            )


def _default_max_workers() -> int:
    """Cap the worker pool at 4 — the semantic embedder is a single shared
    instance and CPU/GIL-bound; more threads only deepen contention."""
    return min(os.cpu_count() or 1, 4)


class StartupBackfillService:
    def __init__(
        self,
        *,
        max_workers: int | None = None,
        options: BackfillRunOptions | None = None,
    ) -> None:
        workers = max_workers if max_workers is not None else _default_max_workers()
        self._executor = ThreadPoolExecutor(max_workers=workers)
        self._options = options or BackfillRunOptions()
        self._max_workers = workers

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

    def _process_tenant(
        self,
        schema_name: str | None,
        note_ids: list[str],
        graph_name: str,
        totals: _Totals,
    ) -> None:
        """Process every note for a single tenant on the calling worker thread.

        Notes within a tenant share AGE graph and concept-registry rows, so we
        keep this loop sequential to avoid MERGE deadlocks and registry races.
        One ``NoteProcessingService`` is reused across all notes so the NLP
        pipeline only initialises once per tenant.

        ``set_tenant_schema`` writes to a ContextVar — in a sync
        ``ThreadPoolExecutor`` each worker thread carries its own context, so
        the binding is isolated to this tenant's thread.
        """
        set_tenant_schema(schema_name)
        try:
            service = NoteProcessingService(schema_name=schema_name, graph_name=graph_name)
            for note_id in note_ids:
                failed = False
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
                    failed = True
                totals.record(failed=failed)
        finally:
            set_tenant_schema(None)

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

        # Per-tenant work map: {schema_name: (graph_name, [note_ids])}.
        # Building this on the orchestrator thread (serially across tenants)
        # avoids interleaving the per-tenant ContextVar bindings during
        # discovery — workers re-set their own schema before processing.
        tenant_work: dict[str | None, tuple[str, list[str]]] = {}
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
                if note_ids:
                    tenant_work[schema_name] = (graph_name, note_ids)
            finally:
                set_tenant_schema(None)

        total = sum(len(ids) for _, ids in tenant_work.values())
        totals = _Totals(total=total)
        set_backfill_status(
            BackfillStatusSnapshot(
                total_notes=total,
                processed_notes=0,
                failed_notes=0,
                in_progress=True,
            )
        )

        if tenant_work:
            # Parallelise ACROSS tenants (disjoint schemas + AGE graphs are
            # safe to write concurrently) but SERIALISE notes within a tenant.
            # A dedicated pool sized to the work bounds thread count
            # independently of the orchestrator's ``_executor``.
            pool_size = min(self._max_workers, len(tenant_work))
            with ThreadPoolExecutor(max_workers=pool_size) as pool:
                futures = [
                    pool.submit(
                        self._process_tenant,
                        schema_name,
                        note_ids,
                        graph_name,
                        totals,
                    )
                    for schema_name, (graph_name, note_ids) in tenant_work.items()
                ]
                for future in as_completed(futures):
                    # Surface unexpected errors but don't let one tenant's
                    # failure abort the others — per-note errors are already
                    # swallowed inside ``_process_tenant``.
                    try:
                        future.result()
                    except Exception:
                        _LOGGER.exception("tenant backfill task crashed")

        with totals.lock:
            set_backfill_status(
                BackfillStatusSnapshot(
                    total_notes=totals.total,
                    processed_notes=totals.processed,
                    failed_notes=totals.failed,
                    in_progress=False,
                )
            )

    def run_graph_reconcile(self) -> None:
        """Reconcile SQL↔AGE graph parity for every tenant on startup.

        Mirrors ``run_note_reprocessing_backfill``'s tenant enumeration: iterates
        all tenant schemas (falling back to the default schema when none exist),
        opens a per-tenant session, and calls ``GraphReconciliationService.reconcile``
        with the live note and subject IDs sourced from the relational DB.  Each
        tenant is isolated in its own try/except so one failure never aborts the
        rest.  Results are logged at INFO so operators can confirm convergence.
        """
        tenant_schemas = self._list_tenant_schemas()
        if not tenant_schemas:
            # Single-tenant or test environment — operate on default schema.
            tenant_schemas = [None]  # type: ignore[list-item]

        session_factory = get_session_factory()

        for schema_name in tenant_schemas:
            graph_name = f"nn_{schema_name}" if schema_name else "neuronote"
            set_tenant_schema(schema_name)
            try:
                with session_factory() as session:
                    repo = NoteRepository(session)
                    live_note_ids = repo.list_note_ids()
                    live_subject_ids = repo.list_live_subject_ids()
                    report = GraphReconciliationService(
                        session=session,
                        graph_name=graph_name,
                    ).reconcile(
                        live_note_ids=live_note_ids,
                        live_subject_ids=live_subject_ids,
                    )
                    # Persist the prune: without this commit the session closes
                    # and rolls back every AGE/registry mutation.
                    session.commit()
                    _LOGGER.info(
                        "graph reconcile schema=%s graph=%s "
                        "pruned_note_artifacts=%d pruned_concept_nodes=%d "
                        "pruned_subject_nodes=%d pruned_registry_rows=%d "
                        "reprocessed_notes=%d",
                        schema_name or "default",
                        graph_name,
                        report.pruned_note_artifacts,
                        report.pruned_concept_nodes,
                        report.pruned_subject_nodes,
                        report.pruned_registry_rows,
                        report.reprocessed_notes,
                    )
            except Exception:
                _LOGGER.exception(
                    "graph reconcile failed for schema=%s", schema_name or "default"
                )
            finally:
                set_tenant_schema(None)
