-- 脑图本次增量升级（MySQL 8+，可重复执行）。
-- 合并版本文档配置快照补列与已转换数据库的旧标签结构清理。
-- 执行顺序：统一前置校验 -> 补齐 mindmap_version.document_data -> 清理旧标签结构。
-- 不新增标签/分类，不更新样式、选择模式、计数或节点标签绑定。
-- 历史版本 document_data 保留 NULL，表示当时未记录配置。
--
-- 前提：已经完成基础脑图及统一标签的数据转换。本脚本不替代
-- 20260824_mindmap_unified_tags.sql；存在 field_id/option_id 绑定时拒绝执行，
-- 应先按原迁移顺序完成转换，不能直接删除旧定义。
-- 执行前停写 HTTP/AI/协作进程，并备份 mindmap_version、mindmap_tag_category、
-- mindmap_tag、mindmap_node_tag、mindmap_tag_field、mindmap_tag_field_option、
-- mindmap_ws_state。旧标签定义清理后仅保留在备份中。
-- MySQL DDL 会隐式提交；执行器必须遇错立即停止，禁止 --force。
-- 失败后保持停写并核对备份；本文件不提供整批事务回滚。

DROP PROCEDURE IF EXISTS `upgrade_mindmap_release_20261003`;
DELIMITER $$
CREATE PROCEDURE `upgrade_mindmap_release_20261003`()
upgrade: BEGIN
    DECLARE legacy_objects INT DEFAULT 0;
    DECLARE has_field_column INT DEFAULT 0;
    DECLARE has_option_column INT DEFAULT 0;
    DECLARE invalid_count BIGINT DEFAULT 0;
    DECLARE retired_constraint VARCHAR(64);

    -- 先检查版本表的前置结构；所有校验通过前不改动任何业务数据。
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_version'
    ) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '脑图升级中止：mindmap_version 表不存在，请先完成基础迁移';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_version'
          AND COLUMN_NAME = 'document_data'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_version'
          AND COLUMN_NAME = 'theme'
    ) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '脑图升级中止：mindmap_version.theme 列不存在';
    END IF;

    SELECT COUNT(*) INTO has_field_column
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_node_tag'
      AND COLUMN_NAME = 'field_id';
    SELECT COUNT(*) INTO has_option_column
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_node_tag'
      AND COLUMN_NAME = 'option_id';
    SELECT COUNT(*) INTO legacy_objects
    FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME IN ('mindmap_tag_field', 'mindmap_tag_field_option');
    SET legacy_objects = legacy_objects + has_field_column + has_option_column;
    IF EXISTS (
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_node_tag'
          AND INDEX_NAME = 'idx_mindmap_node_tag_option'
    ) THEN
        SET legacy_objects = legacy_objects + 1;
    END IF;

    -- 仅在存在遗留结构时检查清理条件；已完成清理的数据库跳过此段。
    IF legacy_objects > 0 THEN
        SELECT COUNT(*) INTO invalid_count
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME IN ('mindmap_node_tag', 'mindmap_tag', 'mindmap_ws_state');
        IF invalid_count <> 3 THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = '旧标签清理中止：统一标签或协作缓存表不完整';
        END IF;

        -- 所有数据校验都在第一次 DELETE/ALTER/DROP 之前完成。
        IF has_field_column > 0 THEN
            SELECT COUNT(*) INTO invalid_count FROM `mindmap_node_tag` WHERE `field_id` IS NOT NULL;
            IF invalid_count > 0 THEN
                SIGNAL SQLSTATE '45000'
                    SET MESSAGE_TEXT = '旧标签清理中止：仍有 field_id 绑定，必须执行完整迁移';
            END IF;
        END IF;
        IF has_option_column > 0 THEN
            SELECT COUNT(*) INTO invalid_count FROM `mindmap_node_tag` WHERE `option_id` IS NOT NULL;
            IF invalid_count > 0 THEN
                SIGNAL SQLSTATE '45000'
                    SET MESSAGE_TEXT = '旧标签清理中止：仍有 option_id 绑定，必须执行完整迁移';
            END IF;
        END IF;

        SELECT COUNT(*) INTO invalid_count
        FROM `mindmap_node_tag` AS binding
        LEFT JOIN `mindmap_tag` AS tag ON tag.`id` = binding.`tag_id`
        WHERE tag.`id` IS NULL;
        IF invalid_count > 0 THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = '旧标签清理中止：存在无效 tag_id 绑定';
        END IF;
        SELECT COUNT(*) INTO invalid_count
        FROM (
            SELECT `node_id`, `tag_id` FROM `mindmap_node_tag`
            GROUP BY `node_id`, `tag_id` HAVING COUNT(*) > 1
        ) AS duplicate_bindings;
        IF invalid_count > 0 THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = '旧标签清理中止：存在重复统一标签绑定';
        END IF;

        -- 只允许待删旧列及旧选项表引用旧字段模型，不能连带删除额外业务依赖。
        SELECT COUNT(*) INTO invalid_count
        FROM information_schema.KEY_COLUMN_USAGE
        WHERE REFERENCED_TABLE_SCHEMA = DATABASE()
          AND (
              (
                  REFERENCED_TABLE_NAME IN ('mindmap_tag_field', 'mindmap_tag_field_option')
                  AND NOT (
                      TABLE_SCHEMA = DATABASE() AND (
                          (TABLE_NAME = 'mindmap_node_tag' AND COLUMN_NAME IN ('field_id', 'option_id'))
                          OR (TABLE_NAME = 'mindmap_tag_field_option' AND REFERENCED_TABLE_NAME = 'mindmap_tag_field')
                      )
                  )
              )
              OR (REFERENCED_TABLE_NAME = 'mindmap_node_tag' AND REFERENCED_COLUMN_NAME IN ('field_id', 'option_id'))
          );
        IF invalid_count > 0 THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = '旧标签清理中止：存在额外业务外键依赖';
        END IF;
    END IF;

    -- 历史版本保留 NULL，不用当前文件配置伪造历史快照。
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'mindmap_version'
          AND COLUMN_NAME = 'document_data'
    ) THEN
        ALTER TABLE `mindmap_version`
            ADD COLUMN `document_data` JSON NULL
            COMMENT '文档级扩展配置快照，NULL 表示旧版本未记录' AFTER `theme`;
    END IF;

    -- 版本列已补齐且旧结构已不存在时退出，不清理后来重建的协作缓存。
    IF legacy_objects = 0 THEN
        LEAVE upgrade;
    END IF;

    -- 先清理可重建缓存，再移除最后的旧结构。若缓存清理失败，不会删除
    -- 任何旧结构；若后续 DDL 中断，重跑仍能通过残余旧结构识别未完成状态。
    DELETE FROM `mindmap_ws_state`;

    SELECT MIN(CONSTRAINT_NAME) INTO retired_constraint
    FROM information_schema.KEY_COLUMN_USAGE
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_node_tag'
      AND COLUMN_NAME IN ('field_id', 'option_id') AND REFERENCED_TABLE_NAME IS NOT NULL;
    WHILE retired_constraint IS NOT NULL DO
        SET @mindmap_legacy_tag_cleanup_ddl = CONCAT(
            'ALTER TABLE `mindmap_node_tag` DROP FOREIGN KEY `',
            REPLACE(retired_constraint, '`', '``'), '`'
        );
        PREPARE cleanup_statement FROM @mindmap_legacy_tag_cleanup_ddl;
        EXECUTE cleanup_statement;
        DEALLOCATE PREPARE cleanup_statement;
        SELECT MIN(CONSTRAINT_NAME) INTO retired_constraint
        FROM information_schema.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_node_tag'
          AND COLUMN_NAME IN ('field_id', 'option_id') AND REFERENCED_TABLE_NAME IS NOT NULL;
    END WHILE;
    SET @mindmap_legacy_tag_cleanup_ddl = NULL;

    IF EXISTS (
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_node_tag'
          AND INDEX_NAME = 'idx_mindmap_node_tag_option'
    ) THEN
        ALTER TABLE `mindmap_node_tag` DROP INDEX `idx_mindmap_node_tag_option`;
    END IF;
    IF has_option_column > 0 THEN
        ALTER TABLE `mindmap_node_tag` DROP COLUMN `option_id`;
    END IF;
    IF has_field_column > 0 THEN
        ALTER TABLE `mindmap_node_tag` DROP COLUMN `field_id`;
    END IF;
    DROP TABLE IF EXISTS `mindmap_tag_field_option`;
    DROP TABLE IF EXISTS `mindmap_tag_field`;
END$$
DELIMITER ;

CALL `upgrade_mindmap_release_20261003`();
DROP PROCEDURE IF EXISTS `upgrade_mindmap_release_20261003`;
