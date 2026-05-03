from __future__ import annotations

import pytest

from app.core.job_store import (
    create_or_get_job,
    get_job,
    mark_job_completed,
    mark_job_failed,
    mark_job_running,
    reset_job_store,
)


def test_create_or_get_job_coalesces_same_note_version(configured_db: None) -> None:
    reset_job_store()

    first, first_created = create_or_get_job(
        note_id="note-job-1",
        content_hash="hash-job-1",
    )
    second, second_created = create_or_get_job(
        note_id="note-job-1",
        content_hash="hash-job-1",
    )

    assert first_created is True
    assert second_created is False
    assert second.job_id == first.job_id
    assert second.status == "queued"


def test_job_status_transitions_from_running_to_completed(configured_db: None) -> None:
    reset_job_store()
    record, _ = create_or_get_job(note_id="note-job-2", content_hash="hash-job-2")

    mark_job_running(record.job_id)
    running = get_job(record.job_id)
    assert running is not None
    assert running.status == "running"

    mark_job_completed(record.job_id)
    completed = get_job(record.job_id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.error is None


def test_failed_job_allows_new_job_for_same_note_version(configured_db: None) -> None:
    reset_job_store()
    first, _ = create_or_get_job(note_id="note-job-3", content_hash="hash-job-3")
    mark_job_failed(first.job_id, error="failed-run")

    retry, retry_created = create_or_get_job(
        note_id="note-job-3",
        content_hash="hash-job-3",
    )

    assert retry_created is True
    assert retry.job_id != first.job_id
