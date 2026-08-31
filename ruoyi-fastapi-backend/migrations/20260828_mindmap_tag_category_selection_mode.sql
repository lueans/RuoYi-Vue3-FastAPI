-- 标签分组单选/多选模式（MySQL 8+，可重复执行）
--
-- 新字段默认多选，避免改变既有非标记分组行为；系统标记分组的收敛更新
-- 放在加列判断之后，确保 ALTER 隐式提交后即使中断，重跑仍能完成回填。

DROP PROCEDURE IF EXISTS `migrate_mindmap_tag_category_selection_mode`;
DELIMITER $$
CREATE PROCEDURE `migrate_mindmap_tag_category_selection_mode`()
BEGIN
    DECLARE `needs_backfill` BOOLEAN DEFAULT FALSE;

    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'mindmap_tag_category'
          AND COLUMN_NAME = 'selection_mode'
    ) THEN
        ALTER TABLE `mindmap_tag_category`
            ADD COLUMN `selection_mode` VARCHAR(20) NOT NULL DEFAULT 'multiple'
            COMMENT 'migration_pending_20260828_selection_mode'
            AFTER `show_on_home`;
        SET `needs_backfill` = TRUE;
    END IF;

    IF `needs_backfill` OR EXISTS (
        SELECT 1
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'mindmap_tag_category'
          AND COLUMN_NAME = 'selection_mode'
          AND COLUMN_COMMENT = 'migration_pending_20260828_selection_mode'
    ) THEN
        UPDATE `mindmap_tag_category`
        SET `selection_mode` = 'single'
        WHERE `category_type` = 'system'
          AND `selection_mode` = 'multiple'
          AND EXISTS (
              SELECT 1
              FROM `mindmap_tag`
              WHERE `mindmap_tag`.`category_id` = `mindmap_tag_category`.`id`
                AND `mindmap_tag`.`tag_key` LIKE 'builtin_marker_%'
          );

        ALTER TABLE `mindmap_tag_category`
            MODIFY COLUMN `selection_mode` VARCHAR(20) NOT NULL DEFAULT 'multiple'
            COMMENT '分组选择模式:single单选 multiple多选';
    END IF;
END$$
DELIMITER ;

CALL `migrate_mindmap_tag_category_selection_mode`();
DROP PROCEDURE IF EXISTS `migrate_mindmap_tag_category_selection_mode`;
