"""User preferences routes — GET/PUT for per-user settings + LLM test-connection."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_api_key, encrypt_api_key
from app.db.tenant_session import get_tenant_session
from shared.contracts.python.v1.preferences import (
    TestConnectionResponse,
    UpdatePreferencesRequest,
    UserPreferences,
)

router = APIRouter()
_LOG = logging.getLogger(__name__)

# Default values for each preference key.
_DEFAULTS: dict[str, str] = {
    "llm_mode": "edge",
    "llm_api_key": "",
    "llm_base_url": "https://api.openai.com/v1",
    "llm_model": "gpt-4o-mini",
    "confidence_threshold": "0.9",
}


def _load_preferences(session: Session) -> dict[str, str]:
    """Load all preference rows, merge with defaults, and decrypt llm_api_key."""
    rows = session.execute(
        text("SELECT key, value FROM user_preferences")
    ).all()
    stored = {str(row[0]): str(row[1]) for row in rows}
    prefs = {**_DEFAULTS, **stored}
    if prefs.get("llm_api_key"):
        prefs["llm_api_key"] = decrypt_api_key(prefs["llm_api_key"])
    return prefs


@router.get("/preferences", response_model=UserPreferences)
def get_preferences(
    session: Session = Depends(get_tenant_session),
) -> UserPreferences:
    """Return all user preferences with defaults for unset keys."""
    prefs = _load_preferences(session)
    # Mask the API key — only show last 4 chars.
    api_key = prefs.get("llm_api_key", "")
    if len(api_key) > 4:
        prefs["llm_api_key"] = "****" + api_key[-4:]
    return UserPreferences(**prefs)


@router.put("/preferences", response_model=UserPreferences)
def update_preferences(
    payload: UpdatePreferencesRequest,
    session: Session = Depends(get_tenant_session),
) -> UserPreferences:
    """Partial update — only provided (non-None) fields are written."""
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        return get_preferences(session)

    # Load current state before writes so we can merge for the response.
    prefs = _load_preferences(session)
    for key, value in updates.items():
        stored_value = encrypt_api_key(value) if key == "llm_api_key" else value
        session.execute(
            text(
                "INSERT INTO user_preferences (key, value, updated_at) "
                "VALUES (:key, :value, CURRENT_TIMESTAMP) "
                "ON CONFLICT (key) DO UPDATE SET value = :value, updated_at = CURRENT_TIMESTAMP"
            ),
            {"key": key, "value": stored_value},
        )
        prefs[key] = value  # keep plaintext in-memory for the response
    session.commit()

    # Mask API key in response (use in-memory prefs, not a second DB read).
    api_key = prefs.get("llm_api_key", "")
    if len(api_key) > 4:
        prefs["llm_api_key"] = "****" + api_key[-4:]
    return UserPreferences(**prefs)


@router.post("/preferences/test-connection", response_model=TestConnectionResponse)
async def test_connection(
    session: Session = Depends(get_tenant_session),
) -> TestConnectionResponse:
    """Test the user's cloud LLM configuration by sending a simple prompt.

    Reads ``llm_api_key``, ``llm_base_url``, and ``llm_model`` from
    the user's stored preferences and attempts a short completion call.
    Returns success/failure so the UI can validate credentials before saving.
    """
    prefs = _load_preferences(session)

    api_key = prefs.get("llm_api_key", "")
    if not api_key:
        return TestConnectionResponse(
            success=False,
            message="No API key configured. Save an API key in preferences first.",
        )

    base_url = prefs.get("llm_base_url", "https://api.openai.com/v1")
    model = prefs.get("llm_model", "gpt-4o-mini")

    from app.nlp.llm_client import AsyncLLMClient

    client = AsyncLLMClient(
        api_key=api_key,
        model=model,
        base_url=base_url,
        timeout_s=10.0,
    )
    try:
        result = await client.complete(
            system="You are a helpful assistant.",
            user="Say hello in one sentence.",
            max_tokens=32,
        )
    except Exception as exc:
        _LOG.debug("test-connection failed: %s", exc, exc_info=True)
        return TestConnectionResponse(
            success=False,
            message=f"Connection failed: {exc}",
        )

    if result is None:
        return TestConnectionResponse(
            success=False,
            message="LLM returned no response. Check your API key, base URL, and model name.",
        )
    return TestConnectionResponse(
        success=True,
        message="Connection successful.",
    )
