-- 脑图结构化内容 Phase 1（MySQL 8+，可重复执行）
--
-- 兼容策略：现有 mindmap 表在本阶段承担 mindmap_file 的职责，node_tree 保留为
-- 回退快照。完成灰度和停止旧代码写入后，再单独执行物理重命名。

DROP PROCEDURE IF EXISTS `add_column_if_missing`;
DROP PROCEDURE IF EXISTS `ensure_index_definition`;
DELIMITER $$
CREATE PROCEDURE `add_column_if_missing`(
    IN p_table VARCHAR(64), IN p_column VARCHAR(64), IN p_definition TEXT
)
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = p_table AND COLUMN_NAME = p_column
    ) THEN
        SET @ddl = CONCAT('ALTER TABLE `', p_table, '` ADD COLUMN `', p_column, '` ', p_definition);
        PREPARE stmt FROM @ddl;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
    END IF;
END$$

CREATE PROCEDURE `ensure_index_definition`(
    IN p_table VARCHAR(64),
    IN p_index VARCHAR(64),
    IN p_columns VARCHAR(500),
    IN p_non_unique SMALLINT,
    IN p_definition TEXT
)
BEGIN
    DECLARE v_existing INT DEFAULT 0;
    DECLARE v_matching INT DEFAULT 0;

    SELECT COUNT(*) INTO v_existing
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = p_table AND INDEX_NAME = p_index;

    SELECT COUNT(*) INTO v_matching
    FROM (
        SELECT INDEX_NAME
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = p_table AND INDEX_NAME = p_index
        GROUP BY INDEX_NAME
        HAVING GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX SEPARATOR ',') = p_columns
           AND MIN(NON_UNIQUE) = p_non_unique
    ) AS matching_index;

    IF v_matching = 0 THEN
        IF v_existing > 0 THEN
            SET @ddl = CONCAT('ALTER TABLE `', p_table, '` DROP INDEX `', p_index, '`');
            PREPARE stmt FROM @ddl;
            EXECUTE stmt;
            DEALLOCATE PREPARE stmt;
        END IF;
        SET @ddl = CONCAT('ALTER TABLE `', p_table, '` ADD INDEX `', p_index, '` ', p_definition);
        PREPARE stmt FROM @ddl;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
    END IF;
END$$
DELIMITER ;

CALL `add_column_if_missing`('mindmap', 'root_node_id', 'BIGINT NULL COMMENT ''结构化根节点ID'' AFTER `node_tree`');
CALL `add_column_if_missing`('mindmap', 'content_revision', 'BIGINT NOT NULL DEFAULT 1 COMMENT ''内容修订号'' AFTER `root_node_id`');
CALL `add_column_if_missing`('mindmap', 'node_count', 'INT NOT NULL DEFAULT 0 COMMENT ''有效节点数量'' AFTER `content_revision`');
CALL `add_column_if_missing`('mindmap', 'schema_version', 'INT NOT NULL DEFAULT 1 COMMENT ''内容模型版本'' AFTER `node_count`');
CALL `add_column_if_missing`('mindmap', 'engine_name', 'VARCHAR(50) NOT NULL DEFAULT ''simple-mind-map'' COMMENT ''脑图引擎'' AFTER `schema_version`');
CALL `add_column_if_missing`('mindmap', 'engine_version', 'VARCHAR(100) NULL COMMENT ''脑图引擎版本'' AFTER `engine_name`');
CALL `add_column_if_missing`('mindmap', 'document_data', 'JSON NULL COMMENT ''文档级扩展配置'' AFTER `engine_version`');

CALL `add_column_if_missing`('mindmap_tag', 'status', 'SMALLINT NOT NULL DEFAULT 0 COMMENT ''状态:0启用 1停用 2归档''');
CALL `add_column_if_missing`('mindmap_tag', 'definition_revision', 'BIGINT NOT NULL DEFAULT 1 COMMENT ''定义修订号''');
CALL `add_column_if_missing`('mindmap_tag', 'usage_node_count', 'BIGINT NOT NULL DEFAULT 0 COMMENT ''使用节点数缓存''');
CALL `add_column_if_missing`('mindmap_tag', 'usage_file_count', 'BIGINT NOT NULL DEFAULT 0 COMMENT ''使用文件数缓存''');
CALL `add_column_if_missing`('mindmap_tag', 'update_by', 'VARCHAR(64) NULL COMMENT ''最后修改人''');

