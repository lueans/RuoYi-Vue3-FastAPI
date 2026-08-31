-- 脑图系统标签初始化（PostgreSQL，可重复执行）
--
-- 前置条件：已执行脑图标签表结构迁移。
-- 本脚本只初始化 4 个系统分组和 61 个内置标记标签，
-- 不迁移历史节点数据，也不清理 mindmap_ws_state。

BEGIN;

INSERT INTO mindmap_tag_category (
    name, category_type, show_on_home, selection_mode, owner_id, sort_order, created_by, created_time
) VALUES
    ('优先级', 'system', 1, 'single', 0, 100, 'system', CURRENT_TIMESTAMP),
    ('任务', 'system', 1, 'single', 0, 200, 'system', CURRENT_TIMESTAMP),
    ('表情', 'system', 1, 'single', 0, 300, 'system', CURRENT_TIMESTAMP),
    ('符号', 'system', 1, 'single', 0, 400, 'system', CURRENT_TIMESTAMP)
ON CONFLICT (owner_id, name) DO UPDATE SET
    category_type = EXCLUDED.category_type,
    sort_order = EXCLUDED.sort_order;

WITH marker_group(type_name, category_name, item_count) AS (
    VALUES
        ('priority', '优先级', 10),
        ('progress', '任务', 8),
        ('expression', '表情', 20),
        ('sign', '符号', 23)
), marker_catalog AS (
    SELECT
        marker_group.type_name || '_' || marker_number.n AS icon_key,
        'builtin_marker_' || marker_group.type_name || '_' || marker_number.n AS tag_key,
        marker_group.category_name,
        marker_number.n AS marker_number
    FROM marker_group
    CROSS JOIN LATERAL GENERATE_SERIES(1, marker_group.item_count) AS marker_number(n)
), marker_source AS (
    SELECT
        marker_catalog.*,
        MD5('mindmap-marker-' || marker_catalog.icon_key) AS uuid_hash,
        category.id AS category_id
    FROM marker_catalog
    JOIN mindmap_tag_category AS category
      ON category.owner_id = 0
     AND category.name = marker_catalog.category_name
)
INSERT INTO mindmap_tag (
    uuid, tag_key, name, category_id, owner_id, style, description,
    status, definition_revision, usage_node_count, usage_file_count,
    created_by, created_time, updated_time, update_by
)
SELECT
    SUBSTRING(uuid_hash, 1, 8) || '-' || SUBSTRING(uuid_hash, 9, 4) || '-' ||
    SUBSTRING(uuid_hash, 13, 4) || '-' || SUBSTRING(uuid_hash, 17, 4) || '-' ||
    SUBSTRING(uuid_hash, 21, 12),
    tag_key,
    category_name || ' ' || marker_number,
    category_id,
    0,
    JSONB_BUILD_OBJECT('iconKey', icon_key, 'placement', 'right', 'align', 'center'),
    '系统内置脑图标记“' || icon_key || '”，可在标签管理中统一维护',
    0, 1, 0, 0,
    'system', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'system'
FROM marker_source
ON CONFLICT (owner_id, tag_key) DO NOTHING;

COMMIT;
