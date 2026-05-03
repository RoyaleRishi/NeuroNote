# Fix: `_load_user_llm_config` tenant schema clobbering

**Date:** 2026-05-03  
**Branch:** serverside  
**Status:** Approved

## Problem

`_load_user_llm_config` in `api/src/app/routes/process.py:33` manipulates the
tenant-schema ContextVar (`set_tenant_schema`) unnecessarily. `_run_processing_job`
already pins the ContextVar for its entire scope before calling this helper. The
helper's `finally: set_tenant_schema(None)` resets the ContextVar to `None`,
so every session opened by `NoteProcessingService` afterwards runs with the wrong
`search_path`. This breaks note processing for all users (edge and cloud alike).

## Fix

Replace the ContextVar manipulation inside `_load_user_llm_config` with a
per-connection binding via `bind_session_to_tenant`. This makes the helper
fully self-contained with no side effects on external state.

### Changed file

**`api/src/app/routes/process.py`**

1. Add `bind_session_to_tenant` to the import from `app.db.engine`.
2. Remove `set_tenant_schema(schema_name)` call at the top of `_load_user_llm_config`.
3. Remove the `try/finally` wrapper around the session block.
4. Add `bind_session_to_tenant(session, schema_name)` immediately after opening the session.
5. Remove `set_tenant_schema` from the imports inside `_load_user_llm_config` (it is still used by `_run_processing_job` and imported there).

Before:
```python
set_tenant_schema(schema_name)
try:
    with factory() as session:
        rows = session.execute(
            sa_text("SELECT key, value FROM user_preferences")
        ).all()
finally:
    set_tenant_schema(None)
```

After:
```python
with factory() as session:
    bind_session_to_tenant(session, schema_name)
    rows = session.execute(
        sa_text("SELECT key, value FROM user_preferences")
    ).all()
```

`_run_processing_job` is **unchanged** — its outer `set_tenant_schema` scope
remains correct and still covers `mark_job_running`, `NoteProcessingService`, etc.

## Tests

**File:** `tests/unit/test_startup_backfill_service.py` or a new
`tests/unit/test_process_route.py`

1. **ContextVar isolation**: call `_load_user_llm_config` with the ContextVar
   pre-set to a schema; assert the ContextVar value is unchanged after the call.
2. **Edge mode returns None**: when `llm_mode` is `"edge"` (or absent), the
   function returns `None`.
3. **Cloud mode returns NlpSettings**: when `llm_mode == "cloud"` and
   `llm_api_key` is non-empty, the function returns an `NlpSettings` with
   `extraction_profile == "llm-enhanced"` and the correct `llm_api_key`.
4. **Missing key returns None**: when `llm_mode == "cloud"` but `llm_api_key`
   is empty/absent, the function returns `None`.

## Out of scope

- API key encryption at rest (separate spec).
- Adding a "Test Connection" button to the UI (separate task).
