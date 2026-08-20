-- 脑图创建请求服务端幂等（MySQL 8+，可重复执行）
-- 不保存原始请求正文，只保存规范化意图摘要和最终文件 ID。

CREATE TABLE IF NOT EXISTS `mindmap_creation_request` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `owner_id` BIGINT NOT NULL,
    `request_id` VARCHAR(100) NOT NULL,
    `operation` VARCHAR(32) NOT NULL,
    `request_fingerprint` CHAR(64) NOT NULL,
    `result_file_id` BIGINT NULL,
    `created_by` VARCHAR(64) NULL,
    `created_time` DATETIME NOT NULL,
    `completed_time` DATETIME NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_mindmap_creation_owner_request` (`owner_id`, `request_id`),
    KEY `idx_mindmap_creation_result` (`result_file_id`),
    KEY `idx_mindmap_creation_created` (`created_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='脑图创建请求幂等记录';
