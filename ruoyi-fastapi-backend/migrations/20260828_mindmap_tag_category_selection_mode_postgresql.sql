-- 标签分组单选/多选模式（PostgreSQL，可重复执行）
DO $$
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

        UPDATE mindmap_tag_category
        SET selection_mode = 'single'
        WHERE category_type = 'system'
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
