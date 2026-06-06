-- 脑图分享链接表
CREATE TABLE IF NOT EXISTS mindmap_share (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    mindmap_id BIGINT NOT NULL COMMENT '脑图ID',
    share_token VARCHAR(64) NOT NULL UNIQUE COMMENT '分享token',
    share_type SMALLINT NOT NULL DEFAULT 0 COMMENT '0=查看 1=编辑',
    expire_time DATETIME COMMENT '过期时间（NULL=永久）',
    created_by BIGINT NOT NULL COMMENT '创建者用户ID',
    created_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_active SMALLINT NOT NULL DEFAULT 1 COMMENT '是否有效',
    INDEX idx_share_token (share_token),
    INDEX idx_share_mindmap (mindmap_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='脑图分享链接表';
