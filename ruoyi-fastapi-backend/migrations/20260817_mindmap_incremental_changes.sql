-- 脑图节点增量保存 Phase 2（MySQL 8+，可重复执行）

DROP PROCEDURE IF EXISTS `add_ws_revision_if_missing`;
DELIMITER $$
CREATE PROCEDURE `add_ws_revision_if_missing`()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'mindmap_ws_state'
          AND COLUMN_NAME = 'content_revision'
    ) THEN
        ALTER TABLE `mindmap_ws_state`
            ADD COLUMN `content_revision` BIGINT NULL
            COMMENT '状态对应的文件内容修订号' AFTER `yjs_state`;
    END IF;
END$$
DELIMITER ;

CALL `add_ws_revision_if_missing`();
DROP PROCEDURE IF EXISTS `add_ws_revision_if_missing`;

CREATE TABLE IF NOT EXISTS `mindmap_change_log` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `file_id` BIGINT NOT NULL,
    `base_revision` BIGINT NOT NULL,
    `revision` BIGINT NOT NULL,
    `client_mutation_id` VARCHAR(100) NOT NULL,
    `operations` JSON NOT NULL,
    `result_data` JSON NULL,
    `created_by` VARCHAR(64) NULL,
    `created_time` DATETIME NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_mindmap_change_revision` (`file_id`, `revision`),
    UNIQUE KEY `uk_mindmap_change_mutation` (`file_id`, `client_mutation_id`),
    KEY `idx_mindmap_change_created` (`file_id`, `created_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='脑图增量变更与幂等日志';
