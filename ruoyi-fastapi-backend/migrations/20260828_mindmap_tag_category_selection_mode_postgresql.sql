-- 标签分组单选/多选模式（PostgreSQL，可重复执行）
DO $$
DECLARE
    needs_backfill BOOLEAN := FALSE;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'mindmap_tag_category'
          AND column_name = 'selection_mode'
    ) THEN
        ALTER TABLE mindmap_tag_category
            ADD COLUMN selection_mode VARCHAR(20) NOT NULL DEFAULT 'multiple';
        needs_backfill := TRUE;
    END IF;

    -- 统一标签迁移可能已经提前补列并保存旧字段的选择模式；只在新列或
    -- 明确待回填时处理系统标记分组，重跑不得覆盖管理员后续设置。
    IF needs_backfill OR EXISTS (
        SELECT 1 FROM pg_catalog.pg_attribute
        WHERE attrelid = 'mindmap_tag_category'::regclass
          AND attname = 'selection_mode'
          AND col_description(attrelid, attnum) = 'migration_pending_20260828_selection_mode'
    ) THEN
        UPDATE mindmap_tag_category
        SET selection_mode = 'single'
        WHERE category_type = 'system'
          AND selection_mode = 'multiple'
          AND EXISTS (
              SELECT 1
              FROM mindmap_tag
              WHERE mindmap_tag.category_id = mindmap_tag_category.id
                AND mindmap_tag.tag_key LIKE 'builtin_marker_%'
          );
    END IF;
END
$$;

COMMENT ON COLUMN mindmap_tag_category.selection_mode
    IS '分组选择模式:single单选 multiple多选';
