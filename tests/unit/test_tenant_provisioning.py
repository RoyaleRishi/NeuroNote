"""Unit tests for tenant schema provisioning.

These tests run against SQLite, so pgvector (note_embeddings) and AGE graph
provisioning are skipped. Integration tests against Postgres cover those.
"""
from __future__ import annotations

import pytest
from sqlalchemy import inspect, text

from app.db.engine import get_engine, get_session_factory
from app.db.tenant import (
    TENANT_TABLES,
    create_user_schema,
    drop_user_schema,
    validate_schema_name,
)


_TEST_SCHEMA = "user_testprov"


def test_validate_schema_name_accepts_valid() -> None:
    validate_schema_name("user_abc123")
    validate_schema_name("user_a1b2c3d4")


def test_validate_schema_name_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="Invalid schema name"):
        validate_schema_name("user_abc; DROP TABLE users")
    with pytest.raises(ValueError, match="Invalid schema name"):
        validate_schema_name("")
    with pytest.raises(ValueError, match="must start with"):
        validate_schema_name("admin_schema")


def test_tenant_tables_constant() -> None:
    """TENANT_TABLES lists every per-user table."""
    assert "subjects" in TENANT_TABLES
    assert "notes" in TENANT_TABLES
    assert "blocks" in TENANT_TABLES
    assert "tags" in TENANT_TABLES
    assert "note_tags" in TENANT_TABLES
    assert "entity_aliases" in TENANT_TABLES
    assert "note_assets" in TENANT_TABLES
    assert "processing_jobs" in TENANT_TABLES
    assert "concept_registry" in TENANT_TABLES
    assert "concept_insight_cache" in TENANT_TABLES
    assert "nlp_extraction_cache" in TENANT_TABLES
    assert "note_embeddings" in TENANT_TABLES
    assert "user_preferences" in TENANT_TABLES
    assert len(TENANT_TABLES) == 13


def test_create_user_schema_creates_tables(configured_db: None) -> None:
    """On SQLite, create_user_schema creates tables with prefixed names."""
    factory = get_session_factory()
    with factory() as session:
        with session.begin():
            create_user_schema(session, _TEST_SCHEMA)

        inspector = inspect(get_engine())
        table_names = set(inspector.get_table_names())

        # SQLite doesn't support schemas, so tables get a prefix
        for table in TENANT_TABLES:
            if table == "note_embeddings":
                continue  # pgvector — skipped on SQLite
            prefixed = f"{_TEST_SCHEMA}__{table}"
            assert prefixed in table_names, f"Missing table: {prefixed}"


def test_create_user_schema_subjects_has_columns(configured_db: None) -> None:
    factory = get_session_factory()
    with factory() as session:
        with session.begin():
            create_user_schema(session, "user_colcheck")

        inspector = inspect(get_engine())
        columns = {
            col["name"]
            for col in inspector.get_columns(f"user_colcheck__subjects")
        }
        assert {"id", "name", "created_at", "updated_at"}.issubset(columns)


def test_create_user_schema_notes_has_all_columns(configured_db: None) -> None:
    factory = get_session_factory()
    with factory() as session:
        with session.begin():
            create_user_schema(session, "user_notecols")

        inspector = inspect(get_engine())
        columns = {
            col["name"]
            for col in inspector.get_columns("user_notecols__notes")
        }
        expected = {
            "note_id", "subject_id", "note_title", "is_pinned", "is_archived",
            "content_json", "content_text", "content_hash", "updated_at",
            "version", "created_at", "saved_at",
        }
        assert expected.issubset(columns)


def test_drop_user_schema(configured_db: None) -> None:
    factory = get_session_factory()
    with factory() as session:
        with session.begin():
            create_user_schema(session, "user_todrop")
        with session.begin():
            drop_user_schema(session, "user_todrop")

        inspector = inspect(get_engine())
        table_names = set(inspector.get_table_names())
        for table in TENANT_TABLES:
            if table == "note_embeddings":
                continue
            assert f"user_todrop__{table}" not in table_names


def test_create_duplicate_schema_is_idempotent(configured_db: None) -> None:
    """Creating the same schema twice should not raise."""
    factory = get_session_factory()
    with factory() as session:
        with session.begin():
            create_user_schema(session, "user_idem")
        with session.begin():
            create_user_schema(session, "user_idem")
