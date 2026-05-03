# API Key Encryption at Rest — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Encrypt `llm_api_key` in `user_preferences` at the application layer using Fernet so a database dump alone cannot expose stored LLM API keys.

**Architecture:** A new `api/src/app/core/crypto.py` module exposes `encrypt_api_key` / `decrypt_api_key` backed by `PREF_ENCRYPTION_KEY` env var. All three sites that read `llm_api_key` from the DB call `decrypt_api_key`; the single write site (`update_preferences`) calls `encrypt_api_key`. When the env var is unset the functions are no-ops, keeping local dev and SQLite tests working without configuration.

**Tech Stack:** Python 3.12, `cryptography.fernet.Fernet`, FastAPI, SQLAlchemy (sync), Alembic, pytest

---

## File Map

| File | Change |
|---|---|
| `api/src/app/core/crypto.py` | **Create** — `encrypt_api_key`, `decrypt_api_key`, `_get_fernet` |
| `tests/unit/test_crypto.py` | **Create** — unit tests for crypto module |
| `tests/conftest.py` | **Modify** — set `PREF_ENCRYPTION_KEY` in `configured_db` fixture |
| `api/src/app/routes/preferences.py` | **Modify** — encrypt on write, decrypt on read in `_load_preferences` and `update_preferences` |
| `api/src/app/routes/process.py` | **Modify** — decrypt in `_load_user_llm_config` |
| `api/src/app/routes/concepts.py` | **Modify** — decrypt in `_resolve_llm_settings` |
| `api/alembic/versions/20260503_0016_clear_plaintext_api_keys.py` | **Create** — wipe existing plaintext API key values |
| `infra/docker-compose.yml` | **Modify** — add `PREF_ENCRYPTION_KEY` env var |
| `CLAUDE.md` | **Modify** — document `PREF_ENCRYPTION_KEY` in env var table |

---

### Task 1: Create `crypto.py` module (TDD)

**Files:**
- Create: `api/src/app/core/crypto.py`
- Create: `tests/unit/test_crypto.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_crypto.py` with this exact content:

```python
"""Unit tests for API key encryption helpers."""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.core.crypto import decrypt_api_key, encrypt_api_key


def test_encrypt_decrypt_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PREF_ENCRYPTION_KEY", Fernet.generate_key().decode())
    plaintext = "sk-test-key-abc123"
    assert decrypt_api_key(encrypt_api_key(plaintext)) == plaintext


def test_no_key_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """When PREF_ENCRYPTION_KEY is unset, functions return the value unchanged."""
    monkeypatch.delenv("PREF_ENCRYPTION_KEY", raising=False)
    value = "sk-test-key-abc123"
    assert encrypt_api_key(value) == value
    assert decrypt_api_key(value) == value


def test_tampered_ciphertext_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PREF_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with pytest.raises(InvalidToken):
        decrypt_api_key("not-a-valid-fernet-token")


def test_empty_string_round_trips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PREF_ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert decrypt_api_key(encrypt_api_key("")) == ""
```

- [ ] **Step 2: Run tests and confirm they FAIL**

```bash
cd /Users/rishis/Desktop/Projects/NeuroNote && uv run --project api pytest tests/unit/test_crypto.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.core.crypto'`

- [ ] **Step 3: Create `api/src/app/core/crypto.py`**

```python
"""Fernet-based encryption for sensitive preference values (llm_api_key).

PREF_ENCRYPTION_KEY must be a base64url-encoded 32-byte Fernet key.
Generate one with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

When the env var is unset, both functions are no-ops (plaintext stored/returned).
"""
from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken

__all__ = ["encrypt_api_key", "decrypt_api_key", "InvalidToken"]


def _get_fernet() -> Fernet | None:
    raw = os.getenv("PREF_ENCRYPTION_KEY", "").strip()
    if not raw:
        return None
    return Fernet(raw.encode())


def encrypt_api_key(plaintext: str) -> str:
    """Encrypt plaintext; no-op if PREF_ENCRYPTION_KEY is unset."""
    f = _get_fernet()
    if f is None:
        return plaintext
    return f.encrypt(plaintext.encode()).decode()


def decrypt_api_key(ciphertext: str) -> str:
    """Decrypt ciphertext; no-op if PREF_ENCRYPTION_KEY is unset.

    Raises ``InvalidToken`` if the key is set but ciphertext is invalid/tampered.
    """
    f = _get_fernet()
    if f is None:
        return ciphertext
    return f.decrypt(ciphertext.encode()).decode()
```

