-- 标签字段/选项收敛为统一标签（PostgreSQL 14+，可重复执行）
--
-- 执行前应完成数据库备份并停止旧版本应用写入。本迁移会：
-- 1. 把历史字段建立为标签分组；
-- 2. 为没有统一标签的字段选项创建标签，并物化最终展示样式；
-- 3. 把节点绑定规范为 tag_id，按 (node_id, tag_id) 去重；
-- 4. 清空可重建的旧 Yjs 协作缓存；
-- 5. 删除标签字段表以及节点关系上的旧列。

BEGIN;

DO $unified_tags$
DECLARE
    unresolved_options BIGINT := 0;
    invalid_bindings BIGINT := 0;
    binding_sequence TEXT;
    max_binding_id BIGINT;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
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
              SELECT 1
              FROM mindmap_tag_category AS global_category
              WHERE global_category.owner_id = 0
                AND LOWER(global_category.name) = LOWER(category.name)
                AND global_category.id <> category.id
          );
    END IF;

    IF to_regclass('mindmap_tag_field') IS NOT NULL THEN
        IF to_regclass('mindmap_tag_field_option') IS NULL THEN
            RAISE EXCEPTION '统一标签迁移中止：标签字段选项表不存在';
        END IF;

        INSERT INTO mindmap_tag_category (
            name, category_type, owner_id, sort_order, created_by, created_time
        )
        SELECT DISTINCT ON (field.owner_id, field.name)
            field.name,
            CASE WHEN field.owner_id = 0 THEN 'system' ELSE 'custom' END,
            field.owner_id,
            COALESCE(field.sort_order, 0),
            field.created_by,
            COALESCE(field.created_time, CURRENT_TIMESTAMP)
        FROM mindmap_tag_field AS field
        WHERE NOT EXISTS (
            SELECT 1
            FROM mindmap_tag_category AS category
            WHERE category.owner_id = field.owner_id AND category.name = field.name
        )
        ORDER BY field.owner_id, field.name, field.id;

        -- 悬空或跨所有者的旧关联不能继续复用，后续为选项建立独立标签。
        UPDATE mindmap_tag_field_option AS option
        SET tag_id = NULL
        FROM mindmap_tag_field AS field
        WHERE field.id = option.field_id
          AND option.tag_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM mindmap_tag AS tag
              WHERE tag.id = option.tag_id AND tag.owner_id = field.owner_id
          );

        -- 优先复用旧运行时已经按字段选项生成的统一标签。
        UPDATE mindmap_tag_field_option AS option
        SET tag_id = tag.id
        FROM mindmap_tag_field AS field, mindmap_tag AS tag
        WHERE field.id = option.field_id
          AND option.tag_id IS NULL
          AND tag.owner_id = field.owner_id
          AND tag.tag_key = LEFT(
              'field_' || field.field_key || '_' || option.option_key,
              100
          );

        INSERT INTO mindmap_tag (
            uuid, tag_key, name, category_id, owner_id, style, description,
            status, definition_revision, usage_node_count, usage_file_count,
            created_by, created_time, updated_time, update_by
        )
        SELECT
            SUBSTRING(source.uuid_hash, 1, 8) || '-' ||
            SUBSTRING(source.uuid_hash, 9, 4) || '-' ||
            SUBSTRING(source.uuid_hash, 13, 4) || '-' ||
            SUBSTRING(source.uuid_hash, 17, 4) || '-' ||
            SUBSTRING(source.uuid_hash, 21, 12),
            source.tag_key,
            source.option_name,
            source.category_id,
            source.owner_id,
            source.style,
            '由历史标签字段“' || source.field_name || '”迁移',
            0, 1, 0, 0,
            source.created_by,
            source.created_time,
            CURRENT_TIMESTAMP,
            source.created_by
        FROM (
            SELECT
                MD5('mindmap-legacy-field-' || field.id || '-option-' || option.id) AS uuid_hash,
                'legacy_field_' || field.id || '_option_' || option.id AS tag_key,
                option.name AS option_name,
                category.id AS category_id,
                field.owner_id,
                JSONB_STRIP_NULLS(
                    COALESCE(field.style, '{}'::jsonb)
                    || JSONB_BUILD_OBJECT('fill', option.fill, 'color', option.color)
                ) AS style,
                field.name AS field_name,
                field.created_by,
                COALESCE(option.created_time, field.created_time, CURRENT_TIMESTAMP) AS created_time
            FROM mindmap_tag_field_option AS option
            JOIN mindmap_tag_field AS field ON field.id = option.field_id
            LEFT JOIN mindmap_tag_category AS category
              ON category.owner_id = field.owner_id AND category.name = field.name
            WHERE option.tag_id IS NULL
        ) AS source
        WHERE NOT EXISTS (
            SELECT 1 FROM mindmap_tag AS tag
            WHERE tag.owner_id = source.owner_id AND tag.tag_key = source.tag_key
        );

        UPDATE mindmap_tag_field_option AS option
        SET tag_id = tag.id
        FROM mindmap_tag_field AS field, mindmap_tag AS tag
        WHERE field.id = option.field_id
          AND option.tag_id IS NULL
          AND tag.owner_id = field.owner_id
          AND tag.tag_key = 'legacy_field_' || field.id || '_option_' || option.id;

        SELECT COUNT(*) INTO unresolved_options
        FROM mindmap_tag_field_option AS option
        LEFT JOIN mindmap_tag AS tag ON tag.id = option.tag_id
        WHERE option.tag_id IS NULL OR tag.id IS NULL;
        IF unresolved_options > 0 THEN
            RAISE EXCEPTION '统一标签迁移中止：存在 % 个无法映射的历史字段选项',
                unresolved_options;
        END IF;

        -- 每个标签稳定选取最早的历史选项作为样式来源。
        UPDATE mindmap_tag AS tag
        SET
            category_id = COALESCE(tag.category_id, source.category_id),
            style = JSONB_STRIP_NULLS(
                COALESCE(source.field_style, '{}'::jsonb)
                || COALESCE(tag.style, '{}'::jsonb)
                || JSONB_BUILD_OBJECT('fill', source.option_fill, 'color', source.option_color)
            ),
            updated_time = CURRENT_TIMESTAMP
        FROM (
            SELECT DISTINCT ON (option.tag_id)
                option.tag_id,
                option.fill AS option_fill,
                option.color AS option_color,
                field.style AS field_style,
                category.id AS category_id
            FROM mindmap_tag_field_option AS option
            JOIN mindmap_tag_field AS field ON field.id = option.field_id
            LEFT JOIN mindmap_tag_category AS category
              ON category.owner_id = field.owner_id AND category.name = field.name
            ORDER BY option.tag_id, option.id
        ) AS source
        WHERE tag.id = source.tag_id;

        UPDATE mindmap_node_tag AS binding
        SET
            placement = COALESCE(binding.placement, field.style ->> 'placement'),
            align = COALESCE(binding.align, field.style ->> 'align')
        FROM mindmap_tag_field_option AS option, mindmap_tag_field AS field
        WHERE option.id = binding.option_id AND field.id = option.field_id;

        SELECT COUNT(*) INTO invalid_bindings
        FROM mindmap_node_tag AS binding
        LEFT JOIN mindmap_tag_field_option AS option ON option.id = binding.option_id
        LEFT JOIN mindmap_tag AS direct_tag ON direct_tag.id = binding.tag_id
        LEFT JOIN mindmap_tag AS option_tag ON option_tag.id = option.tag_id
        WHERE direct_tag.id IS NULL AND option_tag.id IS NULL;
        IF invalid_bindings > 0 THEN
            RAISE EXCEPTION '统一标签迁移中止：存在 % 个无法映射的节点标签绑定',
                invalid_bindings;
        END IF;

        DROP TABLE IF EXISTS tmp_mindmap_node_tag_unified;
        CREATE TEMPORARY TABLE tmp_mindmap_node_tag_unified ON COMMIT DROP AS
        WITH resolved AS (
            SELECT
                binding.id,
                binding.file_id,
                binding.node_id,
                COALESCE(direct_tag.id, option.tag_id) AS resolved_tag_id,
                binding.sort_order,
                binding.placement,
                binding.align,
                binding.created_by,
                binding.created_time
            FROM mindmap_node_tag AS binding
            LEFT JOIN mindmap_tag_field_option AS option ON option.id = binding.option_id
            LEFT JOIN mindmap_tag AS direct_tag ON direct_tag.id = binding.tag_id
        )
        SELECT DISTINCT ON (node_id, resolved_tag_id)
            id, file_id, node_id, resolved_tag_id AS tag_id, sort_order,
            placement, align, created_by, created_time
        FROM resolved
        ORDER BY node_id, resolved_tag_id, id;

        DELETE FROM mindmap_node_tag;
        INSERT INTO mindmap_node_tag (
            id, file_id, node_id, tag_id, sort_order, placement, align,
            created_by, created_time
        )
        SELECT
            id, file_id, node_id, tag_id, sort_order, placement, align,
            created_by, created_time
        FROM tmp_mindmap_node_tag_unified;

        SELECT PG_GET_SERIAL_SEQUENCE('mindmap_node_tag', 'id') INTO binding_sequence;
        SELECT MAX(id) INTO max_binding_id FROM mindmap_node_tag;
        IF binding_sequence IS NOT NULL THEN
            IF max_binding_id IS NULL THEN
                PERFORM SETVAL(binding_sequence, 1, FALSE);
            ELSE
                PERFORM SETVAL(binding_sequence, max_binding_id, TRUE);
            END IF;
        END IF;
    END IF;

    -- 旧协作状态可能仍携带仅有 optionId 的节点标签；缓存可从云端正文重建。
    IF to_regclass('mindmap_ws_state') IS NOT NULL THEN
        DELETE FROM mindmap_ws_state;
    END IF;

    IF to_regclass('mindmap_node_tag') IS NOT NULL THEN
        ALTER TABLE mindmap_node_tag DROP CONSTRAINT IF EXISTS fk_mindmap_node_tag_option;
        ALTER TABLE mindmap_node_tag DROP CONSTRAINT IF EXISTS fk_mindmap_node_tag_field;
        DROP INDEX IF EXISTS idx_mindmap_node_tag_option;
        ALTER TABLE mindmap_node_tag DROP COLUMN IF EXISTS option_id;
        ALTER TABLE mindmap_node_tag DROP COLUMN IF EXISTS field_id;
    END IF;

    DROP TABLE IF EXISTS mindmap_tag_field_option;
    DROP TABLE IF EXISTS mindmap_tag_field;

    UPDATE mindmap_tag
    SET usage_node_count = 0, usage_file_count = 0;
    UPDATE mindmap_tag AS tag
    SET
        usage_node_count = usage.node_count,
        usage_file_count = usage.file_count
    FROM (
        SELECT tag_id, COUNT(*) AS node_count, COUNT(DISTINCT file_id) AS file_count
        FROM mindmap_node_tag
        GROUP BY tag_id
    ) AS usage
    WHERE tag.id = usage.tag_id;
END
$unified_tags$;

COMMIT;
