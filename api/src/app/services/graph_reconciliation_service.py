from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.db.repositories.graph_repository import GraphRepository
from app.nlp.concept_registry import prune_orphan_registry_rows, prune_registry_rows
from shared.contracts.python.v1.parity import GraphParityReport

_LOG = logging.getLogger(__name__)


class GraphReconciliationService:
    """Maintains SQL→AGE parity: prunes graph artifacts whose SQL source is gone.

    Two entry points share one orphan sweep:
      * ``delete_note_graph`` — inline, transactional cleanup for a single note.
      * ``reconcile`` (added later) — backstop that reverse-prunes whole-tenant drift.
    """

    def __init__(
        self,
        *,
        session: Session,
        graph_name: str,
        repository: GraphRepository | None = None,
    ) -> None:
        self._session = session
        self._graph_name = graph_name
        self._repository = repository or GraphRepository(session)

    def sweep_orphans(self, *, live_subject_ids: list[str]) -> tuple[int, int, int]:
        """Delete orphaned Entity/Concept + Subject nodes and their registry rows.

        Returns (pruned_concept_nodes, pruned_subject_nodes, pruned_registry_rows).
        Idempotent: a converged graph yields (0, 0, 0).
        """
        orphan_ids = self._repository.delete_orphan_concept_nodes(graph_name=self._graph_name)
        pruned_subjects = self._repository.delete_orphan_subjects(
            live_subject_ids=live_subject_ids, graph_name=self._graph_name
        )
        pruned_registry = prune_registry_rows(self._session, orphan_ids)
        self._repository.delete_dangling_edges(graph_name=self._graph_name)
        return len(orphan_ids), len(pruned_subjects), pruned_registry

    def reconcile(
        self, *, live_note_ids: list[str], live_subject_ids: list[str]
    ) -> GraphParityReport:
        """Backstop: make AGE match SQL by reverse-pruning stale artifacts.

        Idempotent — a converged tenant yields an all-zero report.
        """
        live_notes = set(live_note_ids)
        age_note_ids = self._repository.fetch_age_note_ids(graph_name=self._graph_name)
        stale = [nid for nid in age_note_ids if nid not in live_notes]
        for nid in stale:
            self._repository.delete_source_artifacts(
                source_note_id=nid, graph_name=self._graph_name
            )

        concepts, subjects, registry = self.sweep_orphans(live_subject_ids=live_subject_ids)

        # Catch-all: registry rows whose entity_id no longer maps to a live mention
        # (drift where the graph node was already gone). concept_registry is a
        # PostgreSQL-only per-tenant table (absent in the SQLite test fallback), so
        # this catch-all SELECT only runs on PostgreSQL. Errors there propagate so
        # the per-tenant reconcile transaction rolls back atomically.
        bind = self._session.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            live_ids = self._repository.fetch_live_mentioned_ids(graph_name=self._graph_name)
            registry += prune_orphan_registry_rows(self._session, live_ids)

        return GraphParityReport(
            pruned_note_artifacts=len(stale),
            pruned_concept_nodes=concepts,
            pruned_subject_nodes=subjects,
            pruned_registry_rows=registry,
        )

    def delete_note_graph(
        self, *, note_id: str, live_subject_ids: list[str]
    ) -> GraphParityReport:
        """Remove a deleted note's AGE artifacts + any now-orphaned shared nodes.

        Runs on the caller's session/transaction so it commits atomically with the
        SQL row delete.
        """
        self._repository.delete_source_artifacts(
            source_note_id=note_id, graph_name=self._graph_name
        )
        concepts, subjects, registry = self.sweep_orphans(live_subject_ids=live_subject_ids)
        return GraphParityReport(
            pruned_note_artifacts=1,
            pruned_concept_nodes=concepts,
            pruned_subject_nodes=subjects,
            pruned_registry_rows=registry,
        )
