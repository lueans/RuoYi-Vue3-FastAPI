-- 标签字段/选项收敛为统一标签（MySQL 8+，可重复执行）
--
-- 执行前应完成数据库备份。本迁移会：
-- 1. 把历史字段建立为标签分类；
-- 2. 为没有统一标签的字段选项创建标签，并物化最终展示样式；
-- 3. 把节点绑定改写为 tag_id，按 (node_id, tag_id) 去重；
-- 4. 删除 mindmap_tag_field、mindmap_tag_field_option 及节点关系上的旧列。

DROP PROCEDURE IF EXISTS `ensure_mindmap_tag_category_type`;
DELIMITER $$
CREATE PROCEDURE `ensure_mindmap_tag_category_type`()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
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
CALL `ensure_mindmap_tag_category_type`();
DROP PROCEDURE IF EXISTS `ensure_mindmap_tag_category_type`;

DROP PROCEDURE IF EXISTS `migrate_mindmap_unified_tags`;
DELIMITER $$
CREATE PROCEDURE `migrate_mindmap_unified_tags`()
BEGIN
    DECLARE v_has_fields INT DEFAULT 0;
    DECLARE v_unresolved_options BIGINT DEFAULT 0;
    DECLARE v_invalid_bindings BIGINT DEFAULT 0;
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    SELECT COUNT(*) INTO v_has_fields
    FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_tag_field';

    IF v_has_fields > 0 THEN
        INSERT IGNORE INTO `mindmap_tag_category` (
            `name`, `category_type`, `owner_id`, `sort_order`, `created_by`, `created_time`
        )
        SELECT
            f.`name`, IF(f.`owner_id` = 0, 'system', 'custom'),
            f.`owner_id`, COALESCE(f.`sort_order`, 0),
            f.`created_by`, COALESCE(f.`created_time`, NOW())
        FROM `mindmap_tag_field` AS f;

        -- 悬空标签或跨所有者错误关联不能继续复用，后续为该选项建立独立标签。
        UPDATE `mindmap_tag_field_option` AS o
        JOIN `mindmap_tag_field` AS f ON f.`id` = o.`field_id`
        LEFT JOIN `mindmap_tag` AS t ON t.`id` = o.`tag_id`
        SET o.`tag_id` = NULL
        WHERE o.`tag_id` IS NOT NULL
          AND (t.`id` IS NULL OR t.`owner_id` != f.`owner_id`);

        -- 优先复用旧运行时已经按字段选项生成的统一标签。
        UPDATE `mindmap_tag_field_option` AS o
        JOIN `mindmap_tag_field` AS f ON f.`id` = o.`field_id`
        JOIN `mindmap_tag` AS t
          ON t.`owner_id` = f.`owner_id`
         AND t.`tag_key` = LEFT(CONCAT('field_', f.`field_key`, '_', o.`option_key`), 100)
        SET o.`tag_id` = t.`id`
        WHERE o.`tag_id` IS NULL;

        -- 剩余选项使用包含数据库主键的稳定 key，避免截断或重名碰撞。
        INSERT IGNORE INTO `mindmap_tag` (
            `uuid`, `tag_key`, `name`, `category_id`, `owner_id`, `style`, `description`,
            `status`, `definition_revision`, `usage_node_count`, `usage_file_count`,
            `created_by`, `created_time`, `updated_time`, `update_by`
        )
        SELECT
            UUID(),
            CONCAT('legacy_field_', f.`id`, '_option_', o.`id`),
            o.`name`,
            c.`id`,
            f.`owner_id`,
            JSON_MERGE_PATCH(
                COALESCE(f.`style`, JSON_OBJECT()),
                IF(o.`fill` IS NULL, JSON_OBJECT(), JSON_OBJECT('fill', o.`fill`)),
                IF(o.`color` IS NULL, JSON_OBJECT(), JSON_OBJECT('color', o.`color`))
            ),
            CONCAT('由历史标签字段“', f.`name`, '”迁移'),
            0, 1, 0, 0,
            f.`created_by`, COALESCE(o.`created_time`, f.`created_time`, NOW()), NOW(), f.`created_by`
        FROM `mindmap_tag_field_option` AS o
        JOIN `mindmap_tag_field` AS f ON f.`id` = o.`field_id`
        LEFT JOIN `mindmap_tag_category` AS c
          ON c.`owner_id` = f.`owner_id` AND c.`name` = f.`name`
        WHERE o.`tag_id` IS NULL;

        UPDATE `mindmap_tag_field_option` AS o
        JOIN `mindmap_tag_field` AS f ON f.`id` = o.`field_id`
        JOIN `mindmap_tag` AS t
          ON t.`owner_id` = f.`owner_id`
         AND t.`tag_key` = CONCAT('legacy_field_', f.`id`, '_option_', o.`id`)
        SET o.`tag_id` = t.`id`
        WHERE o.`tag_id` IS NULL;

        SELECT COUNT(*) INTO v_unresolved_options
        FROM `mindmap_tag_field_option` AS o
        LEFT JOIN `mindmap_tag` AS t ON t.`id` = o.`tag_id`
        WHERE o.`tag_id` IS NULL OR t.`id` IS NULL;
        IF v_unresolved_options > 0 THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = '统一标签迁移中止：存在无法映射的历史字段选项';
        END IF;

        -- 每个标签稳定选择最早的历史选项作为样式来源，避免一对多时更新结果不确定。
        UPDATE `mindmap_tag` AS t
        JOIN (
            SELECT o.`tag_id`, MIN(o.`id`) AS `option_id`
            FROM `mindmap_tag_field_option` AS o
            GROUP BY o.`tag_id`
        ) AS canonical ON canonical.`tag_id` = t.`id`
        JOIN `mindmap_tag_field_option` AS o ON o.`id` = canonical.`option_id`
        JOIN `mindmap_tag_field` AS f ON f.`id` = o.`field_id`
        LEFT JOIN `mindmap_tag_category` AS c
          ON c.`owner_id` = f.`owner_id` AND c.`name` = f.`name`
        SET
            t.`category_id` = COALESCE(t.`category_id`, c.`id`),
            t.`style` = JSON_MERGE_PATCH(
                COALESCE(f.`style`, JSON_OBJECT()),
                COALESCE(t.`style`, JSON_OBJECT()),
                IF(o.`fill` IS NULL, JSON_OBJECT(), JSON_OBJECT('fill', o.`fill`)),
                IF(o.`color` IS NULL, JSON_OBJECT(), JSON_OBJECT('color', o.`color`))
            ),
            t.`updated_time` = NOW();

        -- 同时保留标签默认布局，并把历史节点实际使用的布局固化到绑定上。
        UPDATE `mindmap_node_tag` AS nt
        JOIN `mindmap_tag_field_option` AS o ON o.`id` = nt.`option_id`
        JOIN `mindmap_tag_field` AS f ON f.`id` = o.`field_id`
        SET
            nt.`placement` = COALESCE(
                nt.`placement`, JSON_UNQUOTE(JSON_EXTRACT(f.`style`, '$.placement'))
            ),
            nt.`align` = COALESCE(
                nt.`align`, JSON_UNQUOTE(JSON_EXTRACT(f.`style`, '$.align'))
            );

        SELECT COUNT(*) INTO v_invalid_bindings
        FROM `mindmap_node_tag` AS nt
        LEFT JOIN `mindmap_tag_field_option` AS o ON o.`id` = nt.`option_id`
        LEFT JOIN `mindmap_tag` AS direct_tag ON direct_tag.`id` = nt.`tag_id`
        LEFT JOIN `mindmap_tag` AS option_tag ON option_tag.`id` = o.`tag_id`
        WHERE COALESCE(direct_tag.`id`, option_tag.`id`) IS NULL;
        IF v_invalid_bindings > 0 THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = '统一标签迁移中止：存在无法映射的节点标签绑定';
        END IF;

        DROP TEMPORARY TABLE IF EXISTS `tmp_mindmap_node_tag_unified`;
        CREATE TEMPORARY TABLE `tmp_mindmap_node_tag_unified` AS
        SELECT
            ranked.`id`, ranked.`file_id`, ranked.`node_id`, ranked.`resolved_tag_id` AS `tag_id`,
            ranked.`sort_order`, ranked.`placement`, ranked.`align`,
            ranked.`created_by`, ranked.`created_time`
        FROM (
            SELECT
                resolved.*,
                ROW_NUMBER() OVER (
                    PARTITION BY resolved.`node_id`, resolved.`resolved_tag_id`
                    ORDER BY resolved.`id`
                ) AS `row_number`
            FROM (
                SELECT
                    nt.`id`, nt.`file_id`, nt.`node_id`,
                    COALESCE(direct_tag.`id`, o.`tag_id`) AS `resolved_tag_id`,
                    nt.`sort_order`, nt.`placement`, nt.`align`,
                    nt.`created_by`, nt.`created_time`
                FROM `mindmap_node_tag` AS nt
                LEFT JOIN `mindmap_tag_field_option` AS o ON o.`id` = nt.`option_id`
                LEFT JOIN `mindmap_tag` AS direct_tag ON direct_tag.`id` = nt.`tag_id`
            ) AS resolved
        ) AS ranked
        WHERE ranked.`row_number` = 1;

        DELETE FROM `mindmap_node_tag`;
        INSERT INTO `mindmap_node_tag` (
            `id`, `file_id`, `node_id`, `tag_id`, `sort_order`, `placement`, `align`,
            `created_by`, `created_time`
        )
        SELECT
            `id`, `file_id`, `node_id`, `tag_id`, `sort_order`, `placement`, `align`,
            `created_by`, `created_time`
        FROM `tmp_mindmap_node_tag_unified`;
        DROP TEMPORARY TABLE `tmp_mindmap_node_tag_unified`;
    END IF;

    COMMIT;
