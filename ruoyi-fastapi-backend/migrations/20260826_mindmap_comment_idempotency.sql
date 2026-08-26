-- 脑图评论写入幂等（MySQL 8+，可重复执行）
-- 同一用户重试相同 Idempotency-Key 时只保留一条评论消息。

DROP PROCEDURE IF EXISTS `ensure_mindmap_comment_idempotency`;
DELIMITER $$
CREATE PROCEDURE `ensure_mindmap_comment_idempotency`()
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = 'mindmap_comment'
          AND column_name = 'client_request_id'
    ) THEN
        ALTER TABLE `mindmap_comment`
            ADD COLUMN `client_request_id` VARCHAR(100) NULL
            COMMENT '客户端写入幂等键' AFTER `created_by`;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name = 'mindmap_comment'
          AND index_name = 'uk_mindmap_comment_author_request'
    ) AND NOT EXISTS (
        SELECT index_name
        FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name = 'mindmap_comment'
          AND index_name = 'uk_mindmap_comment_author_request'
        GROUP BY index_name
        HAVING GROUP_CONCAT(column_name ORDER BY seq_in_index SEPARATOR ',') =
                   'created_by,client_request_id'
           AND MIN(non_unique) = 0
    ) THEN
        ALTER TABLE `mindmap_comment`
            DROP INDEX `uk_mindmap_comment_author_request`;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name = 'mindmap_comment'
          AND index_name = 'uk_mindmap_comment_author_request'
    ) THEN
        ALTER TABLE `mindmap_comment`
            ADD UNIQUE INDEX `uk_mindmap_comment_author_request`
            (`created_by`, `client_request_id`);
    END IF;
END$$
DELIMITER ;

CALL `ensure_mindmap_comment_idempotency`();
DROP PROCEDURE IF EXISTS `ensure_mindmap_comment_idempotency`;
