-- 脑图系统标签初始化（MySQL 8+，可重复执行）
--
-- 前置条件：
--   1. 已执行脑图标签表结构迁移；
--   2. mindmap_tag_category 已包含 category_type、sort_order；
--   3. mindmap_tag 已包含 status、definition_revision、usage_* 字段。
--
-- 本脚本只初始化 4 个系统分组和 61 个内置标记标签，
-- 不迁移历史节点数据，也不清理 mindmap_ws_state。

START TRANSACTION;

INSERT INTO mindmap_tag_category (
    name, category_type, owner_id, sort_order, created_by, created_time
) VALUES
    ('优先级', 'system', 0, 100, 'system', NOW()),
    ('任务', 'system', 0, 200, 'system', NOW()),
    ('表情', 'system', 0, 300, 'system', NOW()),
    ('符号', 'system', 0, 400, 'system', NOW())
ON DUPLICATE KEY UPDATE
    category_type = VALUES(category_type),
    sort_order = VALUES(sort_order);

INSERT INTO mindmap_tag (
    uuid, tag_key, name, category_id, owner_id, style, description,
    status, definition_revision, usage_node_count, usage_file_count,
    created_by, created_time, updated_time, update_by
)
WITH RECURSIVE marker_number AS (
    SELECT 1 AS n
    UNION ALL SELECT n + 1 FROM marker_number WHERE n < 23
), marker_group AS (
    SELECT 'priority' AS type_name, '优先级' AS category_name, 10 AS item_count
    UNION ALL SELECT 'progress', '任务', 8
    UNION ALL SELECT 'expression', '表情', 20
    UNION ALL SELECT 'sign', '符号', 23
), marker_catalog AS (
    SELECT
        CONCAT(marker_group.type_name, '_', marker_number.n) AS icon_key,
        CONCAT('builtin_marker_', marker_group.type_name, '_', marker_number.n) AS tag_key,
        marker_group.category_name,
        marker_number.n AS marker_number
    FROM marker_group
    JOIN marker_number ON marker_number.n <= marker_group.item_count
), marker_source AS (
    SELECT
        marker_catalog.*,
        MD5(CONCAT('mindmap-marker-', marker_catalog.icon_key)) AS uuid_hash,
        category.id AS category_id
    FROM marker_catalog
    JOIN mindmap_tag_category AS category
      ON category.owner_id = 0
     AND BINARY category.name = BINARY marker_catalog.category_name
)
SELECT
    CONCAT(
        SUBSTRING(uuid_hash, 1, 8), '-',
        SUBSTRING(uuid_hash, 9, 4), '-',
        SUBSTRING(uuid_hash, 13, 4), '-',
        SUBSTRING(uuid_hash, 17, 4), '-',
        SUBSTRING(uuid_hash, 21, 12)
    ),
    tag_key,
    CONCAT(category_name, ' ', marker_number),
    category_id,
    0,
    JSON_OBJECT('iconKey', icon_key, 'placement', 'right', 'align', 'center'),
    CONCAT('系统内置脑图标记“', icon_key, '”，可在标签管理中统一维护'),
    0, 1, 0, 0,
    'system', NOW(), NOW(), 'system'
FROM marker_source
ON DUPLICATE KEY UPDATE
    tag_key = VALUES(tag_key);

COMMIT;
