-- Tenant schema template for NeuroNote multi-user SaaS.
-- All occurrences of {schema} are replaced with the actual schema name
-- at provisioning time.  Executed once per new user signup.
--
-- Tables derived from migrations 0001–0013 (excluding public.users).

-- ============================================================
-- subjects
-- ============================================================
CREATE TABLE {schema}.subjects (
    id          VARCHAR(64)                  NOT NULL,
    name        VARCHAR(255)                 NOT NULL,
    created_at  TIMESTAMP WITH TIME ZONE     NOT NULL,
    updated_at  TIMESTAMP WITH TIME ZONE     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (name)
);

-- ============================================================
-- notes  (0001 + 0003 note_title + 0004 is_pinned/is_archived)
-- ============================================================
CREATE TABLE {schema}.notes (
    note_id      VARCHAR(255)                NOT NULL,
    subject_id   VARCHAR(64)                 NOT NULL,
    note_title   VARCHAR(255)                NOT NULL,
    is_pinned    BOOLEAN                     NOT NULL DEFAULT FALSE,
    is_archived  BOOLEAN                     NOT NULL DEFAULT FALSE,
    content_json JSON                        NOT NULL,
    content_text TEXT                        NOT NULL,
    content_hash VARCHAR(64)                 NOT NULL,
    updated_at   VARCHAR(64)                 NOT NULL,
    version      INTEGER                     NOT NULL,
    created_at   TIMESTAMP WITH TIME ZONE    NOT NULL,
    saved_at     TIMESTAMP WITH TIME ZONE    NOT NULL,
    PRIMARY KEY (note_id),
    FOREIGN KEY (subject_id)
        REFERENCES {schema}.subjects (id) ON DELETE RESTRICT
);
CREATE INDEX ix_{schema}_notes_subject_id   ON {schema}.notes (subject_id);
CREATE INDEX ix_{schema}_notes_content_hash ON {schema}.notes (content_hash);

-- ============================================================
-- blocks  (0001 + 0006 block_uid / parent / sibling)
-- ============================================================
CREATE TABLE {schema}.blocks (
    id               SERIAL                  NOT NULL,
    note_id          VARCHAR(255)            NOT NULL,
    block_index      INTEGER                 NOT NULL,
    block_uid        VARCHAR(64)             NOT NULL,
    parent_block_uid VARCHAR(64),
    sibling_order    INTEGER                 NOT NULL,
    content_text     TEXT                    NOT NULL,
    content_hash     VARCHAR(64)             NOT NULL,
    rich_content     JSON                    NOT NULL,
    created_at       TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at       TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (note_id)
        REFERENCES {schema}.notes (note_id) ON DELETE CASCADE,
    UNIQUE (note_id, block_uid),
    UNIQUE (note_id, parent_block_uid, sibling_order)
);
CREATE INDEX ix_{schema}_blocks_note_id          ON {schema}.blocks (note_id);
CREATE INDEX ix_{schema}_blocks_content_hash     ON {schema}.blocks (content_hash);
CREATE INDEX ix_{schema}_blocks_block_uid        ON {schema}.blocks (block_uid);
CREATE INDEX ix_{schema}_blocks_parent_block_uid ON {schema}.blocks (parent_block_uid);

-- ============================================================
-- tags
-- ============================================================
CREATE TABLE {schema}.tags (
    id          SERIAL                       NOT NULL,
    name        VARCHAR(255)                 NOT NULL,
    created_at  TIMESTAMP WITH TIME ZONE     NOT NULL,
    updated_at  TIMESTAMP WITH TIME ZONE     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (name)
);
CREATE UNIQUE INDEX ix_{schema}_tags_name ON {schema}.tags (name);

-- ============================================================
-- note_tags  (0004)
-- ============================================================
CREATE TABLE {schema}.note_tags (
    note_id  VARCHAR(255) NOT NULL,
    tag_id   INTEGER      NOT NULL,
    PRIMARY KEY (note_id, tag_id),
    FOREIGN KEY (note_id) REFERENCES {schema}.notes (note_id)  ON DELETE CASCADE,
    FOREIGN KEY (tag_id)  REFERENCES {schema}.tags  (id)       ON DELETE CASCADE
);
CREATE INDEX ix_{schema}_note_tags_note_id ON {schema}.note_tags (note_id);
CREATE INDEX ix_{schema}_note_tags_tag_id  ON {schema}.note_tags (tag_id);