- [ ] **Step 4: Run tests and confirm they PASS**

```bash
cd /Users/rishis/Desktop/Projects/NeuroNote && uv run --project api pytest tests/unit/test_crypto.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add api/src/app/core/crypto.py tests/unit/test_crypto.py
git commit -m "feat: add Fernet-based encrypt_api_key / decrypt_api_key helpers"
```

---

### Task 2: Wire encryption into `preferences.py` + update conftest

**Files:**
- Modify: `tests/conftest.py`
- Modify: `api/src/app/routes/preferences.py`
- Modify: `tests/unit/test_preferences_api.py`

- [ ] **Step 1: Update `conftest.py` to set `PREF_ENCRYPTION_KEY` in all tests**

In `tests/conftest.py`, add the import at the top (after the existing imports):

```python
from cryptography.fernet import Fernet
```

Then inside the `configured_db` fixture, add this line immediately after the other `monkeypatch.setenv` calls (around line 32, after `monkeypatch.setenv("REQUIRE_DB_EXTENSIONS", "false")`):

```python
    monkeypatch.setenv("PREF_ENCRYPTION_KEY", Fernet.generate_key().decode())
```

The full `configured_db` fixture after the change:

```python
@pytest.fixture()
def configured_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    external_db_url = os.getenv("TEST_DATABASE_URL")
    if external_db_url:
        monkeypatch.setenv("DATABASE_URL", external_db_url)
    else:
        test_db_path = tmp_path / "api-test.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{test_db_path}")
    monkeypatch.setenv("DB_AUTO_CREATE", "true")
    monkeypatch.setenv("REQUIRE_DB_EXTENSIONS", "false")
    monkeypatch.setenv("PREF_ENCRYPTION_KEY", Fernet.generate_key().decode())

    from app.db.engine import initialize_database, reset_engine
    from app.core.backfill_store import reset_backfill_status
    from app.core.job_store import reset_job_store

    reset_engine()
    reset_job_store()
    reset_backfill_status()
    initialize_database()

    from app.db.engine import get_session_factory
    from sqlalchemy import text as sa_text
    factory = get_session_factory()
    with factory() as session:
        session.execute(sa_text(
            "CREATE TABLE IF NOT EXISTS user_preferences ("
            "  key VARCHAR(64) NOT NULL PRIMARY KEY,"
            "  value TEXT NOT NULL,"
            "  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            ")"
        ))
        session.commit()

    yield
    reset_job_store()
    reset_backfill_status()
    reset_engine()
```

- [ ] **Step 2: Write the two new failing tests**

Append these tests to the end of `tests/unit/test_preferences_api.py`:

```python
# ── encryption at rest ──────────────────────────────────────────────────────


def test_put_preferences_api_key_is_encrypted_in_db(
    client: TestClient, db_session: "Session"
) -> None:
    """Raw DB value after PUT must differ from the plaintext key (i.e. encrypted)."""
    from sqlalchemy import text as sa_text

    client.put("/v1/preferences", json={"llm_api_key": "sk-real-key-abc123"})
    row = db_session.execute(
        sa_text("SELECT value FROM user_preferences WHERE key = 'llm_api_key'")
    ).first()
    assert row is not None
    assert row[0] != "sk-real-key-abc123"


def test_put_preferences_api_key_round_trips(
    client: TestClient, db_session: "Session"
) -> None:
    """PUT an API key; _load_preferences must return the decrypted plaintext."""
    from app.routes.preferences import _load_preferences

    client.put("/v1/preferences", json={"llm_api_key": "sk-real-key-abc123"})
    prefs = _load_preferences(db_session)
    assert prefs["llm_api_key"] == "sk-real-key-abc123"
```

- [ ] **Step 3: Run the new tests and confirm they FAIL**

```bash
cd /Users/rishis/Desktop/Projects/NeuroNote && uv run --project api pytest tests/unit/test_preferences_api.py::test_put_preferences_api_key_is_encrypted_in_db tests/unit/test_preferences_api.py::test_put_preferences_api_key_round_trips -v
```

Expected: both FAIL — `test_put_preferences_api_key_is_encrypted_in_db` fails because the value is still stored as plaintext; `test_put_preferences_api_key_round_trips` passes trivially (plaintext in = plaintext out), but the encryption test must fail.

