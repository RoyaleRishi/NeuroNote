from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.contracts.python.v1.process import (
    ProcessNoteRequest,
    ProcessNoteResponse,
    ProcessStatusResponse,
)

ROOT = Path(__file__).resolve().parents[2]


def test_process_note_request_accepts_valid_payload() -> None:
    payload = ProcessNoteRequest(
        note_id="note-1",
        content_text="Graph databases are useful for connected data.",
        content_hash="abc123",
        updated_at="2026-03-01T10:00:00Z",
    )
    assert payload.note_id == "note-1"


def test_process_note_request_rejects_missing_field() -> None:
    with pytest.raises(ValidationError):
        ProcessNoteRequest(
            note_id="note-1",
            content_text="text",
            updated_at="2026-03-01T10:00:00Z",
        )


def test_process_response_shape() -> None:
    response = ProcessNoteResponse(job_id="job-1", status="queued")
    assert response.status == "queued"


@pytest.mark.parametrize("status", ["queued", "running", "completed", "failed"])
def test_status_response_accepts_all_status_values(status: str) -> None:
    result = ProcessStatusResponse(
        job_id="job-1",
        status=status,
        created_at="2026-03-01T10:00:00Z",
        updated_at="2026-03-01T10:00:00Z",
        error=None,
    )
    assert result.status == status


def test_ts_contract_contains_required_fields() -> None:
    ts_contract = (ROOT / "shared/contracts/ts/v1/process.ts").read_text()

    required_tokens = [
        "interface ProcessNoteRequest",
        "note_id: string",
        "content_text: string",
        "content_hash: string",
        "updated_at: string",
        "interface ProcessNoteResponse",
        "status: \"queued\"",
        "interface ProcessStatusResponse",
        "created_at: string",
        "error: string | null",
    ]

    for token in required_tokens:
        assert token in ts_contract, f"Missing token in TS contract: {token}"
