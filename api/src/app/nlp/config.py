from __future__ import annotations

import logging
from dataclasses import dataclass, replace as _dataclass_replace
import os

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

_LOG = logging.getLogger(__name__)


def _as_bool(raw_value: str | None, *, default: bool) -> bool:
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    return normalized in {"1", "true", "yes", "on"}


def _as_int(raw_value: str | None, *, default: int) -> int:
    if raw_value is None:
        return default
    return int(raw_value)


def _as_float(raw_value: str | None, *, default: float) -> float:
    if raw_value is None:
        return default
    return float(raw_value)


@dataclass(frozen=True, slots=True)
class NlpSettings:
    enable_embeddings: bool
    process_min_text_len: int
    timeout_ms: int
    # LLM-enhanced profile settings
    llm_model: str = "claude-haiku-4-5-20251001"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.anthropic.com/v1/"
    llm_timeout_ms: int = 8000
    use_semantic_embeddings: bool = False
    # Deterministic concept-extraction tuning.
    enable_yake_fallback: bool = False
    salience_threshold_delta: float = 0.30
    salience_redundancy_threshold: float = 0.86


def get_nlp_settings() -> NlpSettings:
    return NlpSettings(
        enable_embeddings=_as_bool(os.getenv("NLP_ENABLE_EMBEDDINGS"), default=True),
        process_min_text_len=_as_int(os.getenv("NLP_PROCESS_MIN_TEXT_LEN"), default=3),
        timeout_ms=_as_int(os.getenv("NLP_TIMEOUT_MS"), default=2000),
        llm_model=os.getenv("NLP_LLM_MODEL", "claude-haiku-4-5-20251001"),
        llm_api_key=os.getenv("LLM_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or "",
        llm_base_url=os.getenv("LLM_BASE_URL", "https://api.anthropic.com/v1/"),
        llm_timeout_ms=_as_int(os.getenv("NLP_LLM_TIMEOUT_MS"), default=8000),
        use_semantic_embeddings=_as_bool(
            os.getenv("NLP_USE_SEMANTIC_EMBEDDINGS"), default=False
        ),
        enable_yake_fallback=_as_bool(
            os.getenv("NLP_ENABLE_YAKE_FALLBACK"), default=False
        ),
        salience_threshold_delta=_as_float(
            os.getenv("NLP_SALIENCE_THRESHOLD_DELTA"), default=0.30
        ),
        salience_redundancy_threshold=_as_float(
            os.getenv("NLP_SALIENCE_REDUNDANCY_THRESHOLD"), default=0.86
        ),
    )


def resolve_user_llm_settings(session: Session) -> NlpSettings | None:
    """Return cloud-mode NlpSettings from ``user_preferences`` or None.

    Reads the tenant's stored LLM preferences via the caller's session, decrypts
    the API key, and produces an overridden ``NlpSettings``. Returns None when
    the user is on edge mode, has no API key, or the stored key cannot be
    decrypted — callers fall back to server defaults in that case.
    """
    from app.core.crypto import decrypt_api_key, InvalidToken

    rows = session.execute(
        sa_text("SELECT key, value FROM user_preferences")
    ).all()
    prefs = {str(r[0]): str(r[1]) for r in rows}
    if prefs.get("llm_mode") != "cloud" or not prefs.get("llm_api_key"):
        return None

    try:
        api_key = decrypt_api_key(prefs["llm_api_key"])
    except InvalidToken:
        _LOG.warning(
            "llm_api_key could not be decrypted (wrong key or plaintext); skipping cloud mode."
        )
        return None

    if not api_key:
        return None

    base = get_nlp_settings()
    user_base_url = prefs.get("llm_base_url", base.llm_base_url)

    # Validate the user-supplied base URL before using it for outbound calls.
    # On failure, log a warning and fall back to None (env-default settings).
    from app.core.url_guard import validate_outbound_url

    try:
        validate_outbound_url(user_base_url)
    except ValueError as exc:
        _LOG.warning(
            "Skipping cloud mode: stored llm_base_url is unsafe: %s", exc
        )
        return None

    return _dataclass_replace(
        base,
        llm_api_key=api_key,
        llm_base_url=user_base_url,
        llm_model=prefs.get("llm_model", base.llm_model),
    )


__all__ = ["NlpSettings", "get_nlp_settings", "resolve_user_llm_settings"]
