"""脑图数据库 Schema 预检测试。"""

import unittest

from module_mindmap.service.mindmap_schema_verifier import (
    REQUIRED_COLUMNS,
    REQUIRED_FOREIGN_KEY_DEFINITIONS,
    REQUIRED_FOREIGN_KEYS,
    REQUIRED_INDEX_DEFINITIONS,
    REQUIRED_INDEXES,
    REQUIRED_TABLES,
    TEMPLATE_REMOVAL_MIGRATION,
    UNIFIED_TAG_MIGRATION,
    find_mindmap_schema_issues,
)


def complete_snapshot() -> dict[str, object]:
    tables = (
        set(REQUIRED_TABLES)
        | {table for table, _ in REQUIRED_COLUMNS}
        | {table for table, _ in REQUIRED_INDEXES}
        | {table for table, _ in REQUIRED_FOREIGN_KEYS}
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
                }
                for (target, key), definition in REQUIRED_FOREIGN_KEY_DEFINITIONS.items()
                if target == table
            }
            for table in tables
        },
    }


class MindmapSchemaVerifierTest(unittest.TestCase):
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
