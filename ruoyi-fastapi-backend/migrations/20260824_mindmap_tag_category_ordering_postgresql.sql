-- 标签分组来源类型与拖拽排序支持（PostgreSQL，可重复执行）
DO $$
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

        UPDATE mindmap_tag_category AS c
        SET category_type = 'system'
        WHERE c.owner_id = 0
           OR (
                EXISTS (
                    SELECT 1 FROM mindmap_tag AS t WHERE t.category_id = c.id
                )
                AND NOT EXISTS (
                    SELECT 1 FROM mindmap_tag AS t
                    WHERE t.category_id = c.id AND t.owner_id <> 0
                )
           );

        UPDATE mindmap_tag_category AS c
        SET owner_id = 0
        WHERE c.category_type = 'system'
          AND c.owner_id <> 0
          AND NOT EXISTS (
              SELECT 1
              FROM mindmap_tag_category AS global_category
              WHERE global_category.owner_id = 0
                AND LOWER(global_category.name) = LOWER(c.name)
                AND global_category.id <> c.id
          );
    END IF;
END
$$;

COMMENT ON COLUMN mindmap_tag_category.category_type
    IS '分组类型:system系统 custom用户自定义';
