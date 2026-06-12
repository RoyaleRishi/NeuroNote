"""Tenant schema provisioning for multi-user SaaS.

Each user gets an isolated PostgreSQL schema containing all data tables.
On SQLite (tests), schemas are emulated as table-name prefixes.

Usage::

    create_user_schema(session, "user_abc123")   # provisions all tables + AGE graph
    drop_user_schema(session, "user_abc123")     # tears down schema + graph
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_SCHEMA_NAME_RE = re.compile(r"^user_[a-z0-9]{4,32}$")

# Every table that lives inside a per-user schema (12 total).
TENANT_TABLES: tuple[str, ...] = (
    "subjects",
    "notes",
    "blocks",
    "tags",
    "note_tags",
    "entity_aliases",
    "note_assets",
    "processing_jobs",
    "concept_registry",
    "concept_insight_cache",
    "nlp_extraction_cache",
    "user_preferences",
    "note_embeddings",
)

_TEMPLATE_PATH = Path(__file__).parent / "schema_template.sql"

# Tables that require pgvector — skipped on SQLite.
_PGVECTOR_TABLES = {"note_embeddings"}


def validate_schema_name(name: str) -> None:
    """Raise ``ValueError`` if *name* is not a safe schema identifier."""
    if not name:
        raise ValueError("Invalid schema name: must not be empty")
    if not name.startswith("user_"):
        raise ValueError(f"Invalid schema name: must start with 'user_', got {name!r}")
    if not _SCHEMA_NAME_RE.fullmatch(name):
        raise ValueError(f"Invalid schema name: {name!r}")


def _is_postgres(session: Session) -> bool:
    url = str(session.get_bind().url)  # type: ignore[union-attr]
    return url.startswith("postgresql")


def _graph_name(schema_name: str) -> str:
    return f"nn_{schema_name}"


# ------------------------------------------------------------------
# Postgres path — real schemas + AGE graph
# ------------------------------------------------------------------

def _pg_create_schema(session: Session, schema_name: str) -> None:
    """Create the tenant schema and all tables on Postgres."""
    session.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))

    # Ensure pgvector extension exists (database-wide, idempotent).
    session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    template_sql = _TEMPLATE_PATH.read_text()
    rendered = template_sql.replace("{schema}", schema_name)

    # Split on semicolons and execute each statement individually.
    for stmt in rendered.split(";"):
        # Strip leading comment lines so we can detect the actual SQL keyword.
        lines = stmt.strip().splitlines()
        sql_lines = [ln for ln in lines if not ln.strip().startswith("--")]
        cleaned = "\n".join(sql_lines).strip()
        if not cleaned:
            continue
        # Make CREATE TABLE / CREATE INDEX idempotent — but only if the
        # template hasn't already written "IF NOT EXISTS" itself.
        upper = cleaned.upper()
        if "IF NOT EXISTS" not in upper:
            if upper.startswith("CREATE TABLE"):
                cleaned = cleaned.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1)
            elif upper.startswith("CREATE UNIQUE INDEX"):
                cleaned = cleaned.replace(
                    "CREATE UNIQUE INDEX", "CREATE UNIQUE INDEX IF NOT EXISTS", 1
                )
            elif upper.startswith("CREATE INDEX"):
                cleaned = cleaned.replace("CREATE INDEX", "CREATE INDEX IF NOT EXISTS", 1)
        session.execute(text(cleaned))

    # Create per-user AGE graph.
    try:
        session.execute(text("LOAD 'age'"))
        session.execute(text("SET search_path = ag_catalog, \"$user\", public"))
        gname = _graph_name(schema_name)
        exists = session.execute(
            text("SELECT 1 FROM ag_catalog.ag_graph WHERE name = :gn LIMIT 1"),
            {"gn": gname},
        ).first()
        if not exists:
            session.execute(text(f"SELECT ag_catalog.create_graph('{gname}')"))
        logger.info("Provisioned AGE graph %s", gname)
    except Exception:
        logger.warning("AGE graph creation skipped (extension may not be loaded)")


def _pg_drop_schema(session: Session, schema_name: str) -> None:
    """Drop tenant schema and AGE graph on Postgres."""
    gname = _graph_name(schema_name)
    try:
        session.execute(text("LOAD 'age'"))
        session.execute(text("SET search_path = ag_catalog, \"$user\", public"))
        exists = session.execute(
            text("SELECT 1 FROM ag_catalog.ag_graph WHERE name = :gn LIMIT 1"),
            {"gn": gname},
        ).first()
        if exists:
            session.execute(text(f"SELECT ag_catalog.drop_graph('{gname}', true)"))
    except Exception:
        logger.warning("AGE graph drop skipped for %s", gname)

    session.execute(text(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE"))
    logger.info("Dropped tenant schema %s", schema_name)


# ------------------------------------------------------------------
# SQLite path — emulate schemas with table-name prefixes (for tests)
# ------------------------------------------------------------------

def _sqlite_create_tables(session: Session, schema_name: str) -> None:
    """Emulate tenant schema on SQLite using ``{schema}__{table}`` naming."""
    template_sql = _TEMPLATE_PATH.read_text()

    for table in TENANT_TABLES:
        if table in _PGVECTOR_TABLES:
            continue  # pgvector types not available in SQLite

        # Extract the CREATE TABLE block for this table from the template.
        prefixed = f"{schema_name}__{table}"
        _create_sqlite_table(session, schema_name, table, prefixed, template_sql)


def _create_sqlite_table(
    session: Session,
    schema_name: str,
    table: str,
    prefixed_name: str,
    template_sql: str,
) -> None:
    """Parse and execute a single CREATE TABLE + indexes for SQLite."""
    # Find the CREATE TABLE block in the template.
    # Pattern: CREATE TABLE {schema}.<table> ( ... );
    import re as _re

    pattern = _re.compile(
        rf"CREATE TABLE \{{schema\}}\.{_re.escape(table)}\s*\((.*?)\);",
        _re.DOTALL,
    )
    match = pattern.search(template_sql)
    if not match:
        logger.warning("No CREATE TABLE found for %s in template", table)
        return

    body = match.group(1)

    # Remove FOREIGN KEY references to schema-qualified tables —
    # rewrite {schema}.X to {schema_name}__X for SQLite.
    body = body.replace("{schema}.", f"{schema_name}__")

    # Remove unsupported Postgres types/syntax for SQLite.
    body = body.replace("TIMESTAMP WITH TIME ZONE", "TIMESTAMP")
    body = body.replace("SERIAL", "INTEGER")
    body = body.replace("BIGSERIAL", "INTEGER")
    body = body.replace("JSONB", "JSON")
    body = body.replace("DEFAULT NOW()", "")

    ddl = f"CREATE TABLE IF NOT EXISTS {prefixed_name} ({body})"
    session.execute(text(ddl))


def _sqlite_drop_tables(session: Session, schema_name: str) -> None:
    """Drop all prefixed tables for a tenant on SQLite."""
    for table in TENANT_TABLES:
        if table in _PGVECTOR_TABLES:
            continue
        prefixed = f"{schema_name}__{table}"
        session.execute(text(f"DROP TABLE IF EXISTS {prefixed}"))


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def mint_schema_name() -> str:
    """Generate a fresh tenant schema name matching ``^user_[a-z0-9]{4,32}$``."""
    import uuid

    return f"user_{uuid.uuid4().hex[:12]}"


def _seed_default_inbox(session: Session, schema_name: str) -> None:
    """Insert the default 'Inbox' subject row into a freshly-provisioned schema.

    Postgres only. The table reference is schema-qualified so this works
    regardless of where the prior step (AGE bootstrap) left ``search_path``.
    SQLite tests don't need the seed because they own their own fixture data.
    """
    if not _is_postgres(session):
        return
    session.execute(
        text(
            f"INSERT INTO {schema_name}.subjects (id, name, created_at, updated_at) "
            "VALUES (:id, :name, NOW(), NOW()) ON CONFLICT DO NOTHING"
        ),
        {"id": "inbox", "name": "Inbox"},
    )


def create_user_schema(session: Session, schema_name: str) -> None:
    """Provision tenant tables (+ AGE graph on Postgres) and seed default rows."""
    validate_schema_name(schema_name)
    if _is_postgres(session):
        _pg_create_schema(session, schema_name)
    else:
        _sqlite_create_tables(session, schema_name)
    _seed_default_inbox(session, schema_name)
    logger.info("Provisioned tenant schema %s", schema_name)


def drop_user_schema(session: Session, schema_name: str) -> None:
    """Tear down all tenant tables (+ AGE graph on Postgres)."""
    validate_schema_name(schema_name)
    if _is_postgres(session):
        _pg_drop_schema(session, schema_name)
    else:
        _sqlite_drop_tables(session, schema_name)


def apply_ddl_to_all_schemas(session: Session, ddl: str) -> None:
    """Execute *ddl* in every tenant schema. For future migrations."""
    rows = session.execute(
        text("SELECT schema_name FROM users")
    ).all()
    for (schema_name,) in rows:
        if _is_postgres(session):
            session.execute(text(f"SET search_path TO {schema_name}, public"))
            session.execute(text(ddl))
        else:
            logger.warning("apply_ddl_to_all_schemas not supported on SQLite")
            break
