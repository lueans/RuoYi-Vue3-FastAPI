-- 脑图版本标签快照 Phase 4（MySQL 8+，可重复执行）
-- 通过 information_schema 守卫新增列，部署系统重复执行时不会失败。

DROP PROCEDURE IF EXISTS `add_mindmap_version_tag_snapshots`;
DELIMITER $$
CREATE PROCEDURE `add_mindmap_version_tag_snapshots`()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'mindmap_version'
          AND COLUMN_NAME = 'snapshot_schema_version'
    ) THEN
        ALTER TABLE `mindmap_version`
            ADD COLUMN `snapshot_schema_version` INT NOT NULL DEFAULT 1
            COMMENT '版本快照结构版本' AFTER `theme`;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'mindmap_version'
          AND COLUMN_NAME = 'tag_snapshots'
    ) THEN
        ALTER TABLE `mindmap_version`
            ADD COLUMN `tag_snapshots` JSON NULL
            COMMENT '版本创建时引用标签的不可变定义快照' AFTER `snapshot_schema_version`;
    END IF;
END$$
DELIMITER ;

CALL `add_mindmap_version_tag_snapshots`();
DROP PROCEDURE IF EXISTS `add_mindmap_version_tag_snapshots`;
