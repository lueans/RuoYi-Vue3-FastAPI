"""脑图数据库 Schema 预检测试。"""

import unittest
from unittest.mock import Mock, patch

from module_mindmap.service.mindmap_schema_verifier import (
    AI_AGENT_MIGRATION,
    REQUIRED_AI_CONNECTOR_SEEDS,
    REQUIRED_AI_MENU_PERMISSION_SEEDS,
    REQUIRED_CHECK_CONSTRAINT_DEFINITIONS,
    REQUIRED_CHECK_CONSTRAINTS,
    REQUIRED_COLUMNS,
    REQUIRED_FOREIGN_KEY_DEFINITIONS,
    REQUIRED_FOREIGN_KEY_DELETE_RULES,
    REQUIRED_FOREIGN_KEYS,
    REQUIRED_INDEX_DEFINITIONS,
    REQUIRED_INDEXES,
    REQUIRED_TABLES,
    TAG_CATEGORY_HOME_MIGRATION,
    TAG_CATEGORY_SELECTION_MIGRATION,
    TEMPLATE_REMOVAL_MIGRATION,
    UNIFIED_TAG_MIGRATION,
    find_mindmap_schema_issues,
    inspect_mindmap_schema,
)


def complete_snapshot() -> dict[str, object]:
    tables = (
        set(REQUIRED_TABLES)
        | {table for table, _ in REQUIRED_COLUMNS}
        | {table for table, _ in REQUIRED_INDEXES}
        | {table for table, _ in REQUIRED_FOREIGN_KEYS}
        | {table for table, _ in REQUIRED_CHECK_CONSTRAINTS}
    )
    return {
        'tables': tables,
        'columns': {
            table: {column for target, column in REQUIRED_COLUMNS if target == table}
            for table in tables
        },
        'indexes': {
            table: {index for target, index in REQUIRED_INDEXES if target == table}
            for table in tables
        },
        'indexDefinitions': {
            table: {
                index: {'columns': definition[0], 'unique': definition[1]}
                for (target, index), definition in REQUIRED_INDEX_DEFINITIONS.items()
                if target == table
            }
            for table in tables
        },
        'foreignKeys': {
            table: {key for target, key in REQUIRED_FOREIGN_KEYS if target == table}
            for table in tables
        },
        'foreignKeyDefinitions': {
            table: {
                key: {
                    'columns': definition[0],
                    'referredTable': definition[1],
                    'referredColumns': definition[2],
                    'onDelete': REQUIRED_FOREIGN_KEY_DELETE_RULES.get((target, key), ''),
                }
                for (target, key), definition in REQUIRED_FOREIGN_KEY_DEFINITIONS.items()
                if target == table
            }
            for table in tables
        },
        'checkConstraints': {
            table: {
                constraint
                for target, constraint in REQUIRED_CHECK_CONSTRAINTS
                if target == table
            }
            for table in tables
        },
        'checkConstraintDefinitions': {
            table: {
                constraint: (
                    f"{definition[0]} IN ("
                    + ', '.join(f"'{value}'" for value in sorted(definition[1]))
                    + ')'
                )
                for (target, constraint), definition
                in REQUIRED_CHECK_CONSTRAINT_DEFINITIONS.items()
                if target == table
            }
            for table in tables
        },
        'aiConnectorKeys': set(REQUIRED_AI_CONNECTOR_SEEDS),
        'aiMenuPermissions': set(REQUIRED_AI_MENU_PERMISSION_SEEDS),
        'aiAdminRoleGrant': True,
        'aiAdminUseGrant': True,
        'aiUseRoleInheritanceComplete': True,
    }


