-- 把 61 个 simple-mind-map 内置节点标记迁移为统一标签（MySQL 8+，可重复执行）
--
-- 标签 Key 固定为 builtin_marker_<iconKey>，style.iconKey 仅允许内置图标白名单。

DROP TEMPORARY TABLE IF EXISTS `tmp_mindmap_marker_catalog`;
CREATE TEMPORARY TABLE `tmp_mindmap_marker_catalog` (
    `icon_key` VARCHAR(40) NOT NULL PRIMARY KEY,
    `tag_key` VARCHAR(100) NOT NULL,
    `category_name` VARCHAR(100) NOT NULL,
    `sort_order` INT NOT NULL
);

INSERT INTO `tmp_mindmap_marker_catalog` (`icon_key`, `tag_key`, `category_name`, `sort_order`)
WITH RECURSIVE marker_number AS (
    SELECT 1 AS n
    UNION ALL SELECT n + 1 FROM marker_number WHERE n < 23
), marker_group AS (
    SELECT 'priority' AS type_name, '优先级' AS category_name, 10 AS item_count, 100 AS base_order
    UNION ALL SELECT 'progress', '任务', 8, 200
    UNION ALL SELECT 'expression', '表情', 20, 300
    UNION ALL SELECT 'sign', '符号', 23, 400
)
SELECT
    CONCAT(marker_group.type_name, '_', marker_number.n),
    CONCAT('builtin_marker_', marker_group.type_name, '_', marker_number.n),
    marker_group.category_name,
    marker_group.base_order + marker_number.n
FROM marker_group
JOIN marker_number ON marker_number.n <= marker_group.item_count;

DROP TEMPORARY TABLE IF EXISTS `tmp_mindmap_marker_categories`;
CREATE TEMPORARY TABLE `tmp_mindmap_marker_categories` (
    `category_name` VARBINARY(400) NOT NULL PRIMARY KEY,
    `category_id` BIGINT NOT NULL
);

-- 历史开发库可能缺少分组唯一索引。先记录每个系统分组最早的主记录，
-- 后续把已有标签引用归并到该记录，保证本迁移不依赖结构索引也可重复执行。
INSERT INTO `tmp_mindmap_marker_categories` (`category_name`, `category_id`)
SELECT
    BINARY category.`name`,
    MIN(category.`id`)
FROM `mindmap_tag_category` AS category
JOIN (
    SELECT `category_name`
    FROM `tmp_mindmap_marker_catalog`
    GROUP BY `category_name`
) AS marker_group
  ON BINARY category.`name` = BINARY marker_group.`category_name`
WHERE category.`owner_id` = 0
GROUP BY BINARY category.`name`;

-- 存储过程 DDL 会隐式提交，因此必须在数据迁移事务开始前创建。
-- 过程执行时会读取当前连接内的临时标记目录。
DROP PROCEDURE IF EXISTS `migrate_mindmap_marker_icon_payload`;
DELIMITER $$
CREATE PROCEDURE `migrate_mindmap_marker_icon_payload`()
BEGIN
    DECLARE affected_rows BIGINT DEFAULT 1;
    WHILE affected_rows > 0 DO
        UPDATE `mindmap_node` AS node
        JOIN `tmp_mindmap_marker_catalog` AS marker
          ON JSON_SEARCH(node.`content_data`, 'one', marker.`icon_key`, NULL, '$.icon[*]') IS NOT NULL
        SET node.`content_data` = JSON_REMOVE(
            node.`content_data`,
            JSON_UNQUOTE(JSON_SEARCH(node.`content_data`, 'one', marker.`icon_key`, NULL, '$.icon[*]'))
        )
        WHERE node.`is_deleted` = 0;
        SET affected_rows = ROW_COUNT();
    END WHILE;

    UPDATE `mindmap_node`
    SET `content_data` = JSON_REMOVE(`content_data`, '$.icon')
    WHERE `is_deleted` = 0
      AND JSON_TYPE(JSON_EXTRACT(`content_data`, '$.icon')) = 'ARRAY'
      AND JSON_LENGTH(JSON_EXTRACT(`content_data`, '$.icon')) = 0;
END$$
DELIMITER ;

START TRANSACTION;

UPDATE `mindmap_tag` AS tag
JOIN `mindmap_tag_category` AS category ON category.`id` = tag.`category_id`
JOIN `tmp_mindmap_marker_categories` AS canonical
  ON BINARY category.`name` = canonical.`category_name`
SET tag.`category_id` = canonical.`category_id`
WHERE category.`owner_id` = 0 AND category.`id` <> canonical.`category_id`;

DELETE category
FROM `mindmap_tag_category` AS category
JOIN `tmp_mindmap_marker_categories` AS canonical
  ON BINARY category.`name` = canonical.`category_name`
WHERE category.`owner_id` = 0 AND category.`id` <> canonical.`category_id`;

INSERT INTO `mindmap_tag_category` (
    `name`, `category_type`, `owner_id`, `sort_order`, `created_by`, `created_time`
)
SELECT
    marker_group.`category_name`,
    'system',
    0,
    MIN(marker_group.`sort_order`) - 1,
    'migration',
    NOW()
