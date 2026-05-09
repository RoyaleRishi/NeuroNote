"""One-shot data migration: purge legacy LLM-era AGE edges.

Deletes concept→concept edges of types CAUSES, IS_A, RELATED_TO, USES,
BELONGS_TO, APPEARS_IN, PART_OF, CONTRASTS_WITH from every tenant graph.
These edges were emitted by the pre-refactor LLM pipeline. They have no
``source_note_id``, so per-note delete-and-replace sync never removes
them — they're stuck unless explicitly purged.

Idempotent: re-running deletes nothing (counts go to 0).

Usage:
    docker compose -f infra/docker-compose.yml exec -T api \\
        uv run --project api python -m app.scripts.purge_legacy_relations
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from app.db.engine import bind_session_to_tenant, get_session_factory

LEGACY_EDGE_TYPES: list[str] = [
    "CAUSES", "IS_A", "RELATED_TO", "USES",
    "BELONGS_TO", "APPEARS_IN", "PART_OF", "CONTRASTS_WITH",
]

_LOG = logging.getLogger(__name__)


def _prepare_age_session(session) -> None:
    """Load AGE and set the search_path so cypher() resolves.

    Must run inside every session before any ag_catalog.cypher call —
    LOAD is per-connection state and ``cypher`` is unqualified inside
    the $$...$$ block, so the search_path must include ag_catalog.
    """
    session.execute(text("LOAD 'age'"))
    session.execute(text('SET search_path = ag_catalog, "$user", public'))


def _purge_for_tenant(schema_name: str) -> dict[str, int]:
    """Run the purge against one tenant graph; return {edge_type: deleted_count}."""
    graph_name = f"nn_{schema_name}"
    factory = get_session_factory()
    types_literal = ", ".join(f"'{t}'" for t in LEGACY_EDGE_TYPES)
    counts: dict[str, int] = {}

    # First: pre-purge tally (per type) for the comparison check.
    with factory() as session:
        bind_session_to_tenant(session, schema_name)
        _prepare_age_session(session)
        for edge_type in LEGACY_EDGE_TYPES:
            sql = (
                "SELECT * FROM ag_catalog.cypher("
                f"'{graph_name}', "
                f"$$ MATCH ()-[r:{edge_type}]->() RETURN count(r) $$"
                ") AS (n ag_catalog.agtype)"
            )
            row = session.connection().exec_driver_sql(sql, None).first()
            counts[edge_type] = int(str(row[0])) if row and row[0] is not None else 0

    pre_total = sum(counts.values())
    _LOG.info("tenant=%s pre-purge counts=%s total=%d", schema_name, counts, pre_total)

    # Then: delete.
    with factory() as session:
        bind_session_to_tenant(session, schema_name)
        _prepare_age_session(session)
        sql = (
            "SELECT * FROM ag_catalog.cypher("
            f"'{graph_name}', "
            f"$$ MATCH ()-[r]->() WHERE type(r) IN [{types_literal}] DELETE r $$"
            ") AS (v ag_catalog.agtype)"
        )
        session.connection().exec_driver_sql(sql, None).all()
        session.commit()

    # Verify post-purge: every type should report 0.
    with factory() as session:
        bind_session_to_tenant(session, schema_name)
        _prepare_age_session(session)
        for edge_type in LEGACY_EDGE_TYPES:
            sql = (
                "SELECT * FROM ag_catalog.cypher("
                f"'{graph_name}', "
                f"$$ MATCH ()-[r:{edge_type}]->() RETURN count(r) $$"
                ") AS (n ag_catalog.agtype)"
            )
            row = session.connection().exec_driver_sql(sql, None).first()
            remaining = int(str(row[0])) if row and row[0] is not None else 0
            assert remaining == 0, (
                f"tenant {schema_name} still has {remaining} {edge_type} edges after purge"
            )

    _LOG.info("tenant=%s purge complete; deleted=%d", schema_name, pre_total)
    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    factory = get_session_factory()
    with factory() as session:
        rows = session.execute(text("SELECT schema_name FROM public.users")).all()

    grand_total = 0
    for (schema_name,) in rows:
        try:
            counts = _purge_for_tenant(schema_name)
        except Exception:  # noqa: BLE001
            _LOG.exception("purge failed for tenant %s", schema_name)
            raise
        grand_total += sum(counts.values())

    _LOG.info("All tenants done. Total legacy edges deleted: %d", grand_total)


if __name__ == "__main__":
    main()
