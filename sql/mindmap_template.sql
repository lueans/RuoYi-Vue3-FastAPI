-- 模板分类表
CREATE TABLE IF NOT EXISTS mindmap_template_category (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL COMMENT '分类名称',
    sort_order INT DEFAULT 0 COMMENT '排序',
    created_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_mindmap_template_category_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='脑图模板分类表';

-- mindmap 表新增模板分类字段
ALTER TABLE mindmap ADD COLUMN IF NOT EXISTS template_category_id BIGINT DEFAULT NULL COMMENT '模板分类ID';
ALTER TABLE mindmap ADD INDEX idx_mindmap_template_market (is_template, del_flag, template_category_id, create_time);
ALTER TABLE mindmap ADD CONSTRAINT fk_mindmap_template_category
    FOREIGN KEY (template_category_id) REFERENCES mindmap_template_category (id)
    ON DELETE RESTRICT ON UPDATE RESTRICT;
