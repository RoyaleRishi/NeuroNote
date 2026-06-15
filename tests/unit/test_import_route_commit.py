"""Tests that the import route commits the note unconditionally.

Both the new-job and existing-job paths must persist the note even when
``create_or_get_job`` does not issue its own commit (existing-job path).
We verify via a mock session that ``session.commit()`` is called before
the job/background block.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _make_saved_note(note_id: str = "note-abc123") -> SimpleNamespace:
    return SimpleNamespace(note_id=note_id, content_hash="hash-abc")


def _make_job_record(job_id: str = "job-1") -> SimpleNamespace:
    return SimpleNamespace(job_id=job_id)


# create_or_get_job is imported *inside* the route function body, so we must
# patch its definition site (app.core.job_store), not the import_ namespace.
_PATCH_REPO = "app.routes.import_.NoteRepository"
_PATCH_JOB = "app.core.job_store.create_or_get_job"


def _run_import(created: bool) -> MagicMock:
    """Call import_note and return the mock session."""
    mock_session = MagicMock()
    mock_repo_instance = MagicMock()
    mock_repo_instance.upsert_note.return_value = _make_saved_note()

    mock_job_record = _make_job_record()
    mock_user = SimpleNamespace(schema_name="user_test1234")

    with (
        patch(_PATCH_REPO, return_value=mock_repo_instance),
        patch(_PATCH_JOB, return_value=(mock_job_record, created)),
    ):
        from app.routes.import_ import import_note
        from shared.contracts.python.v1.import_ import ImportNoteRequest

        payload = ImportNoteRequest(
            filename="test.md",
            content="# Hello\n\nWorld",
            subject_id="inbox",
        )
        import_note(
            payload=payload,
            background_tasks=MagicMock(),
            session=mock_session,
            user=mock_user,
        )

    return mock_session


def test_commit_called_on_new_job_path() -> None:
    """session.commit() is called when a new job is created."""
    mock_session = _run_import(created=True)
    mock_session.commit.assert_called()


def test_commit_called_on_existing_job_path() -> None:
    """session.commit() is called even when an existing job is returned."""
    mock_session = _run_import(created=False)
    mock_session.commit.assert_called()


def test_commit_precedes_job_logic() -> None:
    """commit() is invoked before create_or_get_job."""
    call_order: list[str] = []
    mock_session = MagicMock()
    mock_session.commit.side_effect = lambda: call_order.append("commit")

    mock_repo_instance = MagicMock()
    mock_repo_instance.upsert_note.return_value = _make_saved_note()

    def _record_job(*args: object, **kwargs: object) -> tuple[SimpleNamespace, bool]:
        call_order.append("create_or_get_job")
        return (_make_job_record(), False)

    mock_user = SimpleNamespace(schema_name="user_test1234")

    with (
        patch(_PATCH_REPO, return_value=mock_repo_instance),
        patch(_PATCH_JOB, side_effect=_record_job),
    ):
        from app.routes.import_ import import_note
        from shared.contracts.python.v1.import_ import ImportNoteRequest

        payload = ImportNoteRequest(
            filename="notes.txt",
            content="first line\nsecond line",
            subject_id="inbox",
        )
        import_note(
            payload=payload,
            background_tasks=MagicMock(),
            session=mock_session,
            user=mock_user,
        )

    assert call_order.index("commit") < call_order.index("create_or_get_job"), (
        f"Expected commit before create_or_get_job; got order: {call_order}"
    )
