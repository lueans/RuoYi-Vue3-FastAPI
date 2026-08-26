-- 脑图节点评论（MySQL 8+，可重复执行）

CREATE TABLE IF NOT EXISTS `mindmap_comment_thread` (
    `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '评论线程ID',
    `mindmap_id` BIGINT NOT NULL COMMENT '脑图ID',
    `node_uid` VARCHAR(64) NOT NULL COMMENT '节点稳定UID',
    `node_text` VARCHAR(500) DEFAULT NULL COMMENT '创建评论时的节点文本快照',
    `status` SMALLINT NOT NULL DEFAULT 0 COMMENT '0待处理 1已解决',
    `created_by` BIGINT NOT NULL COMMENT '线程创建者用户ID',
    `created_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `last_comment_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '最后回复时间',
    `resolved_by` BIGINT DEFAULT NULL COMMENT '解决人用户ID',
    `resolved_time` DATETIME DEFAULT NULL COMMENT '解决时间',
    `del_flag` CHAR(1) NOT NULL DEFAULT '0' COMMENT '删除标志（0存在 2删除）',
    PRIMARY KEY (`id`),
    INDEX `idx_mindmap_comment_thread_file` (`mindmap_id`, `status`, `last_comment_time`),
    INDEX `idx_mindmap_comment_thread_node` (`mindmap_id`, `node_uid`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='脑图评论线程表';

CREATE TABLE IF NOT EXISTS `mindmap_comment` (
    `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '评论消息ID',
    `thread_id` BIGINT NOT NULL COMMENT '评论线程ID',
    `mindmap_id` BIGINT NOT NULL COMMENT '脑图ID',
    `content` TEXT NOT NULL COMMENT '评论内容',
    `created_by` BIGINT NOT NULL COMMENT '评论人用户ID',
    `client_request_id` VARCHAR(100) DEFAULT NULL COMMENT '客户端写入幂等键',
    `created_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `update_time` DATETIME DEFAULT NULL COMMENT '更新时间',
    `del_flag` CHAR(1) NOT NULL DEFAULT '0' COMMENT '删除标志（0存在 2删除）',
    PRIMARY KEY (`id`),
    INDEX `idx_mindmap_comment_thread` (`thread_id`, `created_time`),
    INDEX `idx_mindmap_comment_author` (`created_by`, `created_time`),
    UNIQUE INDEX `uk_mindmap_comment_author_request` (`created_by`, `client_request_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='脑图评论消息表';
