-- 脑图目录生命周期约束（MySQL 8.0+，可重复执行）
-- 1. 修复空名称、首尾空格、指向自身或已失效父级的活动目录。
UPDATE mindmap_folder
SET name = CONCAT('未命名目录-', id)
WHERE del_flag = '0' AND CHAR_LENGTH(TRIM(name)) = 0;

UPDATE mindmap_folder
SET name = TRIM(name)
WHERE del_flag = '0' AND name <> TRIM(name);

UPDATE mindmap_folder AS folder
LEFT JOIN mindmap_folder AS parent
  ON parent.id = folder.parent_id
 AND parent.owner_id = folder.owner_id
 AND parent.del_flag = '0'
SET folder.parent_id = 0
WHERE folder.del_flag = '0'
  AND folder.parent_id <> 0
  AND (folder.parent_id = folder.id OR parent.id IS NULL);

-- 2. 历史同级重名保留最早记录，其余记录追加稳定 ID 后缀。
UPDATE mindmap_folder AS folder
JOIN (
  SELECT owner_id, parent_id, name, MIN(id) AS retained_id
  FROM mindmap_folder
  WHERE del_flag = '0'
  GROUP BY owner_id, parent_id, name
  HAVING COUNT(*) > 1
) AS duplicate
  ON duplicate.owner_id = folder.owner_id
 AND duplicate.parent_id = folder.parent_id
 AND duplicate.name = folder.name
SET folder.name = CONCAT(LEFT(folder.name, 70), '〔迁移去重-', folder.id, '〕')
WHERE folder.del_flag = '0' AND folder.id <> duplicate.retained_id;

-- 3. 软删除记录不参与唯一性约束，活动目录在同一父级下名称唯一。
SET @folder_active_name_exists = (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'mindmap_folder'
    AND column_name = 'active_name'
);
SET @folder_active_name_sql = IF(
  @folder_active_name_exists = 0,
  'ALTER TABLE mindmap_folder ADD COLUMN active_name VARCHAR(100) GENERATED ALWAYS AS (CASE WHEN del_flag = ''0'' THEN name ELSE NULL END) STORED COMMENT ''活动目录唯一名称''',
  'SELECT ''mindmap_folder.active_name already exists'''
);
PREPARE stmt FROM @folder_active_name_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @folder_unique_index_exists = (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'mindmap_folder'
    AND index_name = 'uq_mindmap_folder_active_sibling'
);
SET @folder_unique_index_matches = (
  SELECT COUNT(*)
  FROM (
    SELECT index_name
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'mindmap_folder'
      AND index_name = 'uq_mindmap_folder_active_sibling'
    GROUP BY index_name
    HAVING GROUP_CONCAT(column_name ORDER BY seq_in_index SEPARATOR ',') =
             'owner_id,parent_id,active_name'
       AND MIN(non_unique) = 0
  ) AS matching_index
);
SET @folder_unique_index_drop_sql = IF(
  @folder_unique_index_exists > 0 AND @folder_unique_index_matches = 0,
  'ALTER TABLE mindmap_folder DROP INDEX uq_mindmap_folder_active_sibling',
  'SELECT ''uq_mindmap_folder_active_sibling does not need repair'''
);
PREPARE stmt FROM @folder_unique_index_drop_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
SET @folder_unique_index_sql = IF(
  @folder_unique_index_matches = 0,
  'ALTER TABLE mindmap_folder ADD UNIQUE INDEX uq_mindmap_folder_active_sibling (owner_id, parent_id, active_name)',
  'SELECT ''uq_mindmap_folder_active_sibling already exists'''
);
PREPARE stmt FROM @folder_unique_index_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 4. 支撑目录文件列表、删除影响统计和批量移出目录。
SET @mindmap_owner_folder_index_exists = (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'mindmap'
    AND index_name = 'idx_mindmap_owner_folder'
);
SET @mindmap_owner_folder_index_matches = (
  SELECT COUNT(*)
  FROM (
    SELECT index_name
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'mindmap'
      AND index_name = 'idx_mindmap_owner_folder'
    GROUP BY index_name
    HAVING GROUP_CONCAT(column_name ORDER BY seq_in_index SEPARATOR ',') =
             'owner_id,folder_id,del_flag,is_template'
       AND MIN(non_unique) = 1
  ) AS matching_index
);
SET @mindmap_owner_folder_index_drop_sql = IF(
  @mindmap_owner_folder_index_exists > 0 AND @mindmap_owner_folder_index_matches = 0,
  'ALTER TABLE mindmap DROP INDEX idx_mindmap_owner_folder',
  'SELECT ''idx_mindmap_owner_folder does not need repair'''
);
PREPARE stmt FROM @mindmap_owner_folder_index_drop_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
SET @mindmap_owner_folder_index_sql = IF(
  @mindmap_owner_folder_index_matches = 0,
  'ALTER TABLE mindmap ADD INDEX idx_mindmap_owner_folder (owner_id, folder_id, del_flag, is_template)',
  'SELECT ''idx_mindmap_owner_folder already exists'''
);
PREPARE stmt FROM @mindmap_owner_folder_index_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
