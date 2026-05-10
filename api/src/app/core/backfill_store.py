from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from threading import Lock

# Written to /tmp so all Uvicorn worker processes in the same container see
# the same state. A threading lock guards within-process concurrent writes;
# the file itself is our cross-process channel.
_STATUS_FILE = "/tmp/neuronote_backfill_status.json"
_LOCK = Lock()


@dataclass(frozen=True, slots=True)
class BackfillStatusSnapshot:
    total_notes: int
    processed_notes: int
    failed_notes: int
    in_progress: bool




def reset_backfill_status() -> None:
    set_backfill_status(
        BackfillStatusSnapshot(
            total_notes=0,
            processed_notes=0,
            failed_notes=0,
            in_progress=False,
        )
    )


def get_backfill_status() -> BackfillStatusSnapshot:
    with _LOCK:
        try:
            with open(_STATUS_FILE) as f:
                data = json.load(f)
            return BackfillStatusSnapshot(**data)
        except Exception:
            return BackfillStatusSnapshot(
                total_notes=0,
                processed_notes=0,
                failed_notes=0,
                in_progress=False,
            )


def set_backfill_status(snapshot: BackfillStatusSnapshot) -> None:
    with _LOCK:
        try:
            with open(_STATUS_FILE, "w") as f:
                json.dump(asdict(snapshot), f)
        except Exception:
            pass
