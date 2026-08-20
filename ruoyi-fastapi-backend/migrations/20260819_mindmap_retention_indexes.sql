-- 脑图保留维护扫描索引（MySQL 8+，可重复执行并收敛错误定义）

DROP PROCEDURE IF EXISTS `ensure_mindmap_retention_indexes`;
DELIMITER $$
CREATE PROCEDURE `ensure_mindmap_retention_indexes`()
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'mindmap_creation_request'
          AND INDEX_NAME = 'idx_mindmap_creation_retention'
    ) AND NOT (
        SELECT COUNT(*) = 2
           AND SUM(CASE WHEN SEQ_IN_INDEX = 1 AND COLUMN_NAME = 'completed_time' THEN 1 ELSE 0 END) = 1
           AND SUM(CASE WHEN SEQ_IN_INDEX = 2 AND COLUMN_NAME = 'id' THEN 1 ELSE 0 END) = 1
           AND MAX(NON_UNIQUE) = 1
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'mindmap_creation_request'
          AND INDEX_NAME = 'idx_mindmap_creation_retention'
    ) THEN
        ALTER TABLE `mindmap_creation_request` DROP INDEX `idx_mindmap_creation_retention`;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'mindmap_creation_request'
          AND INDEX_NAME = 'idx_mindmap_creation_retention'
    ) THEN
        ALTER TABLE `mindmap_creation_request`
            ADD INDEX `idx_mindmap_creation_retention` (`completed_time`, `id`);
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'mindmap_change_log'
          AND INDEX_NAME = 'idx_mindmap_change_retention'
    ) AND NOT (
        SELECT COUNT(*) = 2
           AND SUM(CASE WHEN SEQ_IN_INDEX = 1 AND COLUMN_NAME = 'created_time' THEN 1 ELSE 0 END) = 1
           AND SUM(CASE WHEN SEQ_IN_INDEX = 2 AND COLUMN_NAME = 'id' THEN 1 ELSE 0 END) = 1
           AND MAX(NON_UNIQUE) = 1
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'mindmap_change_log'
          AND INDEX_NAME = 'idx_mindmap_change_retention'
    ) THEN
        ALTER TABLE `mindmap_change_log` DROP INDEX `idx_mindmap_change_retention`;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'mindmap_change_log'
          AND INDEX_NAME = 'idx_mindmap_change_retention'
    ) THEN
        ALTER TABLE `mindmap_change_log`
            ADD INDEX `idx_mindmap_change_retention` (`created_time`, `id`);
    END IF;
END$$
DELIMITER ;

CALL `ensure_mindmap_retention_indexes`();
DROP PROCEDURE IF EXISTS `ensure_mindmap_retention_indexes`;