FROM `tmp_mindmap_marker_catalog` AS marker_group
WHERE NOT EXISTS (
    SELECT 1
    FROM `mindmap_tag_category` AS existing
    WHERE existing.`owner_id` = 0
      AND BINARY existing.`name` = BINARY marker_group.`category_name`
)
GROUP BY marker_group.`category_name`;

UPDATE `mindmap_tag_category` AS category
JOIN (
    SELECT `category_name`, MIN(`sort_order`) - 1 AS `sort_order`
    FROM `tmp_mindmap_marker_catalog`
    GROUP BY `category_name`
) AS marker_group
  ON BINARY category.`name` = BINARY marker_group.`category_name`
SET
    category.`category_type` = 'system',
    category.`sort_order` = marker_group.`sort_order`
WHERE category.`owner_id` = 0;

INSERT INTO `mindmap_tag` (
    `uuid`, `tag_key`, `name`, `category_id`, `owner_id`, `style`, `description`,
    `status`, `definition_revision`, `usage_node_count`, `usage_file_count`,
    `created_by`, `created_time`, `updated_time`, `update_by`
)
SELECT
    UUID(),
    marker.`tag_key`,
    CONCAT(marker.`category_name`, ' ', SUBSTRING_INDEX(marker.`icon_key`, '_', -1)),
    category.`id`,
    0,
    JSON_OBJECT('iconKey', marker.`icon_key`, 'placement', 'right', 'align', 'center'),
    CONCAT('由历史脑图标记“', marker.`icon_key`, '”迁移，可在标签管理中统一维护'),
    0, 1, 0, 0,
    'migration', NOW(), NOW(), 'migration'
FROM `tmp_mindmap_marker_catalog` AS marker
JOIN `mindmap_tag_category` AS category
  ON category.`owner_id` = 0 AND BINARY category.`name` = BINARY marker.`category_name`
LEFT JOIN `mindmap_tag` AS existing
  ON existing.`owner_id` = 0 AND BINARY existing.`tag_key` = BINARY marker.`tag_key`
WHERE existing.`id` IS NULL
ON DUPLICATE KEY UPDATE
    `tag_key` = VALUES(`tag_key`);

-- 先建立统一标签绑定；重复执行时由 (node_id, tag_id) 唯一键去重。
INSERT IGNORE INTO `mindmap_node_tag` (
    `file_id`, `node_id`, `tag_id`, `sort_order`, `placement`, `align`,
    `created_by`, `created_time`
)
SELECT
    node.`file_id`,
    node.`id`,
    tag.`id`,
    COALESCE(existing.`max_order`, -1) + legacy_icon.`icon_order`,
    'right',
    'center',
    COALESCE(node.`update_by`, node.`create_by`, 'migration'),
    NOW()
FROM `mindmap_node` AS node
JOIN JSON_TABLE(
    CASE
        WHEN JSON_TYPE(JSON_EXTRACT(node.`content_data`, '$.icon')) = 'ARRAY'
        THEN JSON_EXTRACT(node.`content_data`, '$.icon')
        ELSE JSON_ARRAY()
    END,
    '$[*]' COLUMNS (
        `icon_order` FOR ORDINALITY,
        `icon_key` VARCHAR(40) PATH '$'
    )
) AS legacy_icon
JOIN `tmp_mindmap_marker_catalog` AS marker
  ON BINARY marker.`icon_key` = BINARY legacy_icon.`icon_key`
JOIN `mindmap_tag` AS tag
  ON tag.`owner_id` = 0 AND BINARY tag.`tag_key` = BINARY marker.`tag_key`
LEFT JOIN (
    SELECT `node_id`, MAX(`sort_order`) AS `max_order`
    FROM `mindmap_node_tag`
    GROUP BY `node_id`
) AS existing ON existing.`node_id` = node.`id`
WHERE node.`is_deleted` = 0;

-- 每轮从每个节点移除一个已迁移 icon，循环后仍保留未知/扩展图标。
CALL `migrate_mindmap_marker_icon_payload`();

UPDATE `mindmap_tag` AS tag
LEFT JOIN (
    SELECT `tag_id`, COUNT(*) AS `node_count`, COUNT(DISTINCT `file_id`) AS `file_count`
    FROM `mindmap_node_tag`
    GROUP BY `tag_id`
) AS tag_usage ON tag_usage.`tag_id` = tag.`id`
SET
    tag.`usage_node_count` = COALESCE(tag_usage.`node_count`, 0),
    tag.`usage_file_count` = COALESCE(tag_usage.`file_count`, 0)
WHERE tag.`owner_id` = 0 AND tag.`tag_key` LIKE 'builtin\_marker\_%';

-- 协作缓存可从结构化正文重建，避免旧 icon 再次覆盖迁移后的标签绑定。
DELETE FROM `mindmap_ws_state`;

COMMIT;

DROP PROCEDURE IF EXISTS `migrate_mindmap_marker_icon_payload`;
DROP TEMPORARY TABLE IF EXISTS `tmp_mindmap_marker_categories`;
DROP TEMPORARY TABLE IF EXISTS `tmp_mindmap_marker_catalog`;
