-- 脑图版本历史表
CREATE TABLE IF NOT EXISTS mindmap_version (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    mindmap_id BIGINT NOT NULL COMMENT '脑图ID',
    version_number INT NOT NULL COMMENT '版本号',
    version_type SMALLINT NOT NULL DEFAULT 0 COMMENT '版本类型: 0=草稿 1=正式',
    name VARCHAR(200) COMMENT '版本名称（仅正式版本）',
    node_tree LONGTEXT NOT NULL COMMENT '节点树快照JSON',
    view_data JSON COMMENT '视图状态快照',
    layout VARCHAR(50) COMMENT '布局类型',
    theme JSON COMMENT '主题配置',
    created_by VARCHAR(64) NOT NULL COMMENT '创建者',
    created_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_version_mindmap (mindmap_id, version_type),
    INDEX idx_version_time (mindmap_id, created_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='脑图版本历史表';
