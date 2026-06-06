CREATE TABLE IF NOT EXISTS mindmap_collaborator (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    mindmap_id BIGINT NOT NULL COMMENT '脑图ID',
    user_id BIGINT NOT NULL COMMENT '协作用户ID',
    permission SMALLINT NOT NULL DEFAULT 0 COMMENT '0=查看 1=编辑',
    created_by BIGINT NOT NULL COMMENT '添加者用户ID',
    created_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE INDEX idx_collab_unique (mindmap_id, user_id),
    INDEX idx_collab_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='脑图协作者表';
