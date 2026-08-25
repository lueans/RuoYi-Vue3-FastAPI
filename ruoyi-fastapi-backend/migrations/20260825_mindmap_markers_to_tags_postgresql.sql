-- 把 61 个 simple-mind-map 内置节点标记迁移为统一标签（PostgreSQL，可重复执行）

BEGIN;

INSERT INTO mindmap_tag_category (
    name, category_type, owner_id, sort_order, created_by, created_time
) VALUES
    ('优先级', 'system', 0, 100, 'migration', CURRENT_TIMESTAMP),
    ('任务', 'system', 0, 200, 'migration', CURRENT_TIMESTAMP),
    ('表情', 'system', 0, 300, 'migration', CURRENT_TIMESTAMP),
    ('符号', 'system', 0, 400, 'migration', CURRENT_TIMESTAMP)
ON CONFLICT (owner_id, name) DO UPDATE SET category_type = 'system';

WITH marker_group(type_name, category_name, item_count, base_order) AS (
    VALUES
        ('priority', '优先级', 10, 100),
        ('progress', '任务', 8, 200),
        ('expression', '表情', 20, 300),
        ('sign', '符号', 23, 400)
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
      ON category.owner_id = 0 AND category.name = marker_catalog.category_name
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
    '由历史脑图标记“' || icon_key || '”迁移，可在标签管理中统一维护',
    0, 1, 0, 0,
    'migration', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'migration'
FROM marker_source
ON CONFLICT (owner_id, tag_key) DO NOTHING;

WITH marker_group(type_name, item_count) AS (
    VALUES ('priority', 10), ('progress', 8), ('expression', 20), ('sign', 23)
), marker_catalog AS (
    SELECT
        marker_group.type_name || '_' || marker_number.n AS icon_key,
        'builtin_marker_' || marker_group.type_name || '_' || marker_number.n AS tag_key
    FROM marker_group
    CROSS JOIN LATERAL GENERATE_SERIES(1, marker_group.item_count) AS marker_number(n)
), legacy_icons AS (
    SELECT
        node.file_id,
        node.id AS node_id,
        node.create_by,
        node.update_by,
        legacy_icon.icon_key,
        legacy_icon.icon_order
    FROM mindmap_node AS node
    CROSS JOIN LATERAL JSONB_ARRAY_ELEMENTS_TEXT(
        CASE
            WHEN JSONB_TYPEOF(node.content_data -> 'icon') = 'array'
            THEN node.content_data -> 'icon'
            ELSE '[]'::jsonb
        END
    ) WITH ORDINALITY AS legacy_icon(icon_key, icon_order)
    WHERE node.is_deleted = 0
), existing_order AS (
    SELECT node_id, MAX(sort_order) AS max_order
    FROM mindmap_node_tag
    GROUP BY node_id
)
INSERT INTO mindmap_node_tag (
    file_id, node_id, tag_id, sort_order, placement, align, created_by, created_time
)
SELECT
    legacy_icons.file_id,
    legacy_icons.node_id,
    tag.id,
    COALESCE(existing_order.max_order, -1) + legacy_icons.icon_order::integer,
    'right',
    'center',
    COALESCE(legacy_icons.update_by, legacy_icons.create_by, 'migration'),
    CURRENT_TIMESTAMP
FROM legacy_icons
JOIN marker_catalog ON marker_catalog.icon_key = legacy_icons.icon_key
JOIN mindmap_tag AS tag ON tag.owner_id = 0 AND tag.tag_key = marker_catalog.tag_key
LEFT JOIN existing_order ON existing_order.node_id = legacy_icons.node_id
ON CONFLICT (node_id, tag_id) DO NOTHING;

WITH marker_group(type_name, item_count) AS (
    VALUES ('priority', 10), ('progress', 8), ('expression', 20), ('sign', 23)
), marker_icon AS (
    SELECT marker_group.type_name || '_' || marker_number.n AS icon_key
    FROM marker_group
    CROSS JOIN LATERAL GENERATE_SERIES(1, marker_group.item_count) AS marker_number(n)
), rewritten AS (
    SELECT
        node.id,
        COALESCE(
            JSONB_AGG(legacy_icon.icon_key ORDER BY legacy_icon.icon_order)
                FILTER (WHERE marker_icon.icon_key IS NULL),
            '[]'::jsonb
        ) AS remaining_icons
    FROM mindmap_node AS node
    CROSS JOIN LATERAL JSONB_ARRAY_ELEMENTS_TEXT(
        CASE
            WHEN JSONB_TYPEOF(node.content_data -> 'icon') = 'array'
            THEN node.content_data -> 'icon'
            ELSE '[]'::jsonb
        END
    ) WITH ORDINALITY AS legacy_icon(icon_key, icon_order)
    LEFT JOIN marker_icon ON marker_icon.icon_key = legacy_icon.icon_key
    WHERE node.is_deleted = 0
      AND JSONB_TYPEOF(node.content_data -> 'icon') = 'array'
    GROUP BY node.id
)
UPDATE mindmap_node AS node
SET content_data = CASE
    WHEN JSONB_ARRAY_LENGTH(rewritten.remaining_icons) = 0
    THEN node.content_data - 'icon'
    ELSE JSONB_SET(node.content_data, '{icon}', rewritten.remaining_icons)
END
FROM rewritten
WHERE node.id = rewritten.id;

UPDATE mindmap_tag AS tag
SET
    usage_node_count = usage.node_count,
    usage_file_count = usage.file_count
FROM (
    SELECT tag.id AS tag_id, COUNT(binding.id) AS node_count,
           COUNT(DISTINCT binding.file_id) AS file_count
    FROM mindmap_tag AS tag
    LEFT JOIN mindmap_node_tag AS binding ON binding.tag_id = tag.id
    WHERE tag.owner_id = 0 AND tag.tag_key LIKE 'builtin\_marker\_%' ESCAPE '\'
    GROUP BY tag.id
) AS usage
WHERE tag.id = usage.tag_id;

DELETE FROM mindmap_ws_state;

COMMIT;
