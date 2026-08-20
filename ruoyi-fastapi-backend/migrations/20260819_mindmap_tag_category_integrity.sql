-- Enforce tag-category uniqueness and referential integrity.
-- MySQL 8.x; safe to run repeatedly. Data convergence commits before DDL,
-- because MySQL DDL performs implicit commits and cannot make this file atomic.

START TRANSACTION;

-- Preserve valid tags while clearing historical orphan references.
UPDATE mindmap_tag AS tag
LEFT JOIN mindmap_tag_category AS category
  ON category.id = tag.category_id
SET tag.category_id = NULL
WHERE tag.category_id IS NOT NULL
  AND category.id IS NULL;

-- Bring historical names into the same normalization domain as new writes.
UPDATE mindmap_tag_category
SET name = CONCAT('未命名分类-', id)
WHERE CHAR_LENGTH(TRIM(name)) = 0;

DROP TEMPORARY TABLE IF EXISTS tmp_mindmap_tag_category_canonical;
CREATE TEMPORARY TABLE tmp_mindmap_tag_category_canonical AS
SELECT owner_id, LOWER(TRIM(name)) AS normalized_name, MIN(id) AS keep_id
FROM mindmap_tag_category
GROUP BY owner_id, LOWER(TRIM(name));

-- Repoint every tag before removing duplicate category definitions.
UPDATE mindmap_tag AS tag
JOIN mindmap_tag_category AS category
  ON category.id = tag.category_id
JOIN tmp_mindmap_tag_category_canonical AS canonical
  ON canonical.owner_id = category.owner_id
 AND canonical.normalized_name = LOWER(TRIM(category.name))
SET tag.category_id = canonical.keep_id
WHERE category.id <> canonical.keep_id;

DELETE category
FROM mindmap_tag_category AS category
JOIN tmp_mindmap_tag_category_canonical AS canonical
  ON canonical.owner_id = category.owner_id
 AND canonical.normalized_name = LOWER(TRIM(category.name))
WHERE category.id <> canonical.keep_id;

UPDATE mindmap_tag_category
SET name = TRIM(name)
WHERE name <> TRIM(name);

DROP TEMPORARY TABLE IF EXISTS tmp_mindmap_tag_category_canonical;

COMMIT;

SET @tag_category_unique_exists = (
    SELECT COUNT(1)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'mindmap_tag_category'
      AND index_name = 'uq_mindmap_tag_category_owner_name'
);
SET @tag_category_unique_matches = (
    SELECT COUNT(*)
    FROM (
        SELECT index_name
        FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name = 'mindmap_tag_category'
          AND index_name = 'uq_mindmap_tag_category_owner_name'
        GROUP BY index_name
        HAVING GROUP_CONCAT(column_name ORDER BY seq_in_index SEPARATOR ',') = 'owner_id,name'
           AND MIN(non_unique) = 0
    ) AS matching_index
);
SET @tag_category_unique_drop_sql = IF(
    @tag_category_unique_exists > 0 AND @tag_category_unique_matches = 0,
    'ALTER TABLE mindmap_tag_category DROP INDEX uq_mindmap_tag_category_owner_name',
    'SELECT ''tag category unique index does not need repair'''
);
PREPARE tag_category_unique_drop_stmt FROM @tag_category_unique_drop_sql;
EXECUTE tag_category_unique_drop_stmt;
DEALLOCATE PREPARE tag_category_unique_drop_stmt;
SET @tag_category_unique_sql = IF(
    @tag_category_unique_matches = 0,
    'ALTER TABLE mindmap_tag_category ADD UNIQUE INDEX uq_mindmap_tag_category_owner_name (owner_id, name)',
    'SELECT ''tag category unique index already exists'''
);
PREPARE tag_category_unique_stmt FROM @tag_category_unique_sql;
EXECUTE tag_category_unique_stmt;
DEALLOCATE PREPARE tag_category_unique_stmt;

SET @tag_category_fk_exists = (
    SELECT COUNT(1)
    FROM information_schema.table_constraints
    WHERE constraint_schema = DATABASE()
      AND table_name = 'mindmap_tag'
      AND constraint_name = 'fk_mindmap_tag_category'
      AND constraint_type = 'FOREIGN KEY'
);
SET @tag_category_fk_matches = (
    SELECT COUNT(*)
    FROM (
        SELECT constraint_name
        FROM information_schema.key_column_usage
        WHERE constraint_schema = DATABASE()
          AND table_name = 'mindmap_tag'
          AND constraint_name = 'fk_mindmap_tag_category'
        GROUP BY constraint_name, referenced_table_name
        HAVING GROUP_CONCAT(column_name ORDER BY ordinal_position SEPARATOR ',') = 'category_id'
           AND referenced_table_name = 'mindmap_tag_category'
           AND GROUP_CONCAT(referenced_column_name ORDER BY ordinal_position SEPARATOR ',') = 'id'
    ) AS matching_foreign_key
);
SET @tag_category_fk_drop_sql = IF(
    @tag_category_fk_exists > 0 AND @tag_category_fk_matches = 0,
    'ALTER TABLE mindmap_tag DROP FOREIGN KEY fk_mindmap_tag_category',
    'SELECT ''tag category foreign key does not need repair'''
);
PREPARE tag_category_fk_drop_stmt FROM @tag_category_fk_drop_sql;
EXECUTE tag_category_fk_drop_stmt;
DEALLOCATE PREPARE tag_category_fk_drop_stmt;
SET @tag_category_fk_sql = IF(
    @tag_category_fk_matches = 0,
    'ALTER TABLE mindmap_tag ADD CONSTRAINT fk_mindmap_tag_category FOREIGN KEY (category_id) REFERENCES mindmap_tag_category (id) ON DELETE RESTRICT ON UPDATE RESTRICT',
    'SELECT ''tag category foreign key already exists'''
);
PREPARE tag_category_fk_stmt FROM @tag_category_fk_sql;
EXECUTE tag_category_fk_stmt;
DEALLOCATE PREPARE tag_category_fk_stmt;
