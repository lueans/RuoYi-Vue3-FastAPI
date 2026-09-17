"""脑图 Schema 只读发布计划测试。"""

import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from module_mindmap.entity.do.mindmap_ai_do import MindmapAiDraftCheckpoint
from module_mindmap.service.mindmap_schema_release import (
    MANUAL_REVIEW_MIGRATIONS,
    MINDMAP_SCHEMA_MIGRATIONS,
    build_mindmap_migration_plan,
)
from module_mindmap.service.mindmap_schema_verifier import (
    AI_AGENT_MIGRATION,
    FORBIDDEN_COLUMNS,
    FORBIDDEN_FOREIGN_KEYS,
    FORBIDDEN_INDEXES,
    FORBIDDEN_TABLES,
    REQUIRED_AI_CONNECTOR_SEEDS,
    REQUIRED_AI_MENU_PERMISSION_SEEDS,
    REQUIRED_AI_ROLE_GRANTS,
    REQUIRED_CHECK_CONSTRAINTS,
    REQUIRED_COLUMNS,
    REQUIRED_FOREIGN_KEYS,
    REQUIRED_INDEXES,
    REQUIRED_TABLES,
    TAG_CATEGORY_HOME_MIGRATION,
    TAG_CATEGORY_SELECTION_MIGRATION,
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
            | set(REQUIRED_CHECK_CONSTRAINTS.values())
            | set(FORBIDDEN_TABLES.values())
            | set(FORBIDDEN_COLUMNS.values())
            | set(FORBIDDEN_INDEXES.values())
            | set(FORBIDDEN_FOREIGN_KEYS.values())
            | set(REQUIRED_AI_CONNECTOR_SEEDS.values())
            | set(REQUIRED_AI_MENU_PERMISSION_SEEDS.values())
            | set(REQUIRED_AI_ROLE_GRANTS.values())
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

    def test_draft_checkpoint_plan_selects_the_database_dialect(self) -> None:
        issue = MindmapSchemaIssue(
            'table',
            'mindmap_ai_draft_checkpoint',
            AI_AGENT_MIGRATION,
        )

        mysql_plan = build_mindmap_migration_plan(
            [issue],
            self.MIGRATIONS_DIR,
            database_type='mysql',
        )
        postgresql_plan = build_mindmap_migration_plan(
            [issue],
            self.MIGRATIONS_DIR,
            database_type='postgresql',
        )

        self.assertEqual(
            [item.migration for item in mysql_plan],
            [AI_AGENT_MIGRATION],
        )
        self.assertEqual(
            [item.migration for item in postgresql_plan],
            ['20260910_mindmap_ai_agent_postgresql.sql'],
        )

    def test_draft_checkpoint_migrations_contain_the_complete_contract(self) -> None:
        migration_names = (
            AI_AGENT_MIGRATION,
            '20260910_mindmap_ai_agent_postgresql.sql',
        )
        required_columns = (
            'job_id',
            'preview_version',
            'preview_epoch',
            'document_ciphertext',
            'operations_ciphertext',
            'initial_state_ciphertext',
            'document_hash',
            'summary_json',
            'expires_time',
            'created_time',
            'update_time',
        )

        for migration_name in migration_names:
            sql = (self.MIGRATIONS_DIR / migration_name).read_text(encoding='utf-8')
            normalized = sql.lower().replace('`', '')
            with self.subTest(migration=migration_name):
                self.assertIn('execution_epoch', normalized)
                self.assertIn(
                    'create table if not exists mindmap_ai_draft_checkpoint',
                    normalized,
                )
                for column in required_columns:
                    self.assertIn(column, normalized)
                self.assertIn('idx_mindmap_ai_draft_checkpoint_expires', normalized)

    def test_draft_checkpoint_mysql_ddl_does_not_default_text_summary(self) -> None:
        ddl = str(
            CreateTable(MindmapAiDraftCheckpoint.__table__).compile(
                dialect=mysql.dialect(),
            ),
        )
        summary_definition = next(
            line for line in ddl.splitlines() if 'summary_json' in line
        )

        self.assertNotIn('DEFAULT', summary_definition.upper())
        self.assertIsNone(
            MindmapAiDraftCheckpoint.__table__.c.summary_json.server_default,
        )

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
            TAG_CATEGORY_HOME_MIGRATION: (
                'show_on_home',
                "WHERE `category_type` = 'system'",
            ),
            TAG_CATEGORY_SELECTION_MIGRATION: (
                'selection_mode',
                "DEFAULT 'multiple'",
                "SET `selection_mode` = 'single'",
                "LIKE 'builtin_marker_%'",
            ),
            '20260910_mindmap_ai_agent.sql': (
                'model_allowlist_json',
                'max_budget_usd',
                'timeout_seconds',
                'max_concurrent_jobs',
                'retention_days',
                'ON DUPLICATE KEY UPDATE',
                'idx_mindmap_ai_job_status_expires',
                'status`, `expires_time`, `id',
                'idx_mindmap_ai_undo_expires',
                'expires_time`, `proposal_id',
                'mindmap:mindmap:list',
                'mindmap:mindmap:query',
                "ai_menu.`perms` = 'mindmap:ai:use'",
            ),
        }

        for filename, markers in contracts.items():
            sql = (self.MIGRATIONS_DIR / filename).read_text(encoding='utf-8')
            with self.subTest(migration=filename):
                for marker in markers:
                    self.assertIn(marker, sql)

    def test_ai_permission_inheritance_accepts_flat_and_namespaced_permissions(self) -> None:
        migration_names = (
            '20260910_mindmap_ai_agent.sql',
            '20260910_mindmap_ai_agent_postgresql.sql',
        )
        for migration_name in migration_names:
            sql = (self.MIGRATIONS_DIR / migration_name).read_text(encoding='utf-8')
            with self.subTest(migration=migration_name):
                self.assertIn("'mindmap:list'", sql)
                self.assertIn("'mindmap:query'", sql)
                self.assertIn("'mindmap:mindmap:list'", sql)
                self.assertIn("'mindmap:mindmap:query'", sql)

    def test_ai_migrations_allocate_menu_ids_without_fixed_primary_key_collisions(self) -> None:
        migration_names = (
            '20260910_mindmap_ai_agent.sql',
            '20260910_mindmap_ai_agent_postgresql.sql',
        )
        for migration_name in migration_names:
            sql = (self.MIGRATIONS_DIR / migration_name).read_text(encoding='utf-8')
            with self.subTest(migration=migration_name):
                self.assertIn('MAX(', sql)
                self.assertNotIn("SELECT 9020, 'AI 脑图使用'", sql)
                self.assertNotIn("SELECT 9021, 'AI Agent 管理'", sql)

    def test_ai_retention_hotfix_is_additive_for_both_dialects(self) -> None:
        mysql_sql = (
            self.MIGRATIONS_DIR / '20260910_mindmap_ai_agent.sql'
        ).read_text(encoding='utf-8')
        postgresql_sql = (
            self.MIGRATIONS_DIR / '20260910_mindmap_ai_agent_postgresql.sql'
        ).read_text(encoding='utf-8')
        self.assertNotIn('DROP INDEX', mysql_sql.upper())
        self.assertNotIn('DROP INDEX', postgresql_sql.upper())
        self.assertIn('INSERT IGNORE INTO `sys_role_menu`', mysql_sql)
        self.assertIn('ON CONFLICT DO NOTHING', postgresql_sql)
        self.assertIn("WHERE ai_menu.`perms` = 'mindmap:ai:use'", mysql_sql)
        self.assertIn("WHERE ai_menu.perms = 'mindmap:ai:use'", postgresql_sql)

    def test_ai_bootstrap_migrations_seed_all_connectors_menus_and_admin_grants(self) -> None:
        connector_migrations = (
            '20260910_mindmap_ai_agent.sql',
            '20260910_mindmap_ai_agent_postgresql.sql',
        )
        for migration_name in connector_migrations:
            sql = (self.MIGRATIONS_DIR / migration_name).read_text(encoding='utf-8')
            with self.subTest(migration=migration_name):
                for connector in ('native_mindmap', 'codex', 'claude'):
                    self.assertIn(f"'{connector}'", sql)

        permission_migrations = (
            '20260910_mindmap_ai_agent.sql',
            '20260910_mindmap_ai_agent_postgresql.sql',
        )
        for migration_name in permission_migrations:
            sql = (self.MIGRATIONS_DIR / migration_name).read_text(encoding='utf-8')
            with self.subTest(migration=migration_name):
                self.assertIn("'mindmap:ai:use'", sql)
                self.assertIn("'mindmap:ai:admin'", sql)
                self.assertIn('role_id', sql)
                self.assertIn('SELECT 1, ai_menu.', sql)

    def test_template_data_is_deleted_before_retired_columns_are_dropped(self) -> None:
        sql = (self.MIGRATIONS_DIR / TEMPLATE_REMOVAL_MIGRATION).read_text(
            encoding='utf-8'
        )

        self.assertLess(
            sql.index('DELETE file_row FROM mindmap AS file_row'),
            sql.index('ALTER TABLE mindmap DROP COLUMN is_template'),
        )

    def test_mysql_category_backfills_run_after_the_add_column_guard(self) -> None:
        contracts = {
            TAG_CATEGORY_HOME_MIGRATION: 'SET `show_on_home` = 1',
            TAG_CATEGORY_SELECTION_MIGRATION: 'SET `selection_mode` = \'single\'',
        }

        for filename, assignment in contracts.items():
            sql = (self.MIGRATIONS_DIR / filename).read_text(encoding='utf-8')
            with self.subTest(migration=filename):
                backfill = sql.index('UPDATE `mindmap_tag_category`')
                self.assertLess(sql.index('END IF;'), backfill)
                self.assertGreater(sql.index(assignment), backfill)
                self.assertIn('COLUMN_COMMENT = \'migration_pending_20260828_', sql)
                self.assertLess(backfill, sql.rindex('MODIFY COLUMN'))

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
        self.assertIn('zzzzzzz-mindmap-ai-agent.sql', compose_source)
        backend_block = compose_source.split('ruoyi-backend-my:', 1)[1].split(
            'ruoyi-mindmap-schema-check:',
            1,
        )[0]
        self.assertNotIn('ruoyi-mindmap-schema-check', backend_block)
        self.assertIn('scripts.plan_mindmap_schema_migrations --env=dockermy', readme_source)
        self.assertIn('scripts.verify_mindmap_schema --env=prod', readme_source)
        self.assertIn('manualReview', readme_source)

    def test_docker_compose_requires_and_forwards_checkpoint_key(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        readme_source = (project_root / 'README.md').read_text(encoding='utf-8')

        for compose_name, service_name in (
            ('docker-compose.my.yml', 'ruoyi-backend-my:'),
            ('docker-compose.pg.yml', 'ruoyi-backend-pg:'),
        ):
            compose_source = (project_root / compose_name).read_text(encoding='utf-8')
            backend_block = compose_source.split(service_name, 1)[1].split('\n\n', 1)[0]
            self.assertIn(
                'MINDMAP_AI_CHECKPOINT_KEY: "${MINDMAP_AI_CHECKPOINT_KEY:?',
                backend_block,
            )
            self.assertIn(
                'MINDMAP_AI_CHECKPOINT_KEY_ID: "${MINDMAP_AI_CHECKPOINT_KEY_ID:-checkpoint-v1}"',
                backend_block,
            )

        self.assertIn('后续重启、升级和滚动发布必须复用同一密钥', readme_source)

    def test_source_install_and_ai_acceptance_are_release_ready(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        backend_root = project_root / 'ruoyi-fastapi-backend'
        readme_source = (project_root / 'README.md').read_text(encoding='utf-8')

        for requirements_name in ('requirements.txt', 'requirements-pg.txt'):
            requirements = (backend_root / requirements_name).read_text(
                encoding='utf-8'
            ).splitlines()
            self.assertEqual(requirements[-1], '.')

        self.assertIn('python3 -m venv .venv', readme_source)
        self.assertIn('ruoyi --help', readme_source)
        self.assertIn('ruoyi app doctor --env=dev --output=json', readme_source)
        for migration_name in (
            '20260910_mindmap_ai_agent.sql',
        ):
            self.assertIn(f'mysql -u root -p ruoyi-fastapi < migrations/{migration_name}', readme_source)

        prod_env = (backend_root / '.env.prod').read_text(encoding='utf-8')
        self.assertIn('DB_ECHO = false', prod_env)
        self.assertNotIn('DB_ECHO = true', prod_env)

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
        self.assertIn('zzzzz-mindmap-tag-category-home-postgresql.sql', compose_source)
        self.assertIn('zzzzzz-mindmap-tag-category-selection-mode-postgresql.sql', compose_source)
        self.assertLess(
            compose_source.index('zzzz-mindmap-markers-to-tags-postgresql.sql'),
            compose_source.index('zzzzz-mindmap-tag-category-home-postgresql.sql'),
        )
        self.assertLess(
            compose_source.index('zzzzz-mindmap-tag-category-home-postgresql.sql'),
            compose_source.index('zzzzzz-mindmap-tag-category-selection-mode-postgresql.sql'),
        )
        for table, migration in REQUIRED_TABLES.items():
            if migration != '20260817_mindmap_structured_content.sql':
                continue
            self.assertIn(f'CREATE TABLE IF NOT EXISTS {table}', migration_source)
        ai_migration_source = (
            self.MIGRATIONS_DIR / '20260910_mindmap_ai_agent_postgresql.sql'
        ).read_text(encoding='utf-8')
        self.assertIn('zzzzzzz-mindmap-ai-agent-postgresql.sql', compose_source)
        for table, migration in REQUIRED_TABLES.items():
            if migration == '20260910_mindmap_ai_agent.sql':
                self.assertIn(f'CREATE TABLE IF NOT EXISTS {table}', ai_migration_source)
        self.assertNotIn('CREATE TABLE IF NOT EXISTS mindmap_tag_field', migration_source)
        self.assertNotIn('CREATE TABLE IF NOT EXISTS mindmap_template_category', migration_source)
        self.assertNotIn('is_template SMALLINT', migration_source)
        self.assertNotIn('template_category_id BIGINT', migration_source)
        self.assertNotIn('field_id BIGINT', migration_source)
        self.assertNotIn('option_id BIGINT', migration_source)
        self.assertNotIn('show_on_home', migration_source)
        self.assertNotIn('selection_mode', migration_source)
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