- [ ] **Step 4: Update `api/src/app/routes/preferences.py`**

Add the import at the top of the file (after the existing imports):

```python
from app.core.crypto import decrypt_api_key, encrypt_api_key
```

Replace `_load_preferences` with:

```python
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
```

Replace the `for key, value in updates.items():` loop inside `update_preferences` with:

```python
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
```

- [ ] **Step 5: Run new tests and confirm they PASS**

```bash
cd /Users/rishis/Desktop/Projects/NeuroNote && uv run --project api pytest tests/unit/test_preferences_api.py::test_put_preferences_api_key_is_encrypted_in_db tests/unit/test_preferences_api.py::test_put_preferences_api_key_round_trips -v
```

Expected: both PASS

- [ ] **Step 6: Run the full preferences test file to check for regressions**

```bash
cd /Users/rishis/Desktop/Projects/NeuroNote && uv run --project api pytest tests/unit/test_preferences_api.py -v
```

Expected: all tests pass. The masking test (`test_put_preferences_masks_api_key`) still passes because masking runs after decryption in `_load_preferences`.

Note: `test_load_user_llm_config_returns_settings_for_cloud` and `test_resolve_llm_settings_cloud_mode` may now fail — the API key is stored encrypted but those functions don't decrypt yet. That is expected and will be fixed in Task 3.

- [ ] **Step 7: Commit**

```bash
git add tests/conftest.py api/src/app/routes/preferences.py tests/unit/test_preferences_api.py
git commit -m "feat: encrypt llm_api_key on write, decrypt on read in preferences route"
```

---

### Task 3: Decrypt in `process.py` and `concepts.py`

**Files:**
- Modify: `api/src/app/routes/process.py`
- Modify: `api/src/app/routes/concepts.py`

- [ ] **Step 1: Run affected tests and confirm they currently FAIL**

After Task 2, the API key is stored encrypted but `_load_user_llm_config` and
`_resolve_llm_settings` don't decrypt. These two tests should fail:

```bash
cd /Users/rishis/Desktop/Projects/NeuroNote && uv run --project api pytest \
  tests/unit/test_preferences_api.py::test_load_user_llm_config_returns_settings_for_cloud \
  tests/unit/test_preferences_api.py::test_resolve_llm_settings_cloud_mode -v
```

Expected: both FAIL — `result.llm_api_key` is the Fernet token, not the plaintext key.

- [ ] **Step 2: Update `_load_user_llm_config` in `api/src/app/routes/process.py`**

Inside `_load_user_llm_config`, find the block that starts with `from app.db.engine import bind_session_to_tenant, get_session_factory` and update it to also import `decrypt_api_key`. Then replace the `prefs` check and return:

```python
def _load_user_llm_config(schema_name: str) -> NlpSettings | None:
    """Load user's LLM preferences from the tenant schema.

    Returns an overridden NlpSettings for cloud mode with an API key,
    or None for edge mode / missing key (fall back to server defaults).
    """
    from app.core.crypto import decrypt_api_key
    from app.db.engine import bind_session_to_tenant, get_session_factory
    from app.db.tenant import validate_schema_name

    validate_schema_name(schema_name)
    factory = get_session_factory()
    with factory() as session:
        url = str(session.get_bind().url)
        if url.startswith("postgresql"):
            bind_session_to_tenant(session, schema_name)
        rows = session.execute(
            sa_text("SELECT key, value FROM user_preferences")
        ).all()

    prefs = {str(r[0]): str(r[1]) for r in rows}
    api_key = decrypt_api_key(prefs.get("llm_api_key", ""))
    if prefs.get("llm_mode") != "cloud" or not api_key:
        return None

    base = get_nlp_settings()
    return _dataclass_replace(
        base,
        extraction_profile="llm-enhanced",
        llm_api_key=api_key,
        llm_base_url=prefs.get("llm_base_url", base.llm_base_url),
        llm_model=prefs.get("llm_model", base.llm_model),
    )
```

- [ ] **Step 3: Update `_resolve_llm_settings` in `api/src/app/routes/concepts.py`**

Add `from app.core.crypto import decrypt_api_key` to the existing imports at the top of the file (alongside `from app.nlp.config import NlpSettings, get_nlp_settings`).

Replace `_resolve_llm_settings` with:

