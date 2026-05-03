# API Key Encryption at Rest — Design Spec

**Date:** 2026-05-03  
**Branch:** serverside  
**Status:** Approved

## Problem

`user_preferences.value` stores `llm_api_key` as plaintext `TEXT` in every tenant's
PostgreSQL schema. A database dump exposes all stored LLM API keys without any further
access to the server.

## Goal

Encrypt `llm_api_key` values at the application layer so a database breach alone cannot
expose them. The encryption key lives in the server environment (`PREF_ENCRYPTION_KEY`),
not in the database. This protects against DB-dump breaches; it does not protect against
an attacker who has simultaneous access to both the DB and the server's env vars.

## Approach

Fernet symmetric authenticated encryption via Python's `cryptography` library
(`cryptography` is already installed as a transitive dependency of `authlib`).

---

## Architecture

### New module: `api/src/app/core/crypto.py`

Single-responsibility: encrypt and decrypt `llm_api_key` values.

```
encrypt_api_key(plaintext: str) -> str
    If PREF_ENCRYPTION_KEY is set: Fernet-encrypt, return base64 token string.
    If not set (dev/test with no key): return plaintext unchanged.

decrypt_api_key(ciphertext: str) -> str
    If PREF_ENCRYPTION_KEY is set: Fernet-decrypt, return plaintext string.
    If not set: return ciphertext unchanged (no-op).
    Raises cryptography.fernet.InvalidToken if ciphertext is tampered.
```

`get_fernet() -> Fernet | None` is the internal helper that reads `PREF_ENCRYPTION_KEY`
from the environment on every call (no module-level cache) and returns a `Fernet`
instance, or `None` when the var is unset. No cache means `monkeypatch.setenv` /
`monkeypatch.delenv` in tests work correctly. The public functions call this internally;
callers never touch Fernet directly.

### Write path

`api/src/app/routes/preferences.py` — `update_preferences`:  
Before inserting/upserting `llm_api_key`, pass the value through `encrypt_api_key`.
All other preference keys are stored unchanged.

### Read paths (three sites, all identical pattern)

Each site builds a `prefs: dict[str, str]` from `SELECT key, value FROM user_preferences`,
then applies `decrypt_api_key` to `prefs["llm_api_key"]` before using or returning it.

| File | Function |
|---|---|
| `api/src/app/routes/preferences.py` | `_load_preferences` |
| `api/src/app/routes/process.py` | `_load_user_llm_config` |
| `api/src/app/routes/concepts.py` | `_resolve_llm_settings` |

The masking logic in `get_preferences` (`****abcd`) runs **after** decryption, so the
masked display still reflects the real last 4 chars of the plaintext key.

### No column type change

`user_preferences.value` remains `TEXT`. A Fernet token is a base64url string and fits
without modification.

---

## Environment Variable

| Variable | Description |
|---|---|
| `PREF_ENCRYPTION_KEY` | Base64url-encoded 32-byte Fernet key. Generate with: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |

`PREF_ENCRYPTION_KEY` is added to `infra/docker-compose.yml` under the `api` service with
a hardcoded dev default (acceptable for local dev; must be overridden in production).

When unset, `encrypt_api_key` / `decrypt_api_key` are no-ops — plaintext is stored and
returned as-is. This keeps the local dev and SQLite test environments working without
requiring the env var.

---

## Migration

**Alembic revision 0016** (`api/alembic/versions/20260503_0016_clear_plaintext_api_keys.py`):

For every tenant schema found in `public.users`, run:
```sql
UPDATE {schema}.user_preferences SET value = '' WHERE key = 'llm_api_key';
```

Existing plaintext API key values are wiped. Users must re-enter their API key after
deploying this migration. No downgrade path (clearing values is irreversible by design).

---

## Tests

### `conftest.py`

Add `PREF_ENCRYPTION_KEY` to the `configured_db` fixture environment:
```python
monkeypatch.setenv("PREF_ENCRYPTION_KEY", Fernet.generate_key().decode())
```
This ensures all unit tests exercise the real encrypt/decrypt code paths.

### New: `tests/unit/test_crypto.py`

| Test | Assertion |
|---|---|
| `test_encrypt_decrypt_round_trip` | `decrypt_api_key(encrypt_api_key(plaintext)) == plaintext` |
| `test_no_key_is_noop` | Without `PREF_ENCRYPTION_KEY` set, `encrypt_api_key(x) == x` and `decrypt_api_key(x) == x` |
| `test_tampered_ciphertext_raises` | `decrypt_api_key("corrupted")` raises `InvalidToken` when key is set |
| `test_empty_string_round_trips` | `decrypt_api_key(encrypt_api_key("")) == ""` |

### Updated: `tests/unit/test_preferences_api.py`

| Test | Assertion |
|---|---|
| `test_put_preferences_api_key_is_encrypted_in_db` | After `PUT llm_api_key=sk-test`, read raw DB value and confirm it is NOT equal to `sk-test` (i.e. encrypted) |
| `test_put_preferences_api_key_round_trips` | `PUT llm_api_key=sk-test`, then `_load_preferences` returns `llm_api_key == "sk-test"` (decrypted) |

---

## Out of scope

- External key management service (KMS, Vault)
- Encrypting other preference values (`llm_base_url`, `llm_model`, etc.)
- Key rotation tooling
