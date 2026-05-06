"""One-shot backfill: re-run NLP extraction + graph sync over every note in a tenant schema.

Existing notes processed under the old (rule/spaCy/SLM) pipeline have stale
graph nodes and edges. This script walks the tenant's ``notes`` table and
calls ``NoteProcessingService.process_note`` for each row, which re-runs the
new deterministic pipeline (transformer + YAKE -> normalisation -> structural
relations) and replays graph sync via the standard delete-and-replace path.

Usage:

    uv run python -m app.scripts.reextract_all_notes --schema user_xxxx

The script is intentionally not auto-invoked anywhere; operators run it
explicitly per-tenant after deploying the deterministic pipeline.
"""
from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import select

from app.db.engine import get_session_factory, set_tenant_schema
from app.db.models.note import Note
from app.db.tenant import validate_schema_name
from app.services.note_processing_service import (
    NoteNotFoundError,
    NoteProcessingService,
)
from shared.contracts.python.v1.process import ProcessNoteRequest

_LOGGER = logging.getLogger("app.scripts.reextract_all_notes")
_PROGRESS_EVERY = 25


def _list_notes(schema_name: str) -> list[tuple[str, str, str, str]]:
    """Return (note_id, content_text, content_hash, updated_at) for every note."""
    session_factory = get_session_factory()
    set_tenant_schema(schema_name)
    try:
        with session_factory() as session:
            rows = session.execute(
                select(
                    Note.note_id,
                    Note.content_text,
                    Note.content_hash,
                    Note.updated_at,
                )
            ).all()
            return [(r[0], r[1], r[2], r[3]) for r in rows]
    finally:
        set_tenant_schema(None)


def reextract_all(schema_name: str) -> tuple[int, int]:
    """Re-run extraction for every note in *schema_name*.

    Returns ``(processed, failed)``.
    """
    validate_schema_name(schema_name)
    notes = _list_notes(schema_name)
    total = len(notes)
    _LOGGER.info("Re-extracting %d notes in schema %s", total, schema_name)

    service = NoteProcessingService(schema_name=schema_name)
    processed = 0
    failed = 0
    for index, (note_id, content_text, content_hash, updated_at) in enumerate(notes, start=1):
        try:
            payload = ProcessNoteRequest(
                note_id=note_id,
                content_text=content_text or " ",  # contract requires min_length=1
                content_hash=content_hash,
                updated_at=updated_at,
            )
            service.process_note(payload)
            processed += 1
        except NoteNotFoundError:
            # Note was deleted between listing and processing — skip.
            failed += 1
            _LOGGER.warning("Note %s disappeared during backfill", note_id)
        except Exception as exc:  # pragma: no cover - defensive
            failed += 1
            _LOGGER.exception("Failed to re-extract note %s: %s", note_id, exc)

        if index % _PROGRESS_EVERY == 0 or index == total:
            _LOGGER.info(
                "Progress: %d/%d (%d ok, %d failed)",
                index, total, processed, failed,
            )
    return processed, failed


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--schema",
        required=True,
        help="Tenant schema name, e.g. user_abcd1234",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    processed, failed = reextract_all(args.schema)
    _LOGGER.info("Done. processed=%d failed=%d", processed, failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
