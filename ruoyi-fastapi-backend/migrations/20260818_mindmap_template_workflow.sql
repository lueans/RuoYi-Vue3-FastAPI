-- Harden the template-market lifecycle and converge legacy duplicate categories.
-- MySQL 8.x; safe to run repeatedly. Data normalization commits before DDL,
-- because MySQL DDL performs implicit commits and cannot make this file atomic.

START TRANSACTION;

-- Give historical blank categories deterministic names before applying a unique key.
UPDATE mindmap_template_category
SET name = CONCAT('未命名分类-', id)
WHERE TRIM(name) = '';

DROP TEMPORARY TABLE IF EXISTS tmp_mindmap_template_category_canonical;

-- Clear any historical orphan before adding a referential constraint.
UPDATE mindmap AS template_file
LEFT JOIN mindmap_template_category AS category
  ON category.id = template_file.template_category_id
SET template_file.template_category_id = NULL
WHERE template_file.template_category_id IS NOT NULL
  AND category.id IS NULL;
CREATE TEMPORARY TABLE tmp_mindmap_template_category_canonical AS
SELECT TRIM(name) AS normalized_name, MIN(id) AS keep_id
FROM mindmap_template_category
GROUP BY TRIM(name);

-- Preserve existing template assignments by moving them to the canonical row.
UPDATE mindmap AS template_file
JOIN mindmap_template_category AS category
  ON category.id = template_file.template_category_id
JOIN tmp_mindmap_template_category_canonical AS canonical
  ON canonical.normalized_name = TRIM(category.name)
SET template_file.template_category_id = canonical.keep_id
WHERE category.id <> canonical.keep_id;

-- Remove duplicate definitions only after all references have been reassigned.
DELETE category
FROM mindmap_template_category AS category
JOIN tmp_mindmap_template_category_canonical AS canonical
  ON canonical.normalized_name = TRIM(category.name)
WHERE category.id <> canonical.keep_id;

UPDATE mindmap_template_category
SET name = TRIM(name);

DROP TEMPORARY TABLE IF EXISTS tmp_mindmap_template_category_canonical;

COMMIT;

SET @template_category_name_index_exists = (
    SELECT COUNT(1)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'mindmap_template_category'
      AND index_name = 'uq_mindmap_template_category_name'
);
SET @template_category_name_index_matches = (
    SELECT COUNT(*)
    FROM (
        SELECT index_name
        FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name = 'mindmap_template_category'
          AND index_name = 'uq_mindmap_template_category_name'
        GROUP BY index_name
        HAVING GROUP_CONCAT(column_name ORDER BY seq_in_index SEPARATOR ',') = 'name'
           AND MIN(non_unique) = 0
    ) AS matching_index
);
SET @template_category_name_index_drop_sql = IF(
    @template_category_name_index_exists > 0 AND @template_category_name_index_matches = 0,
    'ALTER TABLE mindmap_template_category DROP INDEX uq_mindmap_template_category_name',
    'SELECT ''template category name index does not need repair'''
);
PREPARE template_category_name_drop_stmt FROM @template_category_name_index_drop_sql;
EXECUTE template_category_name_drop_stmt;
DEALLOCATE PREPARE template_category_name_drop_stmt;
SET @template_category_name_index_sql = IF(
    @template_category_name_index_matches = 0,
    'ALTER TABLE mindmap_template_category ADD UNIQUE INDEX uq_mindmap_template_category_name (name)',
    'SELECT ''template category name index already exists'''
);
PREPARE template_category_name_stmt FROM @template_category_name_index_sql;
EXECUTE template_category_name_stmt;
DEALLOCATE PREPARE template_category_name_stmt;

SET @template_market_index_exists = (
    SELECT COUNT(1)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'mindmap'
      AND index_name = 'idx_mindmap_template_market'
);
SET @template_market_index_matches = (
    SELECT COUNT(*)
    FROM (
        SELECT index_name
        FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name = 'mindmap'
          AND index_name = 'idx_mindmap_template_market'
        GROUP BY index_name
        HAVING GROUP_CONCAT(column_name ORDER BY seq_in_index SEPARATOR ',') =
                 'is_template,del_flag,template_category_id,create_time'
           AND MIN(non_unique) = 1
    ) AS matching_index
);
SET @template_market_index_drop_sql = IF(
    @template_market_index_exists > 0 AND @template_market_index_matches = 0,
    'ALTER TABLE mindmap DROP INDEX idx_mindmap_template_market',
    'SELECT ''template market index does not need repair'''
);
PREPARE template_market_drop_stmt FROM @template_market_index_drop_sql;
EXECUTE template_market_drop_stmt;
DEALLOCATE PREPARE template_market_drop_stmt;
SET @template_market_index_sql = IF(
    @template_market_index_matches = 0,
    'ALTER TABLE mindmap ADD INDEX idx_mindmap_template_market (is_template, del_flag, template_category_id, create_time)',
    'SELECT ''template market index already exists'''
);
PREPARE template_market_stmt FROM @template_market_index_sql;
EXECUTE template_market_stmt;
DEALLOCATE PREPARE template_market_stmt;

SET @template_category_fk_exists = (
    SELECT COUNT(1)
    FROM information_schema.table_constraints
    WHERE constraint_schema = DATABASE()
      AND table_name = 'mindmap'
      AND constraint_name = 'fk_mindmap_template_category'
      AND constraint_type = 'FOREIGN KEY'
);
SET @template_category_fk_matches = (
    SELECT COUNT(*)
    FROM (
        SELECT constraint_name
        FROM information_schema.key_column_usage
        WHERE constraint_schema = DATABASE()
          AND table_name = 'mindmap'
          AND constraint_name = 'fk_mindmap_template_category'
        GROUP BY constraint_name, referenced_table_name
        HAVING GROUP_CONCAT(column_name ORDER BY ordinal_position SEPARATOR ',') =
                 'template_category_id'
           AND referenced_table_name = 'mindmap_template_category'
           AND GROUP_CONCAT(referenced_column_name ORDER BY ordinal_position SEPARATOR ',') = 'id'
    ) AS matching_foreign_key
);
SET @template_category_fk_drop_sql = IF(
    @template_category_fk_exists > 0 AND @template_category_fk_matches = 0,
    'ALTER TABLE mindmap DROP FOREIGN KEY fk_mindmap_template_category',
    'SELECT ''template category foreign key does not need repair'''
);
PREPARE template_category_fk_drop_stmt FROM @template_category_fk_drop_sql;
EXECUTE template_category_fk_drop_stmt;
DEALLOCATE PREPARE template_category_fk_drop_stmt;
SET @template_category_fk_sql = IF(
    @template_category_fk_matches = 0,
    'ALTER TABLE mindmap ADD CONSTRAINT fk_mindmap_template_category FOREIGN KEY (template_category_id) REFERENCES mindmap_template_category (id) ON DELETE RESTRICT ON UPDATE RESTRICT',
    'SELECT ''template category foreign key already exists'''
);
PREPARE template_category_fk_stmt FROM @template_category_fk_sql;
EXECUTE template_category_fk_stmt;
DEALLOCATE PREPARE template_category_fk_stmt;
