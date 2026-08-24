-- 标签分组来源类型与拖拽排序支持（MySQL 8+，可重复执行）
--
-- 既有全局分组，以及仅承载全局标签的历史分组，首次加列时标记为 system；
-- 后者在无同名冲突时同时修正为全局所有者。其余分组及后续新建分组保持 custom。
-- sort_order 已存在，由排序接口批量维护。

DROP PROCEDURE IF EXISTS `migrate_mindmap_tag_category_ordering`;
DELIMITER $$
CREATE PROCEDURE `migrate_mindmap_tag_category_ordering`()
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'mindmap_tag_category'
          AND COLUMN_NAME = 'category_type'
    ) THEN
        ALTER TABLE `mindmap_tag_category`
            ADD COLUMN `category_type` VARCHAR(20) NOT NULL DEFAULT 'custom'
            COMMENT '分组类型:system系统 custom用户自定义'
            AFTER `name`;

        UPDATE `mindmap_tag_category` AS c
        SET c.`category_type` = 'system'
        WHERE c.`owner_id` = 0
           OR (
                EXISTS (
                    SELECT 1 FROM `mindmap_tag` AS t
                    WHERE t.`category_id` = c.`id`
                )
                AND NOT EXISTS (
                    SELECT 1 FROM `mindmap_tag` AS t
                    WHERE t.`category_id` = c.`id` AND t.`owner_id` <> 0
                )
           );

        UPDATE `mindmap_tag_category` AS c
        LEFT JOIN `mindmap_tag_category` AS global_category
          ON global_category.`owner_id` = 0
         AND LOWER(global_category.`name`) = LOWER(c.`name`)
         AND global_category.`id` <> c.`id`
        SET c.`owner_id` = 0
        WHERE c.`category_type` = 'system'
          AND c.`owner_id` <> 0
          AND global_category.`id` IS NULL;
    END IF;
END$$
DELIMITER ;

CALL `migrate_mindmap_tag_category_ordering`();
DROP PROCEDURE IF EXISTS `migrate_mindmap_tag_category_ordering`;
