"""LLM call failures must surface a useful error message.

Pre-fix, ``AsyncLLMClient.complete`` swallows exceptions and returns ``None``.
Both ``ConceptInsightService`` and ``POST /v1/preferences/test-connection``
treated that as "no response" and produced a misleading UX (frontend told
users to set ``LLM_API_KEY`` in their env even when the real failure was an
invalid model name on a configured cloud key).

These tests pin the new contract:

1. ``AsyncLLMClient.last_error`` is set when the call raises.
2. ``ConceptInsightResponse.insight_error`` carries the error message when
   the LLM call fails, so the panel can render a real reason.
3. ``test-connection`` surfaces the underlying error string (not just
   "no response").
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


# ── 1. AsyncLLMClient exposes last_error ──────────────────────────────────────


def test_async_llm_client_records_last_error_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When openai raises, last_error contains the exception message."""
    import asyncio

    from app.nlp.llm_client import AsyncLLMClient

    class _BoomClient:
        def __init__(self, *_a: object, **_kw: object) -> None:
            self.chat = self

        @property
        def completions(self) -> "_BoomClient":
            return self

        async def create(self, **_kwargs: object) -> object:
            raise RuntimeError("model: claude-3-5-haiku-latest not found")

    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", _BoomClient)

    client = AsyncLLMClient(api_key="x", model="bad-model", base_url="http://x")
    result = asyncio.run(
        client.complete(system="s", user="u", max_tokens=10)
    )
    assert result is None
    assert client.last_error is not None
    assert "claude-3-5-haiku-latest" in client.last_error


def test_async_llm_client_clears_last_error_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On a successful call last_error is cleared (None)."""
    import asyncio

    from app.nlp.llm_client import AsyncLLMClient

    class _Msg:
        content = "ok"

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    class _OkClient:
        def __init__(self, *_a: object, **_kw: object) -> None:
            self.chat = self

        @property
        def completions(self) -> "_OkClient":
            return self

        async def create(self, **_kwargs: object) -> _Resp:
            return _Resp()

    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", _OkClient)

    client = AsyncLLMClient(api_key="x", model="m", base_url="http://x")
    # Pre-populate to verify it gets cleared.
    client.last_error = "stale"
    result = asyncio.run(client.complete(system="s", user="u", max_tokens=10))
    assert result == "ok"
    assert client.last_error is None


# ── 2. ConceptInsightResponse.insight_error ───────────────────────────────────


def test_concept_insight_response_has_insight_error_field() -> None:
    """The contract carries an optional insight_error string."""
    from shared.contracts.python.v1.graph import ConceptInsightResponse

    resp = ConceptInsightResponse(
        concept_label="x",
        notes_found=0,
        note_refs=[],
        insight=None,
        insight_error="LLM call failed: model not found",
        learning_links=[],
        generated_at="2026-05-10T00:00:00Z",
    )
    assert resp.insight_error == "LLM call failed: model not found"


def test_concept_insight_service_propagates_llm_error(
    configured_db: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the LLM call raises, the service populates insight_error."""
    import asyncio

    from app.db.engine import get_session_factory
    from app.db.repositories.note_repository import NoteRepository
    from app.services.concept_insight_service import ConceptInsightService

    session_factory = get_session_factory()
    with session_factory() as session:
        with session.begin():
            NoteRepository(session).upsert_note(
                note_id="n1",
                note_title="n",
                content_json={"type": "doc", "content": []},
                content_text="machine learning is great",
                updated_at="2026-05-10T00:00:00Z",
            )

    async def _boom(self: object, **_kwargs: object) -> None:
        self.last_error = "Error code: 404 - model not found: bad-model"  # type: ignore[attr-defined]
        return None

    monkeypatch.setattr("app.nlp.llm_client.AsyncLLMClient.complete", _boom)

    with session_factory() as session:
        svc = ConceptInsightService(session, graph_name="nn_test")
        svc._api_key = "fake-key"  # force the LLM branch
        res = asyncio.run(svc.get_insight("machine learning"))

    assert res.insight is None
    assert res.insight_error is not None
    assert "404" in res.insight_error or "model not found" in res.insight_error


# ── 3. test-connection surfaces the real error ────────────────────────────────


def test_test_connection_surfaces_underlying_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the LLM raises, /v1/preferences/test-connection returns the cause."""
    client.put("/v1/preferences", json={"llm_api_key": "sk-test-key-1234"})

    async def _boom(self: object, **_kwargs: object) -> None:
        self.last_error = "model: claude-3-5-haiku-latest not found"  # type: ignore[attr-defined]
        return None

    monkeypatch.setattr(
        "app.nlp.llm_client.AsyncLLMClient.complete", _boom
    )
    resp = client.post("/v1/preferences/test-connection")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "claude-3-5-haiku-latest" in body["message"]
