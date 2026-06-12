"""Thin async LLM client over any OpenAI-compatible endpoint.

``complete()`` returns the response text or ``None`` on any error. Never raises.

When a call fails, the underlying exception's short message is preserved on
``last_error`` so callers can surface a real reason to the user instead of a
generic "no response" message. ``last_error`` is reset to ``None`` at the
start of every call.

The underlying ``openai.AsyncOpenAI`` SDK client (and its httpx connection
pool) is cached per ``(api_key, base_url, timeout_s)`` tuple at module
scope, so repeated requests reuse the existing TCP connections instead of
spinning up a fresh pool each call.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import openai

_LOGGER = logging.getLogger(__name__)
_OPENAI_CLIENT_CACHE: dict[tuple[str, str, float], Any] = {}


def _format_exc(exc: BaseException) -> str:
    """Compact, single-line representation of *exc* suitable for end-user UX."""
    msg = str(exc).strip()
    return msg or exc.__class__.__name__


def reset_client_cache() -> None:
    """Drop every cached ``AsyncOpenAI`` instance — for tests that monkeypatch ``openai``."""
    _OPENAI_CLIENT_CACHE.clear()


def _get_openai_client(api_key: str, base_url: str, timeout_s: float) -> "openai.AsyncOpenAI":
    """Return a cached ``AsyncOpenAI`` for this credential / endpoint pair.

    Misses are racy but idempotent — under concurrency the worst case is two
    short-lived clients created where one wins the cache slot; the other is
    GC'd by the runtime when the request handler returns.
    """
    key = (api_key, base_url, timeout_s)
    cached = _OPENAI_CLIENT_CACHE.get(key)
    if cached is not None:
        return cached
    import openai

    client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout_s)
    _OPENAI_CLIENT_CACHE[key] = client
    return client


class AsyncLLMClient:
    """Async completion via the openai SDK."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout_s: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._timeout_s = timeout_s
        self.last_error: str | None = None

    async def complete(self, *, system: str, user: str, max_tokens: int) -> str | None:
        self.last_error = None
        try:
            client = _get_openai_client(self._api_key, self._base_url, self._timeout_s)
            resp = await client.chat.completions.create(
                model=self._model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return resp.choices[0].message.content
        except Exception as exc:
            self.last_error = _format_exc(exc)
            _LOGGER.debug("AsyncLLMClient.complete failed", exc_info=True)
            return None


__all__ = ["AsyncLLMClient"]
