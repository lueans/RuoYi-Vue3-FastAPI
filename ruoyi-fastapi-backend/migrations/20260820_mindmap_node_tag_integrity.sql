-- 标签字段/选项引用完整性（MySQL 8+，可重复执行）
-- 先收敛历史悬空引用，再用数据库约束封闭并发删除窗口。

UPDATE `mindmap_node_tag` AS nt
LEFT JOIN `mindmap_tag_field` AS f ON f.`id` = nt.`field_id`
SET nt.`field_id` = NULL
WHERE nt.`field_id` IS NOT NULL AND f.`id` IS NULL;

UPDATE `mindmap_node_tag` AS nt
LEFT JOIN `mindmap_tag_field_option` AS o ON o.`id` = nt.`option_id`
SET nt.`option_id` = NULL
WHERE nt.`option_id` IS NOT NULL AND o.`id` IS NULL;

DROP PROCEDURE IF EXISTS `add_mindmap_fk_if_missing`;
DELIMITER $$
CREATE PROCEDURE `add_mindmap_fk_if_missing`(
    IN p_constraint VARCHAR(64),
    IN p_column VARCHAR(64),
    IN p_reference_table VARCHAR(64)
)
BEGIN
    DECLARE v_exists INT DEFAULT 0;
    DECLARE v_matches INT DEFAULT 0;

    SELECT COUNT(*) INTO v_exists
        FROM information_schema.TABLE_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA = DATABASE()
          AND TABLE_NAME = 'mindmap_node_tag'
          AND CONSTRAINT_NAME = p_constraint
          AND CONSTRAINT_TYPE = 'FOREIGN KEY';

    SELECT COUNT(*) INTO v_matches
        FROM information_schema.KEY_COLUMN_USAGE AS usage_info
        JOIN information_schema.REFERENTIAL_CONSTRAINTS AS reference_info
          ON reference_info.CONSTRAINT_SCHEMA = usage_info.CONSTRAINT_SCHEMA
         AND reference_info.CONSTRAINT_NAME = usage_info.CONSTRAINT_NAME
        WHERE usage_info.CONSTRAINT_SCHEMA = DATABASE()
          AND usage_info.TABLE_NAME = 'mindmap_node_tag'
          AND usage_info.CONSTRAINT_NAME = p_constraint
          AND usage_info.COLUMN_NAME = p_column
          AND usage_info.REFERENCED_TABLE_NAME = p_reference_table
          AND usage_info.REFERENCED_COLUMN_NAME = 'id'
          AND reference_info.DELETE_RULE = 'RESTRICT';

    IF v_exists > 0 AND v_matches = 0 THEN
        SET @ddl = CONCAT(
            'ALTER TABLE `mindmap_node_tag` DROP FOREIGN KEY `', p_constraint, '`'
        );
        PREPARE stmt FROM @ddl;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
    END IF;

    IF v_matches = 0 THEN
        SET @ddl = CONCAT(
            'ALTER TABLE `mindmap_node_tag` ADD CONSTRAINT `', p_constraint,
            '` FOREIGN KEY (`', p_column, '`) REFERENCES `', p_reference_table,
            '` (`id`) ON DELETE RESTRICT'
        );
        PREPARE stmt FROM @ddl;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
    END IF;
END$$
DELIMITER ;

CALL `add_mindmap_fk_if_missing`(
    'fk_mindmap_node_tag_field', 'field_id', 'mindmap_tag_field'
);
CALL `add_mindmap_fk_if_missing`(
    'fk_mindmap_node_tag_option', 'option_id', 'mindmap_tag_field_option'
);

DROP PROCEDURE IF EXISTS `add_mindmap_fk_if_missing`;
