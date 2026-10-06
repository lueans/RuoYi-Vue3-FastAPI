-- 脑图完整版本配置快照（PostgreSQL，可重复执行）。
-- 历史行保留 NULL：不能用当前文件配置伪造历史快照。
ALTER TABLE mindmap_version ADD COLUMN IF NOT EXISTS document_data JSONB;
COMMENT ON COLUMN mindmap_version.document_data IS '文档级扩展配置快照，NULL 表示旧版本未记录';
