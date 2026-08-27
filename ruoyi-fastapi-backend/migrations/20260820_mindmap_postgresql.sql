-- Complete mind-map schema for PostgreSQL 14+.
-- Safe for both fresh databases and existing installations: CREATE/ALTER/INDEX
-- operations are idempotent and historical orphan references are converged
-- before foreign keys are installed.

BEGIN;

CREATE TABLE IF NOT EXISTS mindmap (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description VARCHAR(500),
    owner_id BIGINT NOT NULL,
    folder_id BIGINT,
    layout VARCHAR(50) NOT NULL DEFAULT 'logicalStructure',
    theme JSONB,
    node_tree TEXT NOT NULL,
    root_node_id BIGINT,
    content_revision BIGINT NOT NULL DEFAULT 1,
    node_count INTEGER NOT NULL DEFAULT 0,
    schema_version INTEGER NOT NULL DEFAULT 1,
    engine_name VARCHAR(50) NOT NULL DEFAULT 'simple-mind-map',
    engine_version VARCHAR(100),
    document_data JSONB,
    view_data JSONB,
    cover_image VARCHAR(500),
    last_version_id BIGINT,
    version_count INTEGER NOT NULL DEFAULT 1,
    status SMALLINT NOT NULL DEFAULT 0,
    del_flag CHAR(1) NOT NULL DEFAULT '0',
    create_by VARCHAR(64) DEFAULT '',
    create_time TIMESTAMP,
    update_by VARCHAR(64) DEFAULT '',
    update_time TIMESTAMP,
    remark VARCHAR(500)
);

