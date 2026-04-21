"""User preferences routes — GET/PUT for per-user settings."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.tenant_session import get_tenant_session
from shared.contracts.python.v1.preferences import (
    UpdatePreferencesRequest,
    UserPreferences,
)

router = APIRouter()

# Default values for each preference key.
_DEFAULTS: dict[str, str] = {
    "llm_mode": "edge",
    "llm_api_key": "",
    "llm_base_url": "https://api.openai.com/v1",
    "llm_model": "gpt-4o-mini",
}


def _load_preferences(session: Session) -> dict[str, str]:
    """Load all preference rows and merge with defaults."""
    rows = session.execute(
        text("SELECT key, value FROM user_preferences")
    ).all()
    stored = {str(row[0]): str(row[1]) for row in rows}
    return {**_DEFAULTS, **stored}


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
        session.execute(
            text(
                "INSERT INTO user_preferences (key, value, updated_at) "
                "VALUES (:key, :value, CURRENT_TIMESTAMP) "
                "ON CONFLICT (key) DO UPDATE SET value = :value, updated_at = CURRENT_TIMESTAMP"
            ),
            {"key": key, "value": value},
        )
        prefs[key] = value
    session.commit()

    # Mask API key in response (use in-memory prefs, not a second DB read).
    api_key = prefs.get("llm_api_key", "")
    if len(api_key) > 4:
        prefs["llm_api_key"] = "****" + api_key[-4:]
    return UserPreferences(**prefs)