END$$
DELIMITER ;

CALL `migrate_mindmap_unified_tags`();
DROP PROCEDURE IF EXISTS `migrate_mindmap_unified_tags`;

-- 协作状态只是同 revision 的可重建缓存，其中可能仍保留仅含 optionId 的旧协议。
-- 统一关系完成后清空缓存，确保下次加入房间从结构化云端正文重新播种。
DELETE FROM `mindmap_ws_state`;

DROP PROCEDURE IF EXISTS `drop_mindmap_legacy_tag_schema`;
DELIMITER $$
CREATE PROCEDURE `drop_mindmap_legacy_tag_schema`()
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_node_tag'
          AND CONSTRAINT_NAME = 'fk_mindmap_node_tag_option'
    ) THEN
        ALTER TABLE `mindmap_node_tag` DROP FOREIGN KEY `fk_mindmap_node_tag_option`;
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_node_tag'
          AND CONSTRAINT_NAME = 'fk_mindmap_node_tag_field'
    ) THEN
        ALTER TABLE `mindmap_node_tag` DROP FOREIGN KEY `fk_mindmap_node_tag_field`;
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_node_tag'
          AND INDEX_NAME = 'idx_mindmap_node_tag_option'
    ) THEN
        ALTER TABLE `mindmap_node_tag` DROP INDEX `idx_mindmap_node_tag_option`;
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_node_tag'
          AND COLUMN_NAME = 'option_id'
    ) THEN
        ALTER TABLE `mindmap_node_tag` DROP COLUMN `option_id`;
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_node_tag'
          AND COLUMN_NAME = 'field_id'
    ) THEN
        ALTER TABLE `mindmap_node_tag` DROP COLUMN `field_id`;
    END IF;
END$$
DELIMITER ;

CALL `drop_mindmap_legacy_tag_schema`();
DROP PROCEDURE IF EXISTS `drop_mindmap_legacy_tag_schema`;

DROP TABLE IF EXISTS `mindmap_tag_field_option`;
DROP TABLE IF EXISTS `mindmap_tag_field`;

UPDATE `mindmap_tag` AS t
LEFT JOIN (
    SELECT `tag_id`, COUNT(*) AS `node_count`, COUNT(DISTINCT `file_id`) AS `file_count`
    FROM `mindmap_node_tag`
    GROUP BY `tag_id`
) AS usage_data ON usage_data.`tag_id` = t.`id`
SET
    t.`usage_node_count` = COALESCE(usage_data.`node_count`, 0),
    t.`usage_file_count` = COALESCE(usage_data.`file_count`, 0);
