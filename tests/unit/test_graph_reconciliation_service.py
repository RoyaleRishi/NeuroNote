from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.services.graph_reconciliation_service import GraphReconciliationService


class _FakeRepo:
    def __init__(self, _session):
        self.deleted_sources: list[str] = []
        self._orphan_ids = ["id-gone"]

    def delete_source_artifacts(self, *, source_note_id, graph_name):
        self.deleted_sources.append(source_note_id)

    def delete_orphan_concept_nodes(self, *, graph_name):
        return list(self._orphan_ids)

    def delete_orphan_subjects(self, *, live_subject_ids, graph_name):
        return []

    def delete_dangling_edges(self, *, graph_name):
        return None


def _session() -> Session:
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE concept_registry (concept_text TEXT PRIMARY KEY, entity_id TEXT)"))
        conn.execute(text("INSERT INTO concept_registry VALUES ('gone','id-gone'),('keep','id-keep')"))
    return Session(engine)


def test_delete_note_graph_prunes_source_then_orphans_and_registry():
    session = _session()
    repo = _FakeRepo(session)
    service = GraphReconciliationService(session=session, graph_name="nn_x", repository=repo)

    report = service.delete_note_graph(note_id="n1", live_subject_ids=["s1"])

    assert repo.deleted_sources == ["n1"]
    assert report.pruned_note_artifacts == 1
    assert report.pruned_concept_nodes == 1
    assert report.pruned_registry_rows == 1
    remaining = {r[0] for r in session.execute(text("SELECT entity_id FROM concept_registry")).all()}
    assert remaining == {"id-keep"}