class MindmapSchemaVerifierTest(unittest.TestCase):
    def test_partial_control_plane_tables_do_not_crash_readonly_inspection(self) -> None:
        inspector = Mock()
        inspector.get_table_names.return_value = [
            'mindmap_ai_connector',
            'sys_menu',
            'sys_role_menu',
        ]
        inspector.get_columns.side_effect = lambda table: {
            'mindmap_ai_connector': [{'name': 'enabled'}],
            'sys_menu': [{'name': 'menu_id'}],
            'sys_role_menu': [{'name': 'menu_id'}],
        }[table]
        inspector.get_indexes.return_value = []
        inspector.get_foreign_keys.return_value = []
        inspector.get_check_constraints.return_value = []
        connection = Mock()

        with patch(
            'module_mindmap.service.mindmap_schema_verifier.inspect',
            return_value=inspector,
        ):
            snapshot = inspect_mindmap_schema(connection)

        connection.execute.assert_not_called()
        self.assertEqual(snapshot['aiConnectorKeys'], set())
        self.assertEqual(snapshot['aiMenuPermissions'], set())
        self.assertFalse(snapshot['aiAdminRoleGrant'])

    def test_complete_schema_is_ready(self) -> None:
        self.assertEqual(find_mindmap_schema_issues(complete_snapshot()), [])

    def test_missing_artifacts_report_exact_migration_without_business_data(self) -> None:
        snapshot = complete_snapshot()
        snapshot['tables'].remove('mindmap_change_log')
        snapshot['columns']['mindmap_folder'].remove('active_name')
        snapshot['indexes']['mindmap'].remove('idx_mindmap_owner_status')
        snapshot['foreignKeys']['mindmap_tag'].remove('fk_mindmap_tag_category')

        issues = find_mindmap_schema_issues(snapshot)
        issue_data = [item.to_dict() for item in issues]

        self.assertEqual(len(issue_data), 4)
        self.assertIn({
            'kind': 'column',
            'object_name': 'mindmap_folder.active_name',
            'migration': '20260818_mindmap_folder_lifecycle.sql',
        }, issue_data)
        self.assertTrue(all(set(item) == {'kind', 'object_name', 'migration'} for item in issue_data))

    def test_missing_creation_idempotency_table_names_exact_migration(self) -> None:
        snapshot = complete_snapshot()
        snapshot['tables'].remove('mindmap_creation_request')

        self.assertIn(
            {
                'kind': 'table',
                'object_name': 'mindmap_creation_request',
                'migration': '20260819_mindmap_creation_idempotency.sql',
            },
            [item.to_dict() for item in find_mindmap_schema_issues(snapshot)],
        )

    def test_missing_ai_agent_table_blocks_release_with_one_versioned_migration(self) -> None:
        snapshot = complete_snapshot()
        snapshot['tables'].remove('mindmap_ai_job')

        self.assertIn(
            {
                'kind': 'table',
                'object_name': 'mindmap_ai_job',
                'migration': AI_AGENT_MIGRATION,
            },
            [item.to_dict() for item in find_mindmap_schema_issues(snapshot)],
        )

    def test_missing_ai_draft_checkpoint_table_blocks_release(self) -> None:
        snapshot = complete_snapshot()
        snapshot['tables'].remove('mindmap_ai_draft_checkpoint')

        self.assertIn(
            {
                'kind': 'table',
                'object_name': 'mindmap_ai_draft_checkpoint',
                'migration': AI_AGENT_MIGRATION,
            },
            [item.to_dict() for item in find_mindmap_schema_issues(snapshot)],
        )

    def test_ai_draft_checkpoint_columns_are_release_blocking(self) -> None:
        expected_columns = {
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
        }
        self.assertEqual(
            {
                column
                for (table, column), migration in REQUIRED_COLUMNS.items()
                if table == 'mindmap_ai_draft_checkpoint'
                and migration == AI_AGENT_MIGRATION
            },
            expected_columns,
        )

        snapshot = complete_snapshot()
        snapshot['columns']['mindmap_ai_job'].remove('execution_epoch')
        snapshot['columns']['mindmap_ai_draft_checkpoint'].remove(
            'document_ciphertext'
        )
        issues = [item.to_dict() for item in find_mindmap_schema_issues(snapshot)]

        self.assertIn(
            {
                'kind': 'column',
                'object_name': 'mindmap_ai_job.execution_epoch',
                'migration': AI_AGENT_MIGRATION,
            },
            issues,
        )
        self.assertIn(
            {
                'kind': 'column',
                'object_name': 'mindmap_ai_draft_checkpoint.document_ciphertext',
                'migration': AI_AGENT_MIGRATION,
            },
            issues,
        )

    def test_ai_draft_checkpoint_expiry_index_definition_is_release_blocking(
        self,
    ) -> None:
        snapshot = complete_snapshot()
        snapshot['indexDefinitions']['mindmap_ai_draft_checkpoint'][
            'idx_mindmap_ai_draft_checkpoint_expires'
        ]['columns'] = ('job_id', 'expires_time')

        self.assertIn(
            {
                'kind': 'index_definition',
                'object_name': (
                    'mindmap_ai_draft_checkpoint.'
                    'idx_mindmap_ai_draft_checkpoint_expires'
                ),
                'migration': AI_AGENT_MIGRATION,
            },
            [item.to_dict() for item in find_mindmap_schema_issues(snapshot)],
        )

    def test_partial_ai_agent_schema_blocks_release(self) -> None:
        snapshot = complete_snapshot()
        snapshot['columns']['mindmap_ai_connector'].remove('credential_ref')
        snapshot['indexes']['mindmap_ai_job'].remove(
            'uk_mindmap_ai_job_user_idempotency'
        )

        issues = [item.to_dict() for item in find_mindmap_schema_issues(snapshot)]

        self.assertIn(
            {
                'kind': 'column',
                'object_name': 'mindmap_ai_connector.credential_ref',
                'migration': AI_AGENT_MIGRATION,
            },
            issues,
        )
        self.assertIn(
            {
                'kind': 'index',
                'object_name': 'mindmap_ai_job.uk_mindmap_ai_job_user_idempotency',
                'migration': AI_AGENT_MIGRATION,
            },
            issues,
        )

    def test_missing_ai_runtime_policy_snapshot_names_additive_migration(self) -> None:
        snapshot = complete_snapshot()
        snapshot['columns']['mindmap_ai_connector'].remove('max_concurrent_jobs')
        snapshot['columns']['mindmap_ai_job'].remove('timeout_seconds')

        issues = [item.to_dict() for item in find_mindmap_schema_issues(snapshot)]

        self.assertIn({
            'kind': 'column',
            'object_name': 'mindmap_ai_connector.max_concurrent_jobs',
            'migration': AI_AGENT_MIGRATION,
        }, issues)
        self.assertIn({
            'kind': 'column',
            'object_name': 'mindmap_ai_job.timeout_seconds',
            'migration': AI_AGENT_MIGRATION,
        }, issues)

    def test_missing_each_ai_connector_seed_blocks_release(self) -> None:
        snapshot = complete_snapshot()
        snapshot['aiConnectorKeys'].remove('native_mindmap')
        snapshot['aiConnectorKeys'].remove('codex')
        snapshot['aiConnectorKeys'].remove('claude')

        issues = [item.to_dict() for item in find_mindmap_schema_issues(snapshot)]

        self.assertEqual(
            [item for item in issues if item['kind'] == 'seed'],
            [
                {
                    'kind': 'seed',
                    'object_name': 'mindmap_ai_connector.claude',
                    'migration': AI_AGENT_MIGRATION,
                },
                {
                    'kind': 'seed',
                    'object_name': 'mindmap_ai_connector.codex',
                    'migration': AI_AGENT_MIGRATION,
                },
                {
                    'kind': 'seed',
                    'object_name': 'mindmap_ai_connector.native_mindmap',
                    'migration': AI_AGENT_MIGRATION,
                },
            ],
        )

    def test_missing_ai_menu_and_role_grants_block_release(self) -> None:
        snapshot = complete_snapshot()
        snapshot['aiMenuPermissions'].remove('mindmap:ai:use')
        snapshot['aiMenuPermissions'].remove('mindmap:ai:admin')
        snapshot['aiAdminRoleGrant'] = False
        snapshot['aiAdminUseGrant'] = False
        snapshot['aiUseRoleInheritanceComplete'] = False

        issues = [item.to_dict() for item in find_mindmap_schema_issues(snapshot)]

        self.assertIn({
            'kind': 'seed',
            'object_name': 'sys_menu.mindmap:ai:use',
            'migration': AI_AGENT_MIGRATION,
        }, issues)
        self.assertIn({
            'kind': 'seed',
            'object_name': 'sys_menu.mindmap:ai:admin',
            'migration': AI_AGENT_MIGRATION,
        }, issues)
        self.assertIn({
            'kind': 'role_grant',
            'object_name': 'sys_role_menu.role_1:mindmap:ai:admin',
            'migration': AI_AGENT_MIGRATION,
        }, issues)
        self.assertIn({
            'kind': 'role_grant',
            'object_name': 'sys_role_menu.role_1:mindmap:ai:use',
            'migration': AI_AGENT_MIGRATION,
        }, issues)
        self.assertIn({
            'kind': 'role_grant',
            'object_name': 'sys_role_menu.mindmap:ai:use_inheritance',
            'migration': AI_AGENT_MIGRATION,
        }, issues)

    def test_ai_job_idempotency_index_must_remain_unique(self) -> None:
        snapshot = complete_snapshot()
        snapshot['indexDefinitions']['mindmap_ai_job'][
            'uk_mindmap_ai_job_user_idempotency'
        ]['unique'] = False

        self.assertIn(
            {
                'kind': 'index_definition',
                'object_name': 'mindmap_ai_job.uk_mindmap_ai_job_user_idempotency',
                'migration': AI_AGENT_MIGRATION,
            },
            [item.to_dict() for item in find_mindmap_schema_issues(snapshot)],
        )

    def test_ai_retention_index_definition_is_release_blocking(self) -> None:
        snapshot = complete_snapshot()
        snapshot['indexDefinitions']['mindmap_ai_job'][
            'idx_mindmap_ai_job_status_expires'
        ]['columns'] = ('expires_time', 'status', 'id')

        self.assertIn(
            {
                'kind': 'index_definition',
                'object_name': 'mindmap_ai_job.idx_mindmap_ai_job_status_expires',
                'migration': AI_AGENT_MIGRATION,
            },
            [item.to_dict() for item in find_mindmap_schema_issues(snapshot)],
        )

    def test_missing_category_type_requires_unified_tag_migration(self) -> None:
        snapshot = complete_snapshot()
        snapshot['columns']['mindmap_tag_category'].remove('category_type')

        self.assertIn(
            {
                'kind': 'column',
                'object_name': 'mindmap_tag_category.category_type',
                'migration': UNIFIED_TAG_MIGRATION,
            },
            [item.to_dict() for item in find_mindmap_schema_issues(snapshot)],
        )

    def test_missing_category_home_flag_requires_home_migration(self) -> None:
        snapshot = complete_snapshot()
        snapshot['columns']['mindmap_tag_category'].remove('show_on_home')

        self.assertIn(
            {
                'kind': 'column',
                'object_name': 'mindmap_tag_category.show_on_home',
                'migration': TAG_CATEGORY_HOME_MIGRATION,
            },
            [item.to_dict() for item in find_mindmap_schema_issues(snapshot)],
        )

    def test_missing_category_selection_mode_requires_selection_migration(self) -> None:
        snapshot = complete_snapshot()
        snapshot['columns']['mindmap_tag_category'].remove('selection_mode')

        self.assertIn(
            {
                'kind': 'column',
                'object_name': 'mindmap_tag_category.selection_mode',
                'migration': TAG_CATEGORY_SELECTION_MIGRATION,
            },
            [item.to_dict() for item in find_mindmap_schema_issues(snapshot)],
        )

    def test_creation_idempotency_unique_key_must_remain_unique(self) -> None:
        snapshot = complete_snapshot()
        snapshot['indexDefinitions']['mindmap_creation_request'][
            'uk_mindmap_creation_owner_request'
        ]['unique'] = False

        self.assertIn(
            {
                'kind': 'index_definition',
                'object_name': (
                    'mindmap_creation_request.uk_mindmap_creation_owner_request'
                ),
                'migration': '20260819_mindmap_creation_idempotency.sql',
            },
            [item.to_dict() for item in find_mindmap_schema_issues(snapshot)],
        )

    def test_comment_idempotency_column_and_unique_key_are_release_blocking(self) -> None:
        snapshot = complete_snapshot()
        snapshot['columns']['mindmap_comment'].remove('client_request_id')
        snapshot['indexDefinitions']['mindmap_comment'][
            'uk_mindmap_comment_author_request'
        ]['unique'] = False

        issues = [item.to_dict() for item in find_mindmap_schema_issues(snapshot)]

        self.assertIn({
            'kind': 'column',
            'object_name': 'mindmap_comment.client_request_id',
            'migration': '20260826_mindmap_comment_idempotency.sql',
        }, issues)
        self.assertIn({
            'kind': 'index_definition',
            'object_name': 'mindmap_comment.uk_mindmap_comment_author_request',
            'migration': '20260826_mindmap_comment_idempotency.sql',
        }, issues)

    def test_retention_index_column_order_is_release_blocking(self) -> None:
        snapshot = complete_snapshot()
        snapshot['indexDefinitions']['mindmap_change_log'][
            'idx_mindmap_change_retention'
        ]['columns'] = ('id', 'created_time')

        self.assertIn(
            {
                'kind': 'index_definition',
                'object_name': 'mindmap_change_log.idx_mindmap_change_retention',
                'migration': '20260819_mindmap_retention_indexes.sql',
            },
            [item.to_dict() for item in find_mindmap_schema_issues(snapshot)],
        )

    def test_same_name_with_wrong_index_definition_is_not_ready(self) -> None:
        snapshot = complete_snapshot()
        snapshot['indexDefinitions']['mindmap']['idx_mindmap_owner_status'] = {
            'columns': ('owner_id', 'status'),
            'unique': False,
        }

        issues = find_mindmap_schema_issues(snapshot)

        self.assertIn(
            {
                'kind': 'index_definition',
                'object_name': 'mindmap.idx_mindmap_owner_status',
                'migration': '20260818_mindmap_archive_lifecycle.sql',
            },
            [item.to_dict() for item in issues],
        )

    def test_retired_template_schema_requires_removal_migration(self) -> None:
        snapshot = complete_snapshot()
        snapshot['tables'].add('mindmap_template_category')
        snapshot['columns']['mindmap'].update({'is_template', 'template_category_id'})
        snapshot['indexes']['mindmap'].add('idx_mindmap_template_market')
        snapshot['foreignKeys']['mindmap'].add('fk_mindmap_template_category')

        issues = [item.to_dict() for item in find_mindmap_schema_issues(snapshot)]

        self.assertIn(
            {
                'kind': 'legacy_table',
                'object_name': 'mindmap_template_category',
                'migration': TEMPLATE_REMOVAL_MIGRATION,
            },
            issues,
        )
        self.assertEqual(
            {item['migration'] for item in issues},
            {TEMPLATE_REMOVAL_MIGRATION},
        )

    def test_tag_category_integrity_definitions_are_release_blocking(self) -> None:
        snapshot = complete_snapshot()
        snapshot['indexDefinitions']['mindmap_tag_category'][
            'uq_mindmap_tag_category_owner_name'
        ]['unique'] = False
        snapshot['foreignKeyDefinitions']['mindmap_tag']['fk_mindmap_tag_category'][
            'referredTable'
        ] = 'wrong_category'

        issues = [item.to_dict() for item in find_mindmap_schema_issues(snapshot)]

        self.assertIn(
            {
                'kind': 'index_definition',
                'object_name': 'mindmap_tag_category.uq_mindmap_tag_category_owner_name',
                'migration': '20260819_mindmap_tag_category_integrity.sql',
            },
            issues,
        )
        self.assertIn(
            {
                'kind': 'foreign_key_definition',
                'object_name': 'mindmap_tag.fk_mindmap_tag_category',
                'migration': '20260819_mindmap_tag_category_integrity.sql',
            },
            issues,
        )

    def test_legacy_tag_field_schema_requires_unified_tag_migration(self) -> None:
        snapshot = complete_snapshot()
        snapshot['tables'].update({'mindmap_tag_field', 'mindmap_tag_field_option'})
        snapshot['columns']['mindmap_node_tag'].update({'field_id', 'option_id'})
        snapshot['indexes']['mindmap_node_tag'].add('idx_mindmap_node_tag_option')
        snapshot['foreignKeys']['mindmap_node_tag'].update({
            'fk_mindmap_node_tag_field', 'fk_mindmap_node_tag_option',
        })

        issues = [item.to_dict() for item in find_mindmap_schema_issues(snapshot)]

        self.assertTrue(issues)
        self.assertTrue(all(item['migration'] == UNIFIED_TAG_MIGRATION for item in issues))
        self.assertIn({
            'kind': 'legacy_table',
            'object_name': 'mindmap_tag_field',
            'migration': UNIFIED_TAG_MIGRATION,
        }, issues)


if __name__ == '__main__':
    unittest.main()
