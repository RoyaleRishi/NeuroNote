from __future__ import annotations

from app.db.engine import get_session_factory
from app.db.repositories.note_repository import NoteRepository
from app.services.local_graph_service import LocalGraphQuery, LocalGraphService


def _save_note(
    *,
    note_id: str,
    note_title: str,
    content_text: str,
    updated_at: str,
) -> None:
    factory = get_session_factory()
    with factory() as session:
        with session.begin():
            NoteRepository(session).upsert_note(
                note_id=note_id,
                note_title=note_title,
                content_json={"type": "doc", "content": []},
                content_text=content_text,
                updated_at=updated_at,
            )


def test_local_graph_service_includes_second_hop_note_links(configured_db: None) -> None:
    _save_note(
        note_id="graph-hop-root",
        note_title="Hop Root",
        content_text="See [[Hop A]]",
        updated_at="2026-03-15T16:20:00Z",
    )
    _save_note(
        note_id="graph-hop-a",
        note_title="Hop A",
        content_text="See [[Hop B]]",
        updated_at="2026-03-15T16:21:00Z",
    )
    _save_note(
        note_id="graph-hop-b",
        note_title="Hop B",
        content_text="Final",
        updated_at="2026-03-15T16:22:00Z",
    )

    factory = get_session_factory()
    with factory() as session:
        response = LocalGraphService(session).get_local_graph(
            LocalGraphQuery(
                note_id="graph-hop-root",
                max_hops=2,
                limit_nodes=80,
                min_confidence=0.0,
                include_types=["note", "relation"],
            )
        )

    node_ids = {node.id for node in response.nodes}
    assert {"graph-hop-root", "graph-hop-a", "graph-hop-b"}.issubset(node_ids)

    edge_triples = {(edge.source, edge.target, edge.type) for edge in response.edges}
    assert ("graph-hop-root", "graph-hop-a", "LINKS_TO") in edge_triples
    assert ("graph-hop-a", "graph-hop-b", "LINKS_TO") in edge_triples


def test_local_graph_service_filters_to_note_type_only(configured_db: None) -> None:
    _save_note(
        note_id="graph-note-only-root",
        note_title="Graph Note Only",
        content_text="Machine Learning and [[Graph Note Neighbor]]",
        updated_at="2026-03-15T16:30:00Z",
    )
    _save_note(
        note_id="graph-note-neighbor",
        note_title="Graph Note Neighbor",
        content_text="Neighbor",
        updated_at="2026-03-15T16:31:00Z",
    )

    factory = get_session_factory()
    with factory() as session:
        response = LocalGraphService(session).get_local_graph(
            LocalGraphQuery(
                note_id="graph-note-only-root",
                max_hops=1,
                limit_nodes=80,
                min_confidence=0.0,
                include_types=["note", "relation"],
            )
        )

    assert response.nodes
    assert all(node.type == "note" for node in response.nodes)
    assert all(edge.type == "LINKS_TO" for edge in response.edges)


def test_local_graph_service_returns_note_node_for_isolated_note(
    configured_db: None,
) -> None:
    """Root note must appear as a note node even when it has no wiki-links."""
    _save_note(
        note_id="graph-isolated-root",
        note_title="Isolated Root",
        content_text="entity resolution improves graph reasoning for note linking",
        updated_at="2026-03-15T16:45:00Z",
    )

    factory = get_session_factory()
    with factory() as session:
        response = LocalGraphService(session).get_local_graph(
            LocalGraphQuery(
                note_id="graph-isolated-root",
                max_hops=1,
                limit_nodes=80,
                min_confidence=0.35,
                include_types=["note", "relation"],
            )
        )

    note_nodes = [node for node in response.nodes if node.type == "note"]
    assert note_nodes, "Expected at least the root note node"
    assert note_nodes[0].id == "graph-isolated-root"


def test_local_graph_service_traverses_wiki_links_and_builds_links_to_edges(
    configured_db: None,
) -> None:
    """Wiki-link traversal and LINKS_TO edge building are SQL-only and work on any DB.

    Entity filtering (noise suppression) is covered by AGE integration tests; here
    we only verify that linked notes are included and LINKS_TO edges are produced.
    """
    _save_note(
        note_id="graph-noise-root",
        note_title="Graph Noise Root",
        content_text="Machine Learning links to [[Graph Noise Neighbor]]",
        updated_at="2026-03-29T12:10:00Z",
    )
    _save_note(
        note_id="graph-noise-neighbor",
        note_title="Graph Noise Neighbor",
        content_text="Neighbor body",
        updated_at="2026-03-29T12:11:00Z",
    )

    factory = get_session_factory()
    with factory() as session:
        response = LocalGraphService(session).get_local_graph(
            LocalGraphQuery(
                note_id="graph-noise-root",
                max_hops=1,
                limit_nodes=80,
                min_confidence=0.0,
                include_types=["note", "relation"],
            )
        )

    note_ids = {node.id for node in response.nodes if node.type == "note"}
    assert "graph-noise-root" in note_ids
    assert "graph-noise-neighbor" in note_ids
    edge_triples = {(edge.source, edge.target, edge.type) for edge in response.edges}
    assert ("graph-noise-root", "graph-noise-neighbor", "LINKS_TO") in edge_triples
