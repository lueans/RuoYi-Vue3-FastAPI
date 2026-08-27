-- Remove the retired mindmap template market and administration feature.
-- MySQL 8.x; safe to run repeatedly on the current application schema.

DROP TEMPORARY TABLE IF EXISTS tmp_removed_mindmap_template_ids;
CREATE TEMPORARY TABLE tmp_removed_mindmap_template_ids (
    id BIGINT PRIMARY KEY
);

SET @mindmap_template_flag_exists = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'mindmap'
      AND column_name = 'is_template'
);
SET @capture_template_ids_sql = IF(
    @mindmap_template_flag_exists > 0,
    'INSERT INTO tmp_removed_mindmap_template_ids (id) SELECT id FROM mindmap WHERE is_template = 1',
    'SELECT ''mindmap template flag already removed'''
);
PREPARE stmt FROM @capture_template_ids_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

START TRANSACTION;

-- Remove every child record before deleting the retired template files.
DELETE child FROM mindmap_comment AS child
JOIN tmp_removed_mindmap_template_ids AS removed ON removed.id = child.mindmap_id;
DELETE child FROM mindmap_comment_thread AS child
JOIN tmp_removed_mindmap_template_ids AS removed ON removed.id = child.mindmap_id;
DELETE child FROM mindmap_version AS child
JOIN tmp_removed_mindmap_template_ids AS removed ON removed.id = child.mindmap_id;
DELETE child FROM mindmap_share AS child
JOIN tmp_removed_mindmap_template_ids AS removed ON removed.id = child.mindmap_id;
DELETE child FROM mindmap_collaborator AS child
JOIN tmp_removed_mindmap_template_ids AS removed ON removed.id = child.mindmap_id;
DELETE child FROM mindmap_ws_state AS child
JOIN tmp_removed_mindmap_template_ids AS removed ON removed.id = child.mindmap_id;
DELETE member FROM mindmap_group_member AS member
JOIN mindmap_group AS group_row ON group_row.id = member.group_id
JOIN tmp_removed_mindmap_template_ids AS removed ON removed.id = group_row.file_id;
DELETE child FROM mindmap_node_tag AS child
JOIN tmp_removed_mindmap_template_ids AS removed ON removed.id = child.file_id;
DELETE child FROM mindmap_relation AS child
JOIN tmp_removed_mindmap_template_ids AS removed ON removed.id = child.file_id;
DELETE child FROM mindmap_summary AS child
JOIN tmp_removed_mindmap_template_ids AS removed ON removed.id = child.file_id;
DELETE child FROM mindmap_group AS child
JOIN tmp_removed_mindmap_template_ids AS removed ON removed.id = child.file_id;
DELETE child FROM mindmap_asset AS child
JOIN tmp_removed_mindmap_template_ids AS removed ON removed.id = child.file_id;
DELETE child FROM mindmap_node AS child
JOIN tmp_removed_mindmap_template_ids AS removed ON removed.id = child.file_id;
DELETE child FROM mindmap_change_log AS child
JOIN tmp_removed_mindmap_template_ids AS removed ON removed.id = child.file_id;
DELETE child FROM mindmap_migration_record AS child
JOIN tmp_removed_mindmap_template_ids AS removed ON removed.id = child.file_id;
DELETE request_row FROM mindmap_creation_request AS request_row
LEFT JOIN tmp_removed_mindmap_template_ids AS removed
  ON removed.id = request_row.result_file_id
WHERE request_row.operation = 'template' OR removed.id IS NOT NULL;
DELETE file_row FROM mindmap AS file_row
JOIN tmp_removed_mindmap_template_ids AS removed ON removed.id = file_row.id;

DROP TEMPORARY TABLE IF EXISTS tmp_mindmap_template_menu_ids;
CREATE TEMPORARY TABLE tmp_mindmap_template_menu_ids (
    menu_id BIGINT PRIMARY KEY
);
INSERT IGNORE INTO tmp_mindmap_template_menu_ids (menu_id)
SELECT menu_id
FROM sys_menu
WHERE component IN ('mindmap/templates', 'mindmap/templateAdmin')
   OR perms LIKE 'mindmap:template:%'
   OR (menu_name IN ('模板市场', '模板管理') AND path IN ('templates', 'templateAdmin'));