CALL `add_column_if_missing`('mindmap_tag_field_option', 'tag_id', 'BIGINT NULL COMMENT ''关联的统一标签ID'' AFTER `field_id`');
CALL `ensure_index_definition`(
    'mindmap_tag_field_option', 'idx_tag_option_tag', 'tag_id', 1, '(`tag_id`)'
);

CREATE TABLE IF NOT EXISTS `mindmap_node` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `file_id` BIGINT NOT NULL,
    `node_uid` VARCHAR(64) NOT NULL,
    `parent_id` BIGINT NULL,
    `sort_order` INT NOT NULL DEFAULT 0,
    `text_content` LONGTEXT NULL,
    `text_plain` TEXT NULL,
    `text_format` VARCHAR(16) NOT NULL DEFAULT 'plain',
    `is_expanded` SMALLINT NOT NULL DEFAULT 1,
    `direction` VARCHAR(16) NULL,
    `custom_left` DOUBLE NULL,
    `custom_top` DOUBLE NULL,
    `custom_text_width` DOUBLE NULL,
    `content_data` JSON NULL,
    `style_data` JSON NULL,
    `extension_data` JSON NULL,
    `envelope_data` JSON NULL,
    `payload_schema_version` INT NOT NULL DEFAULT 1,
    `node_revision` BIGINT NOT NULL DEFAULT 1,
    `is_deleted` SMALLINT NOT NULL DEFAULT 0,
    `deleted_time` DATETIME NULL,
    `create_by` VARCHAR(64) NULL,
    `create_time` DATETIME NULL,
    `update_by` VARCHAR(64) NULL,
    `update_time` DATETIME NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_mindmap_node_uid` (`file_id`, `node_uid`),
    KEY `idx_mindmap_node_parent` (`file_id`, `parent_id`, `sort_order`),
    KEY `idx_mindmap_node_deleted` (`file_id`, `is_deleted`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='脑图节点表';

CREATE TABLE IF NOT EXISTS `mindmap_relation` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `relation_uid` VARCHAR(96) NOT NULL,
    `file_id` BIGINT NOT NULL,
    `relation_type` VARCHAR(32) NOT NULL DEFAULT 'associative_line',
    `source_node_id` BIGINT NOT NULL,
    `target_node_id` BIGINT NOT NULL,
    `text` LONGTEXT NULL,
    `control_data` JSON NULL,
    `style_data` JSON NULL,
    `sort_order` INT NOT NULL DEFAULT 0,
    `revision` BIGINT NOT NULL DEFAULT 1,
    `create_time` DATETIME NULL,
    `update_time` DATETIME NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_mindmap_relation_uid` (`file_id`, `relation_uid`),
    KEY `idx_mindmap_relation_source` (`file_id`, `source_node_id`, `sort_order`),
    KEY `idx_mindmap_relation_target` (`file_id`, `target_node_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='脑图跨节点关系表';

CREATE TABLE IF NOT EXISTS `mindmap_summary` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `summary_uid` VARCHAR(64) NOT NULL,
    `file_id` BIGINT NOT NULL,
    `owner_node_id` BIGINT NOT NULL,
    `start_child_id` BIGINT NULL,
    `end_child_id` BIGINT NULL,
    `content_data` JSON NULL,
    `style_data` JSON NULL,
    `extension_data` JSON NULL,
    `sort_order` INT NOT NULL DEFAULT 0,
    `revision` BIGINT NOT NULL DEFAULT 1,
    `create_time` DATETIME NULL,
    `update_time` DATETIME NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_mindmap_summary_uid` (`file_id`, `summary_uid`),
    KEY `idx_mindmap_summary_owner` (`file_id`, `owner_node_id`, `sort_order`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='脑图概要表';

CREATE TABLE IF NOT EXISTS `mindmap_group` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `group_uid` VARCHAR(64) NOT NULL,
    `file_id` BIGINT NOT NULL,
    `parent_node_id` BIGINT NOT NULL,
    `group_type` VARCHAR(32) NOT NULL DEFAULT 'outer_frame',
    `text` LONGTEXT NULL,
    `style_data` JSON NULL,
    `extension_data` JSON NULL,
    `revision` BIGINT NOT NULL DEFAULT 1,
    `create_time` DATETIME NULL,
    `update_time` DATETIME NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_mindmap_group_uid` (`file_id`, `group_uid`),
    KEY `idx_mindmap_group_parent` (`file_id`, `parent_node_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='脑图节点分组表';

CREATE TABLE IF NOT EXISTS `mindmap_group_member` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `group_id` BIGINT NOT NULL,
    `node_id` BIGINT NOT NULL,
    `sort_order` INT NOT NULL DEFAULT 0,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_mindmap_group_member` (`group_id`, `node_id`),
    KEY `idx_mindmap_group_member_order` (`group_id`, `sort_order`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='脑图节点分组成员表';

CREATE TABLE IF NOT EXISTS `mindmap_asset` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `file_id` BIGINT NOT NULL,
    `asset_key` VARCHAR(128) NOT NULL,
    `asset_type` VARCHAR(32) NOT NULL DEFAULT 'image',
    `storage_type` VARCHAR(16) NOT NULL DEFAULT 'url',
    `uri` LONGTEXT NULL,
    `object_key` VARCHAR(500) NULL,
    `mime_type` VARCHAR(100) NULL,
    `size` BIGINT NULL,
    `sha256` VARCHAR(64) NULL,
    `metadata` JSON NULL,
    `create_time` DATETIME NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_mindmap_asset_key` (`file_id`, `asset_key`),
    KEY `idx_mindmap_asset_hash` (`file_id`, `sha256`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='脑图资源表';

CREATE TABLE IF NOT EXISTS `mindmap_node_tag` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `file_id` BIGINT NOT NULL,
    `node_id` BIGINT NOT NULL,
    `tag_id` BIGINT NOT NULL,
    `field_id` BIGINT NULL COMMENT '绑定时所属标签字段ID',
    `option_id` BIGINT NULL COMMENT '绑定时选择的字段选项ID',
    `sort_order` INT NOT NULL DEFAULT 0,
    `placement` VARCHAR(16) NULL,
    `align` VARCHAR(16) NULL,
    `created_by` VARCHAR(64) NULL,
    `created_time` DATETIME NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_mindmap_node_tag` (`node_id`, `tag_id`),
    KEY `idx_mindmap_node_tag_usage` (`tag_id`, `file_id`),
    KEY `idx_mindmap_node_tag_option` (`option_id`, `file_id`),
    KEY `idx_mindmap_node_tag_order` (`node_id`, `sort_order`),
    CONSTRAINT `fk_mindmap_node_tag_field`
        FOREIGN KEY (`field_id`) REFERENCES `mindmap_tag_field` (`id`) ON DELETE RESTRICT,
    CONSTRAINT `fk_mindmap_node_tag_option`
        FOREIGN KEY (`option_id`) REFERENCES `mindmap_tag_field_option` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='脑图节点标签关系表';

CALL `add_column_if_missing`('mindmap_node_tag', 'field_id', 'BIGINT NULL COMMENT ''绑定时所属标签字段ID'' AFTER `tag_id`');
CALL `add_column_if_missing`('mindmap_node_tag', 'option_id', 'BIGINT NULL COMMENT ''绑定时选择的字段选项ID'' AFTER `field_id`');
CALL `ensure_index_definition`(
    'mindmap_node_tag', 'idx_mindmap_node_tag_option', 'option_id,file_id', 1,
    '(`option_id`, `file_id`)'
);

-- 旧关系只在 tag 与字段选项一对一时安全回填；一对多关系保留为空，等待用户重新选择。
UPDATE `mindmap_node_tag` nt
JOIN (
    SELECT `tag_id`, MIN(`id`) AS `option_id`, MIN(`field_id`) AS `field_id`
    FROM `mindmap_tag_field_option`
    WHERE `tag_id` IS NOT NULL
    GROUP BY `tag_id`
    HAVING COUNT(*) = 1
) mapping ON mapping.`tag_id` = nt.`tag_id`
SET nt.`field_id` = mapping.`field_id`, nt.`option_id` = mapping.`option_id`
WHERE nt.`option_id` IS NULL;

CREATE TABLE IF NOT EXISTS `mindmap_migration_record` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `file_id` BIGINT NOT NULL,
    `batch_id` VARCHAR(64) NOT NULL,
    `status` VARCHAR(16) NOT NULL COMMENT 'migrated/failed',
    `legacy_hash` VARCHAR(64) NULL,
    `structured_hash` VARCHAR(64) NULL,
    `error_message` VARCHAR(2000) NULL,
    `started_time` DATETIME NOT NULL,
    `finished_time` DATETIME NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_mindmap_migration_file` (`file_id`),
    KEY `idx_mindmap_migration_batch` (`batch_id`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='脑图结构化迁移结果';

DROP PROCEDURE IF EXISTS `add_column_if_missing`;
DROP PROCEDURE IF EXISTS `ensure_index_definition`;
