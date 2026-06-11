"""Thin async LLM client over any OpenAI-compatible endpoint.

``complete()`` returns the response text or ``None`` on any error. Never raises.

When a call fails, the underlying exception's short message is preserved on
``last_error`` so callers can surface a real reason to the user instead of a
generic "no response" message. ``last_error`` is reset to ``None`` at the
start of every call.
"""
from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)


def _format_exc(exc: BaseException) -> str:
    """Compact, single-line representation of *exc* suitable for end-user UX."""
    msg = str(exc).strip()
    return msg or exc.__class__.__name__


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
            import openai

            client = openai.AsyncOpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=self._timeout_s,
            )
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