DELETE role_menu FROM sys_role_menu AS role_menu
JOIN tmp_mindmap_template_menu_ids AS removed ON removed.menu_id = role_menu.menu_id;
DELETE menu_row FROM sys_menu AS menu_row
JOIN tmp_mindmap_template_menu_ids AS removed ON removed.menu_id = menu_row.menu_id;

COMMIT;

-- Remove the foreign key and indexes before dropping their columns.
SET @mindmap_template_fk_exists = (
    SELECT COUNT(*) FROM information_schema.table_constraints
    WHERE constraint_schema = DATABASE()
      AND table_name = 'mindmap'
      AND constraint_name = 'fk_mindmap_template_category'
      AND constraint_type = 'FOREIGN KEY'
);
SET @drop_mindmap_template_fk_sql = IF(
    @mindmap_template_fk_exists > 0,
    'ALTER TABLE mindmap DROP FOREIGN KEY fk_mindmap_template_category',
    'SELECT ''mindmap template foreign key already removed'''
);
PREPARE stmt FROM @drop_mindmap_template_fk_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @mindmap_template_market_index_exists = (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'mindmap'
      AND index_name = 'idx_mindmap_template_market'
);
SET @drop_mindmap_template_market_index_sql = IF(
    @mindmap_template_market_index_exists > 0,
    'ALTER TABLE mindmap DROP INDEX idx_mindmap_template_market',
    'SELECT ''mindmap template market index already removed'''
);
PREPARE stmt FROM @drop_mindmap_template_market_index_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @mindmap_owner_folder_index_exists = (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'mindmap'
      AND index_name = 'idx_mindmap_owner_folder'
);
SET @drop_mindmap_owner_folder_index_sql = IF(
    @mindmap_owner_folder_index_exists > 0,
    'ALTER TABLE mindmap DROP INDEX idx_mindmap_owner_folder',
    'SELECT ''mindmap owner folder index does not exist'''
);
PREPARE stmt FROM @drop_mindmap_owner_folder_index_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
ALTER TABLE mindmap ADD INDEX idx_mindmap_owner_folder (owner_id, folder_id, del_flag);

SET @mindmap_owner_status_index_exists = (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'mindmap'
      AND index_name = 'idx_mindmap_owner_status'
);
SET @drop_mindmap_owner_status_index_sql = IF(
    @mindmap_owner_status_index_exists > 0,
    'ALTER TABLE mindmap DROP INDEX idx_mindmap_owner_status',
    'SELECT ''mindmap owner status index does not exist'''
);
PREPARE stmt FROM @drop_mindmap_owner_status_index_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
ALTER TABLE mindmap ADD INDEX idx_mindmap_owner_status (owner_id, status, del_flag, update_time);

SET @mindmap_template_category_column_exists = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'mindmap'
      AND column_name = 'template_category_id'
);
SET @drop_mindmap_template_category_column_sql = IF(
    @mindmap_template_category_column_exists > 0,
    'ALTER TABLE mindmap DROP COLUMN template_category_id',
    'SELECT ''mindmap template category column already removed'''
);
PREPARE stmt FROM @drop_mindmap_template_category_column_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @drop_mindmap_template_flag_sql = IF(
    @mindmap_template_flag_exists > 0,
    'ALTER TABLE mindmap DROP COLUMN is_template',
    'SELECT ''mindmap template flag already removed'''
);
PREPARE stmt FROM @drop_mindmap_template_flag_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

DROP TABLE IF EXISTS mindmap_template_category;
DROP TEMPORARY TABLE IF EXISTS tmp_mindmap_template_menu_ids;
DROP TEMPORARY TABLE IF EXISTS tmp_removed_mindmap_template_ids;
