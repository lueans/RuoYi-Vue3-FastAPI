-- 标签分组脑图首页展示开关（MySQL 8+，可重复执行）
--
-- 新字段默认关闭，避免既有自定义分组突然占用脑图侧栏；系统分组的收敛
-- 更新放在加列判断之后，确保 ALTER 隐式提交后即使中断，重跑仍能完成回填。

DROP PROCEDURE IF EXISTS `migrate_mindmap_tag_category_home`;
DELIMITER $$
CREATE PROCEDURE `migrate_mindmap_tag_category_home`()
BEGIN
    DECLARE `needs_backfill` BOOLEAN DEFAULT FALSE;

    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'mindmap_tag_category'
          AND COLUMN_NAME = 'show_on_home'
    ) THEN
        ALTER TABLE `mindmap_tag_category`
            ADD COLUMN `show_on_home` SMALLINT NOT NULL DEFAULT 0
            COMMENT 'migration_pending_20260828_home'
            AFTER `category_type`;
        SET `needs_backfill` = TRUE;
    END IF;

    IF `needs_backfill` OR EXISTS (
        SELECT 1
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'mindmap_tag_category'
          AND COLUMN_NAME = 'show_on_home'
          AND COLUMN_COMMENT = 'migration_pending_20260828_home'
    ) THEN
        UPDATE `mindmap_tag_category`
        SET `show_on_home` = 1
        WHERE `category_type` = 'system'
          AND `show_on_home` = 0;

        ALTER TABLE `mindmap_tag_category`
            MODIFY COLUMN `show_on_home` SMALLINT NOT NULL DEFAULT 0
            COMMENT '是否在脑图标签首页展示:0否 1是';
    END IF;
END$$
DELIMITER ;

CALL `migrate_mindmap_tag_category_home`();
DROP PROCEDURE IF EXISTS `migrate_mindmap_tag_category_home`;
