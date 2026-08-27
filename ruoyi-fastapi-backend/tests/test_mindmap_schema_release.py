"""脑图 Schema 只读发布计划测试。"""

import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

from module_mindmap.service.mindmap_schema_release import (
    MANUAL_REVIEW_MIGRATIONS,
    MINDMAP_SCHEMA_MIGRATIONS,
    build_mindmap_migration_plan,
)
from module_mindmap.service.mindmap_schema_verifier import (
    FORBIDDEN_COLUMNS,
    FORBIDDEN_FOREIGN_KEYS,
    FORBIDDEN_INDEXES,
    FORBIDDEN_TABLES,
    REQUIRED_COLUMNS,
    REQUIRED_FOREIGN_KEYS,
    REQUIRED_INDEXES,
    REQUIRED_TABLES,
    TEMPLATE_REMOVAL_MIGRATION,
    MindmapSchemaIssue,
)


class MindmapSchemaReleaseTest(unittest.TestCase):
    MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / 'migrations'

    def test_catalog_covers_every_schema_verifier_migration(self) -> None:
        referenced = (
            set(REQUIRED_TABLES.values())
            | set(REQUIRED_COLUMNS.values())
            | set(REQUIRED_INDEXES.values())
            | set(REQUIRED_FOREIGN_KEYS.values())
            | set(FORBIDDEN_TABLES.values())
            | set(FORBIDDEN_COLUMNS.values())
            | set(FORBIDDEN_INDEXES.values())
            | set(FORBIDDEN_FOREIGN_KEYS.values())
        )

        self.assertEqual(
            referenced - {item.filename for item in MINDMAP_SCHEMA_MIGRATIONS},
            set(),
        )

    def test_groups_issues_in_dependency_order_with_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            migration_dir = Path(directory)
            contents: dict[str, bytes] = {}
            for definition in MINDMAP_SCHEMA_MIGRATIONS:
                content = f'-- {definition.filename}\nSELECT 1;\n'.encode()
                contents[definition.filename] = content
                (migration_dir / definition.filename).write_bytes(content)
            issues = [
                MindmapSchemaIssue(
                    'legacy_column',
                    'mindmap.is_template',
                    TEMPLATE_REMOVAL_MIGRATION,
                ),
                MindmapSchemaIssue(
                    'column',
                    'mindmap_folder.active_name',
                    '20260818_mindmap_folder_lifecycle.sql',
                ),
                MindmapSchemaIssue(
                    'index',
                    'mindmap.idx_mindmap_owner_folder',
                    '20260818_mindmap_folder_lifecycle.sql',
                ),
            ]

            plan = build_mindmap_migration_plan(issues, migration_dir)

            self.assertEqual(
                [item.migration for item in plan],
                [
                    '20260818_mindmap_folder_lifecycle.sql',
                    TEMPLATE_REMOVAL_MIGRATION,
                ],
            )
            self.assertEqual(plan[0].sha256, sha256(contents[plan[0].migration]).hexdigest())
            self.assertEqual(len(plan[0].missing_objects), 2)
            self.assertIn('missingObjects', plan[0].to_dict())
            self.assertNotIn('missing_objects', plan[0].to_dict())

    def test_unknown_migration_fails_closed(self) -> None:
        issue = MindmapSchemaIssue('table', 'unknown', 'unknown.sql')

        with self.assertRaisesRegex(ValueError, '缺少迁移目录定义'):
            build_mindmap_migration_plan([issue], Path('.'))

    def test_missing_migration_file_fails_closed(self) -> None:
        issue = MindmapSchemaIssue(
            'index',
            'mindmap.idx_mindmap_owner_status',
            '20260818_mindmap_archive_lifecycle.sql',
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaisesRegex(ValueError, '迁移文件不存在'),
        ):
            build_mindmap_migration_plan([issue], Path(directory))

    def test_postgresql_plan_selects_the_postgresql_unified_migration(self) -> None:
        issue = MindmapSchemaIssue(
            'legacy_table',
            'mindmap_tag_field',
            '20260824_mindmap_unified_tags.sql',
        )
        with tempfile.TemporaryDirectory() as directory:
            migration_dir = Path(directory)
            migration_name = '20260824_mindmap_unified_tags_postgresql.sql'
            (migration_dir / migration_name).write_text('-- PostgreSQL\nSELECT 1;\n')

            plan = build_mindmap_migration_plan(
                [issue],
                migration_dir,
                database_type='postgresql',
            )

        self.assertEqual([item.migration for item in plan], [migration_name])

    def test_definition_checked_objects_can_be_repaired_by_their_migrations(self) -> None:
        contracts = {
            '20260817_mindmap_structured_content.sql': (
                'ensure_index_definition',
                'DROP INDEX',
            ),
            '20260818_mindmap_archive_lifecycle.sql': (
                'owner_id,status,del_flag,update_time',
                'DROP INDEX idx_mindmap_owner_status',
            ),
            '20260818_mindmap_folder_lifecycle.sql': (
                'owner_id,parent_id,active_name',
                'DROP INDEX uq_mindmap_folder_active_sibling',
                'owner_id,folder_id,del_flag',
                'DROP INDEX idx_mindmap_owner_folder',
            ),
            TEMPLATE_REMOVAL_MIGRATION: (
                "WHERE is_template = 1",
                "request_row.operation = 'template'",
                'DROP INDEX idx_mindmap_template_market',
                'DROP FOREIGN KEY fk_mindmap_template_category',
                'DROP COLUMN template_category_id',
                'DROP COLUMN is_template',
                'DROP TABLE IF EXISTS mindmap_template_category',
            ),
            '20260819_mindmap_retention_indexes.sql': (
                'completed_time',
                'created_time',
                'DROP INDEX `idx_mindmap_creation_retention`',
                'DROP INDEX `idx_mindmap_change_retention`',
            ),
            '20260819_mindmap_tag_category_integrity.sql': (
                'owner_id,name',
                'DROP INDEX uq_mindmap_tag_category_owner_name',
                'DROP FOREIGN KEY fk_mindmap_tag_category',
                'REFERENCES mindmap_tag_category (id) ON DELETE RESTRICT',
            ),
            '20260820_mindmap_node_tag_integrity.sql': (
                'fk_mindmap_node_tag_field',
                'fk_mindmap_node_tag_option',
                'DROP FOREIGN KEY',
                'ON DELETE RESTRICT',
            ),
            '20260824_mindmap_unified_tags.sql': (
                'INSERT IGNORE INTO `mindmap_tag`',
                'DROP COLUMN `field_id`',
                'DROP COLUMN `option_id`',
                'DROP TABLE IF EXISTS `mindmap_tag_field`',
            ),
            '20260826_mindmap_comment_idempotency.sql': (
                'client_request_id',
                'uk_mindmap_comment_author_request',
                'ADD UNIQUE INDEX',
            ),
        }

        for filename, markers in contracts.items():
            sql = (self.MIGRATIONS_DIR / filename).read_text(encoding='utf-8')
            with self.subTest(migration=filename):
                for marker in markers:
                    self.assertIn(marker, sql)

    def test_template_data_is_deleted_before_retired_columns_are_dropped(self) -> None:
        sql = (self.MIGRATIONS_DIR / TEMPLATE_REMOVAL_MIGRATION).read_text(
            encoding='utf-8'
        )

        self.assertLess(
            sql.index('DELETE file_row FROM mindmap AS file_row'),
            sql.index('ALTER TABLE mindmap DROP COLUMN is_template'),
        )

    def test_tag_category_data_convergence_commits_before_constraints(self) -> None:
        sql = (
            self.MIGRATIONS_DIR / '20260819_mindmap_tag_category_integrity.sql'
        ).read_text(encoding='utf-8')

        self.assertLess(sql.index('COMMIT;'), sql.index('ALTER TABLE mindmap_tag_category'))
        self.assertLess(sql.index('SET tag.category_id = canonical.keep_id'), sql.index('DELETE category'))

    def test_mysql_compose_exposes_opt_in_readonly_release_gate(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        compose_source = (project_root / 'docker-compose.my.yml').read_text(encoding='utf-8')
        readme_source = (project_root / 'README.md').read_text(encoding='utf-8')

        self.assertIn('ruoyi-mindmap-schema-check:', compose_source)
        self.assertIn('profiles: ["release-check"]', compose_source)
        self.assertIn('scripts.verify_mindmap_schema', compose_source)
        self.assertIn('condition: service_healthy', compose_source)
        backend_block = compose_source.split('ruoyi-backend-my:', 1)[1].split(
            'ruoyi-mindmap-schema-check:',
            1,
        )[0]
        self.assertNotIn('ruoyi-mindmap-schema-check', backend_block)
        self.assertIn('scripts.plan_mindmap_schema_migrations --env=dockermy', readme_source)
        self.assertIn('scripts.verify_mindmap_schema --env=prod', readme_source)
        self.assertIn('manualReview', readme_source)

    def test_postgresql_compose_runs_complete_mindmap_migration_after_baseline(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        compose_source = (project_root / 'docker-compose.pg.yml').read_text(encoding='utf-8')
        migration_source = (
            self.MIGRATIONS_DIR / '20260820_mindmap_postgresql.sql'
        ).read_text(encoding='utf-8')
        unified_source = (
            self.MIGRATIONS_DIR / '20260824_mindmap_unified_tags_postgresql.sql'
        ).read_text(encoding='utf-8')

        self.assertIn('zz-mindmap-postgresql.sql', compose_source)
        self.assertIn('zzz-mindmap-unified-tags-postgresql.sql', compose_source)
        self.assertIn('zzzz-mindmap-markers-to-tags-postgresql.sql', compose_source)
        for table in REQUIRED_TABLES:
            self.assertIn(f'CREATE TABLE IF NOT EXISTS {table}', migration_source)
        self.assertNotIn('CREATE TABLE IF NOT EXISTS mindmap_tag_field', migration_source)
        self.assertNotIn('CREATE TABLE IF NOT EXISTS mindmap_template_category', migration_source)
        self.assertNotIn('is_template SMALLINT', migration_source)
        self.assertNotIn('template_category_id BIGINT', migration_source)
        self.assertNotIn('field_id BIGINT', migration_source)
        self.assertNotIn('option_id BIGINT', migration_source)
        self.assertIn('DROP TABLE IF EXISTS mindmap_tag_field', unified_source)
        self.assertIn('DROP COLUMN IF EXISTS option_id', unified_source)
        self.assertNotIn('DELIMITER', migration_source)
        self.assertNotIn('AUTO_INCREMENT', migration_source)
        self.assertNotIn('`', migration_source)

    def test_marker_data_migration_is_exposed_for_manual_release_review(self) -> None:
        marker_migration = next(
            item for item in MANUAL_REVIEW_MIGRATIONS
            if item['migration'] == '20260825_mindmap_markers_to_tags.sql'
        )

        self.assertEqual(
            marker_migration['postgresqlMigration'],
            '20260825_mindmap_markers_to_tags_postgresql.sql',
        )
        self.assertIn('61 个内置标记标签', marker_migration['reason'])

    def test_postgresql_comment_idempotency_migration_repairs_only_wrong_index(self) -> None:
        sql = (
            self.MIGRATIONS_DIR / '20260826_mindmap_comment_idempotency_postgresql.sql'
        ).read_text(encoding='utf-8')

        self.assertIn("existing_columns = ARRAY['created_by', 'client_request_id']::TEXT[]", sql)
        self.assertIn('IF existing_columns IS NOT NULL AND NOT', sql)
        self.assertIn(
            'CREATE UNIQUE INDEX IF NOT EXISTS uk_mindmap_comment_author_request',
            sql,
        )


if __name__ == '__main__':
    unittest.main()
