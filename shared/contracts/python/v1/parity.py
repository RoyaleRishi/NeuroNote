from __future__ import annotations

from pydantic import BaseModel, Field


class GraphParityReport(BaseModel):
    """Counts produced by a SQL↔AGE parity operation (inline cleanup or reconcile).

    Every field is a non-negative tally; a fully-converged second reconcile run
    returns all zeros (idempotency contract).
    """

    pruned_note_artifacts: int = Field(default=0, ge=0)
    pruned_concept_nodes: int = Field(default=0, ge=0)
    pruned_subject_nodes: int = Field(default=0, ge=0)
    pruned_registry_rows: int = Field(default=0, ge=0)
    reprocessed_notes: int = Field(default=0, ge=0)
