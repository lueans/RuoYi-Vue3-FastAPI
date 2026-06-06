-- 模板分类表
CREATE TABLE IF NOT EXISTS mindmap_template_category (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL COMMENT '分类名称',
    sort_order INT DEFAULT 0 COMMENT '排序',
    created_time DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='脑图模板分类表';

-- mindmap 表新增模板分类字段
ALTER TABLE mindmap ADD COLUMN IF NOT EXISTS template_category_id BIGINT DEFAULT NULL COMMENT '模板分类ID';
