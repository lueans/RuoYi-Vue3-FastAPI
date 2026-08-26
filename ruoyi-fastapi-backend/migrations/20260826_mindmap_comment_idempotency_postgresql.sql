-- 脑图评论写入幂等（PostgreSQL 14+，可重复执行）

BEGIN;

ALTER TABLE mindmap_comment
    ADD COLUMN IF NOT EXISTS client_request_id VARCHAR(100);

DO $$
DECLARE
    existing_unique BOOLEAN;
    existing_columns TEXT[];
BEGIN
    SELECT index_row.indisunique,
           array_agg(attribute.attname ORDER BY key_column.ordinality)
      INTO existing_unique, existing_columns
      FROM pg_class AS index_class
      JOIN pg_index AS index_row
        ON index_row.indexrelid = index_class.oid
      JOIN pg_class AS table_class
        ON table_class.oid = index_row.indrelid
      JOIN pg_namespace AS namespace
        ON namespace.oid = table_class.relnamespace
      JOIN LATERAL unnest(index_row.indkey) WITH ORDINALITY
        AS key_column(attnum, ordinality) ON TRUE
      JOIN pg_attribute AS attribute
        ON attribute.attrelid = table_class.oid
       AND attribute.attnum = key_column.attnum
     WHERE namespace.nspname = current_schema()
       AND table_class.relname = 'mindmap_comment'
       AND index_class.relname = 'uk_mindmap_comment_author_request'
     GROUP BY index_row.indisunique;

    IF existing_columns IS NOT NULL AND NOT (
        existing_unique
        AND existing_columns = ARRAY['created_by', 'client_request_id']::TEXT[]
    ) THEN
        DROP INDEX uk_mindmap_comment_author_request;
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uk_mindmap_comment_author_request
    ON mindmap_comment (created_by, client_request_id);

COMMENT ON COLUMN mindmap_comment.client_request_id IS '客户端写入幂等键';

COMMIT;
