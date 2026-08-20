-- 脑图归档列表索引（MySQL 8.0+，可重复执行）
-- 归档状态只能为 0/1；历史异常值先归一化为正常状态。
UPDATE mindmap
SET status = 0
WHERE status IS NULL OR status NOT IN (0, 1);

SET @mindmap_archive_index_exists = (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'mindmap'
    AND index_name = 'idx_mindmap_owner_status'
);
SET @mindmap_archive_index_matches = (
  SELECT COUNT(*)
  FROM (
    SELECT index_name
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'mindmap'
      AND index_name = 'idx_mindmap_owner_status'
    GROUP BY index_name
    HAVING GROUP_CONCAT(column_name ORDER BY seq_in_index SEPARATOR ',') =
             'owner_id,status,del_flag,is_template,update_time'
       AND MIN(non_unique) = 1
  ) AS matching_index
);
SET @mindmap_archive_drop_index_sql = IF(
  @mindmap_archive_index_exists > 0 AND @mindmap_archive_index_matches = 0,
  'ALTER TABLE mindmap DROP INDEX idx_mindmap_owner_status',
  'SELECT ''idx_mindmap_owner_status does not need repair'''
);
PREPARE stmt FROM @mindmap_archive_drop_index_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
SET @mindmap_archive_index_sql = IF(
  @mindmap_archive_index_matches = 0,
  'ALTER TABLE mindmap ADD INDEX idx_mindmap_owner_status (owner_id, status, del_flag, is_template, update_time)',
  'SELECT ''idx_mindmap_owner_status already exists'''
);
PREPARE stmt FROM @mindmap_archive_index_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
