"""统一标签历史数据迁移的静态发布契约。"""

import unittest
from pathlib import Path


class MindmapUnifiedTagMigrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = (
            Path(__file__).parents[1]
            / 'migrations'
            / '20260824_mindmap_unified_tags.sql'
        ).read_text(encoding='utf-8')
        cls.category_ordering_sql = (
            Path(__file__).parents[1]
            / 'migrations'
            / '20260824_mindmap_tag_category_ordering.sql'
        ).read_text(encoding='utf-8')
        cls.postgresql_sql = (
            Path(__file__).parents[1]
            / 'migrations'
            / '20260824_mindmap_unified_tags_postgresql.sql'
        ).read_text(encoding='utf-8')

    def test_migration_materializes_categories_tags_and_local_layout(self) -> None:
        self.assertIn('INSERT IGNORE INTO `mindmap_tag_category`', self.sql)
        self.assertIn('INSERT IGNORE INTO `mindmap_tag`', self.sql)
        self.assertIn('JSON_MERGE_PATCH(\n                COALESCE(f.`style`, JSON_OBJECT())', self.sql)
        self.assertNotIn("JSON_REMOVE(COALESCE(f.`style`, JSON_OBJECT()), '$.placement', '$.align')", self.sql)
        self.assertIn('nt.`placement` = COALESCE(', self.sql)
        self.assertIn('nt.`align` = COALESCE(', self.sql)

    def test_migration_rebuilds_and_deduplicates_node_tag_bindings(self) -> None:
        self.assertIn('COALESCE(direct_tag.`id`, o.`tag_id`) AS `resolved_tag_id`', self.sql)
        self.assertIn('PARTITION BY resolved.`node_id`, resolved.`resolved_tag_id`', self.sql)
        self.assertIn('DECLARE EXIT HANDLER FOR SQLEXCEPTION', self.sql)
        self.assertIn('START TRANSACTION;', self.sql)
        self.assertIn('ROLLBACK;', self.sql)
        self.assertIn('COMMIT;', self.sql)
        self.assertIn('SIGNAL SQLSTATE', self.sql)
        self.assertIn('DELETE FROM `mindmap_node_tag`', self.sql)
        self.assertIn('DELETE FROM `mindmap_ws_state`', self.sql)

    def test_migration_removes_the_legacy_management_schema(self) -> None:
        self.assertIn('DROP COLUMN `option_id`', self.sql)
        self.assertIn('DROP COLUMN `field_id`', self.sql)
        self.assertIn('DROP TABLE IF EXISTS `mindmap_tag_field_option`', self.sql)
        self.assertIn('DROP TABLE IF EXISTS `mindmap_tag_field`', self.sql)

    def test_category_ordering_migration_backfills_system_source_once(self) -> None:
        self.assertIn('ADD COLUMN `category_type`', self.category_ordering_sql)
        self.assertIn("SET c.`category_type` = 'system'", self.category_ordering_sql)
        self.assertIn("c.`owner_id` = 0", self.category_ordering_sql)
        self.assertIn("t.`owner_id` <> 0", self.category_ordering_sql)
        self.assertIn("SET c.`owner_id` = 0", self.category_ordering_sql)
        self.assertIn('COLUMN_NAME = \'category_type\'', self.category_ordering_sql)

    def test_postgresql_migration_matches_the_unified_target_schema(self) -> None:
        self.assertIn('INSERT INTO mindmap_tag_category', self.postgresql_sql)
        self.assertIn('INSERT INTO mindmap_tag', self.postgresql_sql)
        self.assertNotIn("- ARRAY['placement', 'align']", self.postgresql_sql)
        self.assertIn('COALESCE(direct_tag.id, option.tag_id)', self.postgresql_sql)
        self.assertIn('DELETE FROM mindmap_ws_state', self.postgresql_sql)
        self.assertIn('DROP COLUMN IF EXISTS option_id', self.postgresql_sql)
        self.assertIn('DROP COLUMN IF EXISTS field_id', self.postgresql_sql)
        self.assertIn('DROP TABLE IF EXISTS mindmap_tag_field_option', self.postgresql_sql)
        self.assertNotIn('DELIMITER', self.postgresql_sql)
        self.assertNotIn('`', self.postgresql_sql)


if __name__ == '__main__':
    unittest.main()