-- Existing PostgreSQL installations may already contain the legacy mindmap table.
ALTER TABLE mindmap ADD COLUMN IF NOT EXISTS folder_id BIGINT;
ALTER TABLE mindmap ADD COLUMN IF NOT EXISTS root_node_id BIGINT;
ALTER TABLE mindmap ADD COLUMN IF NOT EXISTS content_revision BIGINT NOT NULL DEFAULT 1;
ALTER TABLE mindmap ADD COLUMN IF NOT EXISTS node_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE mindmap ADD COLUMN IF NOT EXISTS schema_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE mindmap ADD COLUMN IF NOT EXISTS engine_name VARCHAR(50) NOT NULL DEFAULT 'simple-mind-map';
ALTER TABLE mindmap ADD COLUMN IF NOT EXISTS engine_version VARCHAR(100);
ALTER TABLE mindmap ADD COLUMN IF NOT EXISTS document_data JSONB;
ALTER TABLE mindmap ADD COLUMN IF NOT EXISTS view_data JSONB;
ALTER TABLE mindmap ADD COLUMN IF NOT EXISTS last_version_id BIGINT;
ALTER TABLE mindmap ADD COLUMN IF NOT EXISTS version_count INTEGER NOT NULL DEFAULT 1;
ALTER TABLE mindmap ADD COLUMN IF NOT EXISTS status SMALLINT NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS mindmap_collaborator (
    id BIGSERIAL PRIMARY KEY,
    mindmap_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    permission SMALLINT NOT NULL DEFAULT 0,
    created_by BIGINT NOT NULL,
    created_time TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mindmap_share (
    id BIGSERIAL PRIMARY KEY,
    mindmap_id BIGINT NOT NULL,
    share_token VARCHAR(64) NOT NULL UNIQUE,
    share_type SMALLINT NOT NULL DEFAULT 0,
    expire_time TIMESTAMP,
    created_by BIGINT NOT NULL,
    created_time TIMESTAMP,
    is_active SMALLINT NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS mindmap_folder (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    parent_id BIGINT NOT NULL DEFAULT 0,
    owner_id BIGINT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    del_flag VARCHAR(1) NOT NULL DEFAULT '0',
    active_name VARCHAR(100) GENERATED ALWAYS AS (
        CASE WHEN del_flag = '0' THEN name ELSE NULL END
    ) STORED,
    create_by VARCHAR(64) DEFAULT '',
    create_time TIMESTAMP,
    update_by VARCHAR(64) DEFAULT '',
    update_time TIMESTAMP
);
ALTER TABLE mindmap_folder ADD COLUMN IF NOT EXISTS active_name VARCHAR(100)
    GENERATED ALWAYS AS (CASE WHEN del_flag = '0' THEN name ELSE NULL END) STORED;

CREATE TABLE IF NOT EXISTS mindmap_version (
    id BIGSERIAL PRIMARY KEY,
    mindmap_id BIGINT NOT NULL,
    version_number INTEGER NOT NULL,
    version_type SMALLINT NOT NULL DEFAULT 0,
    name VARCHAR(200),
    node_tree TEXT NOT NULL,
    view_data JSONB,
    layout VARCHAR(50),
    theme JSONB,
    snapshot_schema_version INTEGER NOT NULL DEFAULT 1,
    tag_snapshots JSONB,
    created_by VARCHAR(64) NOT NULL,
    created_time TIMESTAMP
);
ALTER TABLE mindmap_version ADD COLUMN IF NOT EXISTS snapshot_schema_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE mindmap_version ADD COLUMN IF NOT EXISTS tag_snapshots JSONB;

CREATE TABLE IF NOT EXISTS mindmap_ws_state (
    id BIGSERIAL PRIMARY KEY,
    mindmap_id BIGINT NOT NULL UNIQUE,
    yjs_state BYTEA,
    content_revision BIGINT,
    updated_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mindmap_node (
    id BIGSERIAL PRIMARY KEY,
    file_id BIGINT NOT NULL,
    node_uid VARCHAR(64) NOT NULL,
    parent_id BIGINT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    text_content TEXT,
    text_plain TEXT,
    text_format VARCHAR(16) NOT NULL DEFAULT 'plain',
    is_expanded SMALLINT NOT NULL DEFAULT 1,
    direction VARCHAR(16),
    custom_left DOUBLE PRECISION,
    custom_top DOUBLE PRECISION,
    custom_text_width DOUBLE PRECISION,
    content_data JSONB,
    style_data JSONB,
    extension_data JSONB,
    envelope_data JSONB,
    payload_schema_version INTEGER NOT NULL DEFAULT 1,
    node_revision BIGINT NOT NULL DEFAULT 1,
    is_deleted SMALLINT NOT NULL DEFAULT 0,
    deleted_time TIMESTAMP,
    create_by VARCHAR(64),
    create_time TIMESTAMP,
    update_by VARCHAR(64),
    update_time TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mindmap_relation (
    id BIGSERIAL PRIMARY KEY,
    relation_uid VARCHAR(96) NOT NULL,
    file_id BIGINT NOT NULL,
    relation_type VARCHAR(32) NOT NULL DEFAULT 'associative_line',
    source_node_id BIGINT NOT NULL,
    target_node_id BIGINT NOT NULL,
    text TEXT,
    control_data JSONB,
    style_data JSONB,
    sort_order INTEGER NOT NULL DEFAULT 0,
    revision BIGINT NOT NULL DEFAULT 1,
    create_time TIMESTAMP,
    update_time TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mindmap_summary (
    id BIGSERIAL PRIMARY KEY,
    summary_uid VARCHAR(64) NOT NULL,
    file_id BIGINT NOT NULL,
    owner_node_id BIGINT NOT NULL,
    start_child_id BIGINT,
    end_child_id BIGINT,
    content_data JSONB,
    style_data JSONB,
    extension_data JSONB,
    sort_order INTEGER NOT NULL DEFAULT 0,
    revision BIGINT NOT NULL DEFAULT 1,
    create_time TIMESTAMP,
    update_time TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mindmap_group (
    id BIGSERIAL PRIMARY KEY,
    group_uid VARCHAR(64) NOT NULL,
    file_id BIGINT NOT NULL,
    parent_node_id BIGINT NOT NULL,
    group_type VARCHAR(32) NOT NULL DEFAULT 'outer_frame',
    text TEXT,
    style_data JSONB,
    extension_data JSONB,
    revision BIGINT NOT NULL DEFAULT 1,
    create_time TIMESTAMP,
    update_time TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mindmap_group_member (
    id BIGSERIAL PRIMARY KEY,
    group_id BIGINT NOT NULL,
    node_id BIGINT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS mindmap_asset (
    id BIGSERIAL PRIMARY KEY,
    file_id BIGINT NOT NULL,
    asset_key VARCHAR(128) NOT NULL,
    asset_type VARCHAR(32) NOT NULL DEFAULT 'image',
    storage_type VARCHAR(16) NOT NULL DEFAULT 'url',
    uri TEXT,
    object_key VARCHAR(500),
    mime_type VARCHAR(100),
    size BIGINT,
    sha256 VARCHAR(64),
    metadata JSONB,
    create_time TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mindmap_change_log (
    id BIGSERIAL PRIMARY KEY,
    file_id BIGINT NOT NULL,
    base_revision BIGINT NOT NULL,
    revision BIGINT NOT NULL,
    client_mutation_id VARCHAR(100) NOT NULL,
    operations JSONB NOT NULL,
    result_data JSONB,
    created_by VARCHAR(64),
    created_time TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS mindmap_migration_record (
    id BIGSERIAL PRIMARY KEY,
    file_id BIGINT NOT NULL,
    batch_id VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL,
    legacy_hash VARCHAR(64),
    structured_hash VARCHAR(64),
    error_message VARCHAR(2000),
    started_time TIMESTAMP NOT NULL,
    finished_time TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS mindmap_creation_request (
    id BIGSERIAL PRIMARY KEY,
    owner_id BIGINT NOT NULL,
    request_id VARCHAR(100) NOT NULL,
    operation VARCHAR(32) NOT NULL,
    request_fingerprint VARCHAR(64) NOT NULL,
    result_file_id BIGINT,
    created_by VARCHAR(64),
    created_time TIMESTAMP NOT NULL,
    completed_time TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mindmap_comment_thread (
    id BIGSERIAL PRIMARY KEY,
    mindmap_id BIGINT NOT NULL,
    node_uid VARCHAR(64) NOT NULL,
    node_text VARCHAR(500),
    status SMALLINT NOT NULL DEFAULT 0,
    created_by BIGINT NOT NULL,
    created_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_comment_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_by BIGINT,
    resolved_time TIMESTAMP,
    del_flag CHAR(1) NOT NULL DEFAULT '0'
);

CREATE TABLE IF NOT EXISTS mindmap_comment (
    id BIGSERIAL PRIMARY KEY,
    thread_id BIGINT NOT NULL,
    mindmap_id BIGINT NOT NULL,
    content TEXT NOT NULL,
    created_by BIGINT NOT NULL,
    client_request_id VARCHAR(100),
    created_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP,
    del_flag CHAR(1) NOT NULL DEFAULT '0'
);

CREATE TABLE IF NOT EXISTS mindmap_tag_category (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    category_type VARCHAR(20) NOT NULL DEFAULT 'custom',
    owner_id BIGINT NOT NULL DEFAULT 0,
    sort_order INTEGER DEFAULT 0,
    created_by VARCHAR(64),
    created_time TIMESTAMP
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'mindmap_tag_category'
          AND column_name = 'category_type'
    ) THEN
        ALTER TABLE mindmap_tag_category
            ADD COLUMN category_type VARCHAR(20) NOT NULL DEFAULT 'custom';
        UPDATE mindmap_tag_category AS category
        SET category_type = 'system'
        WHERE category.owner_id = 0
           OR (
                EXISTS (
                    SELECT 1 FROM mindmap_tag AS tag
                    WHERE tag.category_id = category.id
                )
                AND NOT EXISTS (
                    SELECT 1 FROM mindmap_tag AS tag
                    WHERE tag.category_id = category.id AND tag.owner_id <> 0
                )
           );
        UPDATE mindmap_tag_category AS category
        SET owner_id = 0
        WHERE category.category_type = 'system'
          AND category.owner_id <> 0
          AND NOT EXISTS (
              SELECT 1 FROM mindmap_tag_category AS global_category
              WHERE global_category.owner_id = 0
                AND LOWER(global_category.name) = LOWER(category.name)
                AND global_category.id <> category.id
          );
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS mindmap_tag (
    id BIGSERIAL PRIMARY KEY,
    uuid VARCHAR(36) NOT NULL,
    tag_key VARCHAR(100) NOT NULL,
    name VARCHAR(200) NOT NULL,
    category_id BIGINT,
    owner_id BIGINT NOT NULL DEFAULT 0,
    style JSONB,
    description VARCHAR(500),
    status SMALLINT NOT NULL DEFAULT 0,
    definition_revision BIGINT NOT NULL DEFAULT 1,
    usage_node_count BIGINT NOT NULL DEFAULT 0,
    usage_file_count BIGINT NOT NULL DEFAULT 0,
    created_by VARCHAR(64),
    created_time TIMESTAMP,
    updated_time TIMESTAMP,
    update_by VARCHAR(64)
);
ALTER TABLE mindmap_tag ADD COLUMN IF NOT EXISTS definition_revision BIGINT NOT NULL DEFAULT 1;
ALTER TABLE mindmap_tag ADD COLUMN IF NOT EXISTS usage_node_count BIGINT NOT NULL DEFAULT 0;
ALTER TABLE mindmap_tag ADD COLUMN IF NOT EXISTS usage_file_count BIGINT NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS mindmap_node_tag (
    id BIGSERIAL PRIMARY KEY,
    file_id BIGINT NOT NULL,
    node_id BIGINT NOT NULL,
    tag_id BIGINT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    placement VARCHAR(16),
    align VARCHAR(16),
    created_by VARCHAR(64),
    created_time TIMESTAMP
);

-- Converge data into the same normalization domain used by service writes.
UPDATE mindmap_folder SET name = '未命名目录-' || id WHERE del_flag = '0' AND BTRIM(name) = '';
UPDATE mindmap_folder SET name = BTRIM(name) WHERE del_flag = '0' AND name <> BTRIM(name);
UPDATE mindmap_folder AS folder
SET parent_id = 0
WHERE folder.del_flag = '0' AND folder.parent_id <> 0 AND (
    folder.parent_id = folder.id OR NOT EXISTS (
        SELECT 1 FROM mindmap_folder AS parent
        WHERE parent.id = folder.parent_id
          AND parent.owner_id = folder.owner_id
          AND parent.del_flag = '0'
    )
);

WITH ranked AS (
    SELECT id, ROW_NUMBER() OVER (PARTITION BY owner_id, parent_id, name ORDER BY id) AS position
    FROM mindmap_folder WHERE del_flag = '0'
)
UPDATE mindmap_folder AS folder
SET name = LEFT(folder.name, 70) || '〔迁移去重-' || folder.id || '〕'
FROM ranked
WHERE ranked.id = folder.id AND ranked.position > 1;

UPDATE mindmap_tag SET category_id = NULL
WHERE category_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM mindmap_tag_category c WHERE c.id = category_id);
UPDATE mindmap_tag_category SET name = '未命名分类-' || id WHERE BTRIM(name) = '';
WITH canonical AS (
    SELECT owner_id, LOWER(BTRIM(name)) AS normalized_name, MIN(id) AS keep_id
    FROM mindmap_tag_category GROUP BY owner_id, LOWER(BTRIM(name))
)
UPDATE mindmap_tag AS tag
SET category_id = canonical.keep_id
FROM mindmap_tag_category AS category, canonical
WHERE tag.category_id = category.id
  AND canonical.owner_id = category.owner_id
  AND canonical.normalized_name = LOWER(BTRIM(category.name))
  AND category.id <> canonical.keep_id;
DELETE FROM mindmap_tag_category AS category
USING (
    SELECT owner_id, LOWER(BTRIM(name)) AS normalized_name, MIN(id) AS keep_id
    FROM mindmap_tag_category GROUP BY owner_id, LOWER(BTRIM(name))
) AS canonical
WHERE canonical.owner_id = category.owner_id
  AND canonical.normalized_name = LOWER(BTRIM(category.name))
  AND category.id <> canonical.keep_id;
UPDATE mindmap_tag_category SET name = BTRIM(name);

-- Recreate named constraints so an existing constraint with the wrong target or
-- delete policy is repaired rather than silently accepted.
ALTER TABLE mindmap_tag DROP CONSTRAINT IF EXISTS fk_mindmap_tag_category;
ALTER TABLE mindmap_tag ADD CONSTRAINT fk_mindmap_tag_category
    FOREIGN KEY (category_id) REFERENCES mindmap_tag_category(id) ON DELETE RESTRICT;

CREATE INDEX IF NOT EXISTS idx_mindmap_name ON mindmap(name);
CREATE INDEX IF NOT EXISTS idx_mindmap_owner ON mindmap(owner_id, del_flag);
CREATE INDEX IF NOT EXISTS idx_mindmap_owner_folder ON mindmap(owner_id, folder_id, del_flag);
CREATE INDEX IF NOT EXISTS idx_mindmap_owner_status ON mindmap(owner_id, status, del_flag, update_time);
CREATE INDEX IF NOT EXISTS idx_mindmap_archive_cleanup ON mindmap(status, update_time, id);
CREATE INDEX IF NOT EXISTS idx_mindmap_deleted_cleanup ON mindmap(del_flag, update_time, id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_collab_unique ON mindmap_collaborator(mindmap_id, user_id);
CREATE INDEX IF NOT EXISTS idx_collab_user ON mindmap_collaborator(user_id);
CREATE INDEX IF NOT EXISTS idx_share_mindmap ON mindmap_share(mindmap_id);
CREATE INDEX IF NOT EXISTS idx_share_token ON mindmap_share(share_token);
CREATE INDEX IF NOT EXISTS idx_folder_owner ON mindmap_folder(owner_id, del_flag);
CREATE INDEX IF NOT EXISTS idx_folder_parent ON mindmap_folder(parent_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_mindmap_folder_active_sibling ON mindmap_folder(owner_id, parent_id, active_name);
CREATE INDEX IF NOT EXISTS idx_version_mindmap ON mindmap_version(mindmap_id, version_type);
CREATE INDEX IF NOT EXISTS idx_version_time ON mindmap_version(mindmap_id, created_time);
CREATE UNIQUE INDEX IF NOT EXISTS uk_mindmap_node_uid ON mindmap_node(file_id, node_uid);
CREATE INDEX IF NOT EXISTS idx_mindmap_node_parent ON mindmap_node(file_id, parent_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_mindmap_node_deleted ON mindmap_node(file_id, is_deleted);
CREATE UNIQUE INDEX IF NOT EXISTS uk_mindmap_relation_uid ON mindmap_relation(file_id, relation_uid);
CREATE INDEX IF NOT EXISTS idx_mindmap_relation_source ON mindmap_relation(file_id, source_node_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_mindmap_relation_target ON mindmap_relation(file_id, target_node_id);
CREATE UNIQUE INDEX IF NOT EXISTS uk_mindmap_summary_uid ON mindmap_summary(file_id, summary_uid);
CREATE INDEX IF NOT EXISTS idx_mindmap_summary_owner ON mindmap_summary(file_id, owner_node_id, sort_order);
CREATE UNIQUE INDEX IF NOT EXISTS uk_mindmap_group_uid ON mindmap_group(file_id, group_uid);
CREATE INDEX IF NOT EXISTS idx_mindmap_group_parent ON mindmap_group(file_id, parent_node_id);
CREATE UNIQUE INDEX IF NOT EXISTS uk_mindmap_group_member ON mindmap_group_member(group_id, node_id);
CREATE INDEX IF NOT EXISTS idx_mindmap_group_member_order ON mindmap_group_member(group_id, sort_order);
CREATE UNIQUE INDEX IF NOT EXISTS uk_mindmap_asset_key ON mindmap_asset(file_id, asset_key);
CREATE INDEX IF NOT EXISTS idx_mindmap_asset_hash ON mindmap_asset(file_id, sha256);
CREATE UNIQUE INDEX IF NOT EXISTS uk_mindmap_change_revision ON mindmap_change_log(file_id, revision);
CREATE UNIQUE INDEX IF NOT EXISTS uk_mindmap_change_mutation ON mindmap_change_log(file_id, client_mutation_id);
CREATE INDEX IF NOT EXISTS idx_mindmap_change_created ON mindmap_change_log(file_id, created_time);
CREATE INDEX IF NOT EXISTS idx_mindmap_change_retention ON mindmap_change_log(created_time, id);
CREATE UNIQUE INDEX IF NOT EXISTS uk_mindmap_migration_file ON mindmap_migration_record(file_id);
CREATE INDEX IF NOT EXISTS idx_mindmap_migration_batch ON mindmap_migration_record(batch_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS uk_mindmap_creation_owner_request ON mindmap_creation_request(owner_id, request_id);
CREATE INDEX IF NOT EXISTS idx_mindmap_creation_created ON mindmap_creation_request(created_time);
CREATE INDEX IF NOT EXISTS idx_mindmap_creation_result ON mindmap_creation_request(result_file_id);
CREATE INDEX IF NOT EXISTS idx_mindmap_creation_retention ON mindmap_creation_request(completed_time, id);
CREATE INDEX IF NOT EXISTS idx_mindmap_comment_thread_file
    ON mindmap_comment_thread(mindmap_id, status, last_comment_time);
CREATE INDEX IF NOT EXISTS idx_mindmap_comment_thread_node
    ON mindmap_comment_thread(mindmap_id, node_uid, status);
CREATE INDEX IF NOT EXISTS idx_mindmap_comment_thread
    ON mindmap_comment(thread_id, created_time);
CREATE INDEX IF NOT EXISTS idx_mindmap_comment_author
    ON mindmap_comment(created_by, created_time);
CREATE UNIQUE INDEX IF NOT EXISTS uk_mindmap_comment_author_request
    ON mindmap_comment(created_by, client_request_id);
CREATE INDEX IF NOT EXISTS idx_tag_cat_owner ON mindmap_tag_category(owner_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_mindmap_tag_category_owner_name ON mindmap_tag_category(owner_id, name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tag_owner_key ON mindmap_tag(owner_id, tag_key);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tag_uuid ON mindmap_tag(uuid);
CREATE INDEX IF NOT EXISTS idx_tag_category ON mindmap_tag(category_id);
CREATE UNIQUE INDEX IF NOT EXISTS uk_mindmap_node_tag ON mindmap_node_tag(node_id, tag_id);
CREATE INDEX IF NOT EXISTS idx_mindmap_node_tag_usage ON mindmap_node_tag(tag_id, file_id);
CREATE INDEX IF NOT EXISTS idx_mindmap_node_tag_order ON mindmap_node_tag(node_id, sort_order);

-- Keep the legacy menu rows aligned with the controller permission namespace.
UPDATE sys_menu
SET parent_id = 121, update_by = 'migration', update_time = CURRENT_TIMESTAMP
WHERE menu_id = 9010 AND perms = 'mindmap:folder:list' AND parent_id <> 121;
UPDATE sys_menu
SET perms = CASE perms
    WHEN 'mindmap:list' THEN 'mindmap:mindmap:list'
    WHEN 'mindmap:query' THEN 'mindmap:mindmap:query'
    WHEN 'mindmap:add' THEN 'mindmap:mindmap:add'
    WHEN 'mindmap:edit' THEN 'mindmap:mindmap:edit'
    WHEN 'mindmap:remove' THEN 'mindmap:mindmap:remove'
    ELSE perms
END, update_by = 'migration', update_time = CURRENT_TIMESTAMP
WHERE perms IN ('mindmap:list', 'mindmap:query', 'mindmap:add', 'mindmap:edit', 'mindmap:remove');

COMMIT;
