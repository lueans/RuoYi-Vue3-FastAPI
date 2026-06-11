-- 脑图标签字段管理表
-- 执行: mysql -u root -proot ruoyi-fastapi < sql/mindmap_tag_field.sql

-- ============================================================
-- 标签字段表（替换 mindmap_tag_category）
-- ============================================================
CREATE TABLE IF NOT EXISTS mindmap_tag_field (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '字段ID',
    field_key VARCHAR(100) NOT NULL COMMENT '字段key(英文/数字/下划线)',
    name VARCHAR(100) NOT NULL COMMENT '字段显示名称',
    select_mode VARCHAR(10) NOT NULL DEFAULT 'single' COMMENT '选择模式: single/multi',
    style JSON DEFAULT NULL COMMENT '基础样式 {fontSize,radius,paddingX,placement,align}',
    owner_id BIGINT NOT NULL DEFAULT 0 COMMENT '所有者(0=全局)',
    sort_order INT DEFAULT 0 COMMENT '排序',
    description VARCHAR(500) DEFAULT NULL COMMENT '字段描述',
    created_by VARCHAR(64) DEFAULT NULL COMMENT '创建人',
    created_time DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE INDEX idx_tag_field_owner_key (owner_id, field_key),
    INDEX idx_tag_field_owner (owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='脑图标签字段表';

-- ============================================================
-- 标签字段选项表（替换 mindmap_tag）
-- ============================================================
CREATE TABLE IF NOT EXISTS mindmap_tag_field_option (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '选项ID',
    field_id BIGINT NOT NULL COMMENT '所属字段ID',
    option_key VARCHAR(100) NOT NULL COMMENT '选项key(字段内唯一)',
    name VARCHAR(200) NOT NULL COMMENT '选项显示名称',
    fill VARCHAR(20) DEFAULT NULL COMMENT '背景色',
    color VARCHAR(20) DEFAULT NULL COMMENT '文字色',
    sort_order INT DEFAULT 0 COMMENT '排序',
    created_time DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    UNIQUE INDEX idx_tag_option_field_key (field_id, option_key),
    INDEX idx_tag_option_field (field_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='脑图标签字段选项表';
