from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.backfill_store import BackfillStatusSnapshot, set_backfill_status


def test_reconcile_endpoint_returns_parity_report(client: TestClient) -> None:
    resp = client.post("/v1/graph/reconcile")
    assert resp.status_code == 200
    body = resp.json()
    for key in (
        "pruned_note_artifacts", "pruned_concept_nodes",
        "pruned_subject_nodes", "pruned_registry_rows", "reprocessed_notes",
    ):
        assert key in body and isinstance(body[key], int)


def test_reprocess_all_force_returns_202(client: TestClient) -> None:
    response = client.post("/v1/reprocess-all?force=true")
    assert response.status_code == 202
    body = response.json()
    assert body["in_progress"] is True


def test_backfill_status_endpoint_returns_snapshot(client: TestClient) -> None:
    set_backfill_status(
        BackfillStatusSnapshot(
            total_notes=10,
            processed_notes=4,
            failed_notes=1,
            in_progress=True,
        )
    )

    response = client.get("/v1/backfill-status")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "total_notes": 10,
        "processed_notes": 4,
        "failed_notes": 1,
        "in_progress": True,
    }

