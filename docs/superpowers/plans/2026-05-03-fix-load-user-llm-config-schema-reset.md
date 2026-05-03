# Fix `_load_user_llm_config` Tenant Schema Clobbering — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the ContextVar side-effects from `_load_user_llm_config` so it no longer resets the tenant schema, which currently breaks `NoteProcessingService` DB access for all users.

**Architecture:** Replace the `set_tenant_schema` / `set_tenant_schema(None)` pattern inside `_load_user_llm_config` with `bind_session_to_tenant`, which scopes the tenant to the session's underlying DBAPI connection (`conn.info`) rather than the global ContextVar. The function becomes self-contained with no external state side-effects.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy (sync), pytest

---

## File Map

| File | Change |
|---|---|
| `api/src/app/routes/process.py` | Replace ContextVar calls with `bind_session_to_tenant` in `_load_user_llm_config` |
| `tests/unit/test_preferences_api.py` | Add one new test: ContextVar isolation |

---

### Task 1: Write the failing ContextVar-isolation test

The bug is that `_load_user_llm_config` resets the `_tenant_schema` ContextVar to `None`
after reading preferences. This test proves that by setting the ContextVar to a known
value before the call and asserting it is unchanged after. It must **fail** before the
fix is applied.

**Files:**
- Modify: `tests/unit/test_preferences_api.py`

- [ ] **Step 1: Add the test**

Append this to the `# ── _load_user_llm_config` section that already exists in
`tests/unit/test_preferences_api.py` (after line 155):

```python
def test_load_user_llm_config_does_not_clobber_context_var(
    client: TestClient,
) -> None:
    """_load_user_llm_config must not alter the tenant-schema ContextVar.

    Before the fix, the function resets the ContextVar to None in its
    finally block, breaking NoteProcessingService sessions opened afterwards.
    """
    from app.db.engine import get_tenant_schema, set_tenant_schema
    from app.routes.process import _load_user_llm_config

    set_tenant_schema("user_test0001")
    try:
        _load_user_llm_config("user_test0001")
        assert get_tenant_schema() == "user_test0001", (
            "_load_user_llm_config must not reset the tenant-schema ContextVar"
        )
    finally:
        set_tenant_schema(None)  # always clean up so other tests are unaffected
```

- [ ] **Step 2: Run the test and confirm it FAILS**

```bash
cd /Users/rishis/Desktop/Projects/NeuroNote
uv run --directory api pytest tests/unit/test_preferences_api.py::test_load_user_llm_config_does_not_clobber_context_var -v
```

Expected output (before fix):
```
FAILED tests/unit/test_preferences_api.py::test_load_user_llm_config_does_not_clobber_context_var
AssertionError: _load_user_llm_config must not reset the tenant-schema ContextVar
```

---

### Task 2: Apply the `bind_session_to_tenant` fix

Replace the three ContextVar lines in `_load_user_llm_config` with a single
`bind_session_to_tenant` call on the session. This scopes the tenant to the
DBAPI connection (`conn.info`), which is local to that session and has no
effect on the ContextVar used by the rest of `_run_processing_job`.

**Files:**
- Modify: `api/src/app/routes/process.py:33–64`

- [ ] **Step 1: Update `_load_user_llm_config`**

In `api/src/app/routes/process.py`, replace the entire `_load_user_llm_config`
function body with this (the docstring and the `prefs`/return logic are unchanged;
only the session-opening block changes):

```python
def _load_user_llm_config(schema_name: str) -> NlpSettings | None:
    """Load user's LLM preferences from the tenant schema.

    Returns an overridden NlpSettings for cloud mode with an API key,
    or None for edge mode / missing key (fall back to server defaults).
    """
    from app.db.engine import bind_session_to_tenant, get_session_factory
    from app.db.tenant import validate_schema_name

    validate_schema_name(schema_name)
    factory = get_session_factory()
    with factory() as session:
        bind_session_to_tenant(session, schema_name)
        rows = session.execute(
            sa_text("SELECT key, value FROM user_preferences")
        ).all()

    prefs = {str(r[0]): str(r[1]) for r in rows}
    if prefs.get("llm_mode") != "cloud" or not prefs.get("llm_api_key"):
        return None

    base = get_nlp_settings()
    return _dataclass_replace(
        base,
        extraction_profile="llm-enhanced",
        llm_api_key=prefs["llm_api_key"],
        llm_base_url=prefs.get("llm_base_url", base.llm_base_url),
        llm_model=prefs.get("llm_model", base.llm_model),
    )
```

Key differences from the old version:
- `set_tenant_schema` and `set_tenant_schema(None)` removed entirely
- `bind_session_to_tenant` imported instead of `set_tenant_schema`
- No `try/finally` wrapper — the `with factory() as session:` block handles cleanup

- [ ] **Step 2: Run the new test and confirm it PASSES**

```bash
cd /Users/rishis/Desktop/Projects/NeuroNote
uv run --directory api pytest tests/unit/test_preferences_api.py::test_load_user_llm_config_does_not_clobber_context_var -v
```

Expected:
```
PASSED tests/unit/test_preferences_api.py::test_load_user_llm_config_does_not_clobber_context_var
```

- [ ] **Step 3: Run the full preferences test suite**

```bash
cd /Users/rishis/Desktop/Projects/NeuroNote
uv run --directory api pytest tests/unit/test_preferences_api.py -v
```

Expected: all tests pass. There are 4 existing `_load_user_llm_config` tests and
3 existing `_resolve_llm_settings` tests — none of them should regress.

- [ ] **Step 4: Run the full unit test suite**

```bash
cd /Users/rishis/Desktop/Projects/NeuroNote
uv run --directory api pytest tests/unit/ -v
```

Expected: all tests pass with no regressions.

- [ ] **Step 5: Commit**

```bash
git add api/src/app/routes/process.py tests/unit/test_preferences_api.py
git commit -m "fix: use bind_session_to_tenant in _load_user_llm_config to avoid clobbering tenant ContextVar"
```
