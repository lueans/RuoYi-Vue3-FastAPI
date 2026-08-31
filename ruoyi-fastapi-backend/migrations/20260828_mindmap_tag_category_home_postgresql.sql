-- 标签分组脑图首页展示开关（PostgreSQL，可重复执行）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'mindmap_tag_category'
          AND column_name = 'show_on_home'
    ) THEN
        ALTER TABLE mindmap_tag_category
            ADD COLUMN show_on_home SMALLINT NOT NULL DEFAULT 0;

        UPDATE mindmap_tag_category
        SET show_on_home = 1
        WHERE category_type = 'system';
    END IF;
END
$$;

COMMENT ON COLUMN mindmap_tag_category.show_on_home
    IS '是否在脑图标签首页展示:0否 1是';
