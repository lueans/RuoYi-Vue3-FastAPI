-- 脑图标签管理表
-- 执行: mysql -u root -proot ruoyi-fastapi < sql/mindmap_tag.sql

-- ============================================================
-- 标签分类表
-- ============================================================
CREATE TABLE IF NOT EXISTS mindmap_tag_category (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '分类ID',
    name VARCHAR(100) NOT NULL COMMENT '分类名称',
    owner_id BIGINT NOT NULL DEFAULT 0 COMMENT '所有者(0=全局)',
    sort_order INT DEFAULT 0 COMMENT '排序',
    created_by VARCHAR(64) DEFAULT NULL COMMENT '创建人',
    created_time DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    INDEX idx_tag_cat_owner (owner_id),
    UNIQUE INDEX uq_mindmap_tag_category_owner_name (owner_id, name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='脑图标签分类表';

-- ============================================================
-- 标签表
-- ============================================================
CREATE TABLE IF NOT EXISTS mindmap_tag (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '标签ID',
    uuid VARCHAR(36) NOT NULL COMMENT 'UUID(自动生成)',
    tag_key VARCHAR(100) NOT NULL COMMENT '标签key(自定义必填)',
    name VARCHAR(200) NOT NULL COMMENT '标签显示名称',
    category_id BIGINT DEFAULT NULL COMMENT '所属分类ID',
    owner_id BIGINT NOT NULL DEFAULT 0 COMMENT '所有者(0=全局)',
    style JSON DEFAULT NULL COMMENT '标签样式 {fill,color,fontSize,radius}',
    description VARCHAR(500) DEFAULT NULL COMMENT '标签描述',
    created_by VARCHAR(64) DEFAULT NULL COMMENT '创建人',
    created_time DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE INDEX idx_tag_uuid (uuid),
    UNIQUE INDEX idx_tag_owner_key (owner_id, tag_key),
    INDEX idx_tag_category (category_id),
    CONSTRAINT fk_mindmap_tag_category
        FOREIGN KEY (category_id) REFERENCES mindmap_tag_category (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='脑图标签表';
