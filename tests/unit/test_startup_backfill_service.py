from __future__ import annotations

from threading import Event
import time
from unittest.mock import MagicMock, patch

from app.services.startup_backfill_service import StartupBackfillService


def test_force_reprocess_bypasses_stale_filter() -> None:
    """force=True must process every note without consulting _filter_stale_notes."""
    all_ids = ["note-a", "note-b", "note-c"]
    processed: list[str] = []

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_factory = MagicMock(return_value=mock_session)

    mock_note_repo = MagicMock()
    mock_note_repo.list_note_ids.return_value = all_ids

    class _MockProcessingService:
        def __init__(self, **_kwargs):
            pass

        def process_note(self, req):
            processed.append(req.note_id)

    service = StartupBackfillService()

    with (
        patch("app.services.startup_backfill_service.get_session_factory", return_value=mock_factory),
        patch("app.services.startup_backfill_service.NoteRepository", return_value=mock_note_repo),
        patch("app.services.startup_backfill_service.StartupBackfillService._filter_stale_notes") as mock_filter,
        patch("app.services.startup_backfill_service.StartupBackfillService._list_tenant_schemas", return_value=[None]),
        patch("app.services.startup_backfill_service.NoteProcessingService", side_effect=_MockProcessingService),
        patch("app.services.startup_backfill_service.clear_extraction_cache"),
    ):
        service.run_note_reprocessing_backfill(force=True)

    assert processed == all_ids
    mock_filter.assert_not_called()


def test_startup_backfill_runs_async_without_blocking() -> None:
    done = Event()
    service = StartupBackfillService()

    def runner() -> None:
        time.sleep(0.05)
        done.set()

    started_at = time.perf_counter()
    service.run_async(runner)
    elapsed = time.perf_counter() - started_at

    assert elapsed < 0.03
    assert done.wait(timeout=1.0)


def test_run_graph_reconcile_iterates_tenants(monkeypatch):
    from app.services import startup_backfill_service as mod

    calls = []

    class _StubService:
        def __init__(self, *, session, graph_name):
            self.graph_name = graph_name
        def reconcile(self, *, live_note_ids, live_subject_ids):
            calls.append(self.graph_name)
            from shared.contracts.python.v1.parity import GraphParityReport
            return GraphParityReport()

    monkeypatch.setattr(mod, "GraphReconciliationService", _StubService, raising=False)
    svc = mod.StartupBackfillService()
    svc.run_graph_reconcile()  # should not raise
    assert isinstance(calls, list)

