"""Regression: literal % in user content must not trip psycopg placeholder parsing."""
from __future__ import annotations

from typing import Any

from app.db.repositories.graph_repository import GraphRepository


class _FakeResult:
    def all(self) -> list:
        return []


class _FakeConn:
    def __init__(self) -> None:
        self.last_sql: str | None = None

    def exec_driver_sql(self, sql: str, params: Any) -> _FakeResult:
        self.last_sql = sql
        return _FakeResult()


class _FakeSession:
    def __init__(self) -> None:
        self._conn = _FakeConn()

    def connection(self) -> _FakeConn:
        return self._conn


def test_exec_cypher_escapes_percent_in_query() -> None:
    session = _FakeSession()
    repo = GraphRepository(session)  # type: ignore[arg-type]

    query = 'MERGE (n:Block {id: "x", text: "25% tuition"}) RETURN n'
    repo._exec_cypher("nn_test", query)

    sent = session._conn.last_sql or ""
    assert "%%" in sent, f"expected percent to be doubled in {sent!r}"
    assert "25% tuition" not in sent, "raw single % must be escaped"