-- ============================================================
-- entity_aliases  (0002)
-- ============================================================
CREATE TABLE {schema}.entity_aliases (
    id                  SERIAL                   NOT NULL,
    alias_text          VARCHAR(255)             NOT NULL,
    canonical_entity_id VARCHAR(255)             NOT NULL,
    canonical_name      VARCHAR(255)             NOT NULL,
    confidence          FLOAT                    NOT NULL,
    source              VARCHAR(64)              NOT NULL,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (alias_text)
);
CREATE UNIQUE INDEX ix_{schema}_entity_aliases_alias_text
    ON {schema}.entity_aliases (alias_text);
CREATE INDEX ix_{schema}_entity_aliases_canonical_entity_id
    ON {schema}.entity_aliases (canonical_entity_id);

-- ============================================================
-- note_assets  (0005)
-- ============================================================
CREATE TABLE {schema}.note_assets (
    asset_id       VARCHAR(64)              NOT NULL,
    note_id        VARCHAR(255)             NOT NULL,
    mime_type      VARCHAR(128)             NOT NULL,
    file_ext       VARCHAR(16)              NOT NULL,
    byte_size      INTEGER                  NOT NULL,
    relative_path  VARCHAR(512)             NOT NULL,
    created_at     TIMESTAMP WITH TIME ZONE NOT NULL,
    deleted_at     TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (asset_id),
    FOREIGN KEY (note_id)
        REFERENCES {schema}.notes (note_id) ON DELETE CASCADE,
    UNIQUE (relative_path)
);
CREATE INDEX ix_{schema}_note_assets_note_id ON {schema}.note_assets (note_id);

-- ============================================================
-- processing_jobs  (0009 + 0013 extraction_summary)
-- ============================================================
CREATE TABLE {schema}.processing_jobs (
    job_id             VARCHAR(64)              NOT NULL,
    note_id            VARCHAR(255)             NOT NULL,
    content_hash       VARCHAR(64)              NOT NULL,
    status             VARCHAR(32)              NOT NULL DEFAULT 'queued',
    error              TEXT,
    extraction_summary JSONB,
    created_at         TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (job_id)
);
CREATE INDEX ix_{schema}_processing_jobs_note_content
    ON {schema}.processing_jobs (note_id, content_hash);
CREATE INDEX ix_{schema}_processing_jobs_status
    ON {schema}.processing_jobs (status);

-- ============================================================
-- concept_registry  (0010 + 0012 meta_classified_at + 0017 embedding)
-- ============================================================
CREATE TABLE {schema}.concept_registry (
    concept_text       TEXT                     NOT NULL,
    entity_id          TEXT                     NOT NULL,
    meta_classified_at TIMESTAMP WITH TIME ZONE,
    created_at         TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    embedding          vector(384),
    PRIMARY KEY (concept_text)
);
CREATE INDEX IF NOT EXISTS concept_registry_embedding_hnsw_idx
    ON {schema}.concept_registry USING hnsw (embedding vector_cosine_ops);

-- ============================================================
-- concept_insight_cache  (0011)
-- ============================================================
CREATE TABLE {schema}.concept_insight_cache (
    concept_label  TEXT                     NOT NULL,
    content_digest VARCHAR(64)             NOT NULL,
    insight        TEXT                     NOT NULL,
    learning_links TEXT                     NOT NULL DEFAULT '[]',
    notes_count    INTEGER                 NOT NULL,
    generated_at   TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (concept_label)
);

-- ============================================================
-- nlp_extraction_cache  (0011)
-- ============================================================
CREATE TABLE {schema}.nlp_extraction_cache (
    content_hash       VARCHAR(64)              NOT NULL,
    extraction_profile VARCHAR(32)              NOT NULL,
    result_json        TEXT                     NOT NULL,
    created_at         TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (content_hash)
);

-- ============================================================
-- user_preferences  (key-value store for per-user settings)
-- ============================================================
CREATE TABLE {schema}.user_preferences (
    key        VARCHAR(64)              NOT NULL,
    value      TEXT                     NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (key)
);

-- ============================================================
-- note_embeddings  (0008 — pgvector)
-- Requires: CREATE EXTENSION IF NOT EXISTS vector  (database-wide, run once)
-- ============================================================
CREATE TABLE {schema}.note_embeddings (
    embedding_id BIGSERIAL                    NOT NULL,
    item_id      TEXT                         NOT NULL,
    item_type    TEXT                         NOT NULL,
    embedding    vector(384)                  NOT NULL,
    created_at   TIMESTAMP WITH TIME ZONE     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (embedding_id),
    UNIQUE (item_id, item_type)
);
CREATE INDEX ix_{schema}_note_embeddings_hnsw
    ON {schema}.note_embeddings
    USING hnsw (embedding vector_cosine_ops);
