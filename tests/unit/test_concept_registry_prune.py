from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.nlp.concept_registry import prune_registry_rows, prune_orphan_registry_rows


def _session_with_registry() -> Session:
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE concept_registry (concept_text TEXT PRIMARY KEY, entity_id TEXT)"))
        conn.execute(text("INSERT INTO concept_registry VALUES ('keep','id-keep'),('gone','id-gone'),('also','id-also')"))
    return Session(engine)


def test_prune_registry_rows_deletes_only_named_ids():
    session = _session_with_registry()
    deleted = prune_registry_rows(session, ["id-gone", "id-also"])
    session.commit()
    assert deleted == 2
    rows = {r[0] for r in session.execute(text("SELECT entity_id FROM concept_registry")).all()}
    assert rows == {"id-keep"}


def test_prune_registry_rows_noop_on_empty_list():
    session = _session_with_registry()
    assert prune_registry_rows(session, []) == 0


def test_prune_orphan_registry_rows_keeps_only_live_ids():
    session = _session_with_registry()
    deleted = prune_orphan_registry_rows(session, {"id-keep"})
    session.commit()
    assert deleted == 2
    rows = {r[0] for r in session.execute(text("SELECT entity_id FROM concept_registry")).all()}
    assert rows == {"id-keep"}