```python
def _resolve_llm_settings(session: Session) -> NlpSettings | None:
    """Read tenant preferences; return overridden NlpSettings for cloud mode, else None."""
    rows = session.execute(
        sa_text("SELECT key, value FROM user_preferences")
    ).all()
    prefs = {str(r[0]): str(r[1]) for r in rows}
    api_key = decrypt_api_key(prefs.get("llm_api_key", ""))
    if prefs.get("llm_mode") != "cloud" or not api_key:
        return None

    base = get_nlp_settings()
    return _dataclass_replace(
        base,
        extraction_profile="llm-enhanced",
        llm_api_key=api_key,
        llm_base_url=prefs.get("llm_base_url", base.llm_base_url),
        llm_model=prefs.get("llm_model", base.llm_model),
    )
```

- [ ] **Step 4: Run the two previously-failing tests and confirm they PASS**

```bash
cd /Users/rishis/Desktop/Projects/NeuroNote && uv run --project api pytest \
  tests/unit/test_preferences_api.py::test_load_user_llm_config_returns_settings_for_cloud \
  tests/unit/test_preferences_api.py::test_resolve_llm_settings_cloud_mode -v
```

Expected: both PASS

- [ ] **Step 5: Run the full unit suite**

```bash
cd /Users/rishis/Desktop/Projects/NeuroNote && uv run --project api pytest tests/unit/ -v
```

Expected: all tests pass, no regressions.

- [ ] **Step 6: Commit**

```bash
git add api/src/app/routes/process.py api/src/app/routes/concepts.py
git commit -m "feat: decrypt llm_api_key in _load_user_llm_config and _resolve_llm_settings"
```

---

### Task 4: Alembic migration 0016 — clear plaintext API keys

**Files:**
- Create: `api/alembic/versions/20260503_0016_clear_plaintext_api_keys.py`

- [ ] **Step 1: Create the migration file**

Create `api/alembic/versions/20260503_0016_clear_plaintext_api_keys.py` with this exact content:

```python
"""Clear plaintext llm_api_key values from all tenant schemas.

Existing stored API keys are plaintext and must be wiped before the
encryption layer is deployed. Users will need to re-enter their API key.

Revision ID: 20260503_0016
Revises: 20260421_0015
Create Date: 2026-05-03 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260503_0016"
down_revision = "20260421_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT schema_name FROM users")
    ).all()
    for (schema_name,) in rows:
        bind.execute(
            sa.text(
                f"UPDATE {schema_name}.user_preferences "
                "SET value = '' WHERE key = 'llm_api_key'"
            )
        )


def downgrade() -> None:
    pass  # clearing values is irreversible by design
```

- [ ] **Step 2: Verify the migration is syntactically valid**

```bash
cd /Users/rishis/Desktop/Projects/NeuroNote && python -c "
import ast
src = open('api/alembic/versions/20260503_0016_clear_plaintext_api_keys.py').read()
ast.parse(src)
print('Syntax OK')
"
```

Expected: `Syntax OK`

- [ ] **Step 3: Commit**

```bash
git add api/alembic/versions/20260503_0016_clear_plaintext_api_keys.py
git commit -m "feat: migration 0016 — clear plaintext llm_api_key values from tenant schemas"
```

---

### Task 5: Add `PREF_ENCRYPTION_KEY` to docker-compose and CLAUDE.md

**Files:**
- Modify: `infra/docker-compose.yml`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add env var to `infra/docker-compose.yml`**

In `infra/docker-compose.yml`, find the `api` service's `environment` block. After the `SESSION_SECRET` line (line 76), add:

```yaml
      PREF_ENCRYPTION_KEY: ${PREF_ENCRYPTION_KEY:-}
```

The empty default means encryption is a no-op in local dev unless `PREF_ENCRYPTION_KEY` is set in the environment. Production deployments must set this to a real Fernet key.

- [ ] **Step 2: Update `CLAUDE.md` env var table**

In `CLAUDE.md`, find the environment variables table. Add this row after the `SESSION_SECRET` row:

```markdown
| `PREF_ENCRYPTION_KEY` | `api/.env` or compose | Base64url Fernet key for encrypting `llm_api_key` at rest. Generate with: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Unset = no-op (plaintext stored). |
```

- [ ] **Step 3: Run the full unit suite one final time**

```bash
cd /Users/rishis/Desktop/Projects/NeuroNote && uv run --project api pytest tests/unit/ -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add infra/docker-compose.yml CLAUDE.md
git commit -m "chore: add PREF_ENCRYPTION_KEY env var to docker-compose and document in CLAUDE.md"
```
