"""脑图数据库迁移产物的只读契约校验。"""

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.engine import Connection

STRUCTURED_MIGRATION = '20260817_mindmap_structured_content.sql'
INCREMENTAL_MIGRATION = '20260817_mindmap_incremental_changes.sql'
VERSION_MIGRATION = '20260817_mindmap_version_tag_snapshots.sql'
FOLDER_MIGRATION = '20260818_mindmap_folder_lifecycle.sql'
ARCHIVE_MIGRATION = '20260818_mindmap_archive_lifecycle.sql'
CREATION_IDEMPOTENCY_MIGRATION = '20260819_mindmap_creation_idempotency.sql'
RETENTION_INDEX_MIGRATION = '20260819_mindmap_retention_indexes.sql'
TAG_CATEGORY_INTEGRITY_MIGRATION = '20260819_mindmap_tag_category_integrity.sql'
NODE_TAG_INTEGRITY_MIGRATION = '20260820_mindmap_node_tag_integrity.sql'
UNIFIED_TAG_MIGRATION = '20260824_mindmap_unified_tags.sql'
COMMENT_MIGRATION = '20260825_mindmap_comments.sql'
COMMENT_IDEMPOTENCY_MIGRATION = '20260826_mindmap_comment_idempotency.sql'
TEMPLATE_REMOVAL_MIGRATION = '20260827_remove_mindmap_template_feature.sql'
TAG_CATEGORY_HOME_MIGRATION = '20260828_mindmap_tag_category_home.sql'
TAG_CATEGORY_SELECTION_MIGRATION = '20260828_mindmap_tag_category_selection_mode.sql'

REQUIRED_TABLES = dict.fromkeys(
    (
        'mindmap_node',
        'mindmap_relation',
        'mindmap_summary',
        'mindmap_group',
        'mindmap_group_member',
        'mindmap_asset',
        'mindmap_node_tag',
        'mindmap_migration_record',
    ),
    STRUCTURED_MIGRATION,
) | {
    'mindmap_change_log': INCREMENTAL_MIGRATION,
    'mindmap_creation_request': CREATION_IDEMPOTENCY_MIGRATION,
    'mindmap_comment_thread': COMMENT_MIGRATION,
    'mindmap_comment': COMMENT_MIGRATION,
}

REQUIRED_COLUMNS = {
    ('mindmap', column): STRUCTURED_MIGRATION
    for column in (
        'root_node_id',
        'content_revision',
        'node_count',
        'schema_version',
        'engine_name',
        'engine_version',
        'document_data',
    )
} | {
    ('mindmap_tag', column): STRUCTURED_MIGRATION
    for column in ('status', 'definition_revision', 'usage_node_count', 'usage_file_count', 'update_by')
} | {
    ('mindmap_ws_state', 'content_revision'): INCREMENTAL_MIGRATION,
    ('mindmap_version', 'snapshot_schema_version'): VERSION_MIGRATION,
    ('mindmap_version', 'tag_snapshots'): VERSION_MIGRATION,
    ('mindmap_folder', 'active_name'): FOLDER_MIGRATION,
    ('mindmap_tag_category', 'category_type'): UNIFIED_TAG_MIGRATION,
    ('mindmap_tag_category', 'show_on_home'): TAG_CATEGORY_HOME_MIGRATION,
    ('mindmap_tag_category', 'selection_mode'): TAG_CATEGORY_SELECTION_MIGRATION,
    ('mindmap_comment', 'client_request_id'): COMMENT_IDEMPOTENCY_MIGRATION,
} | {
    ('mindmap_creation_request', column): CREATION_IDEMPOTENCY_MIGRATION
    for column in (
        'owner_id',
        'request_id',
        'operation',
        'request_fingerprint',
        'result_file_id',
        'created_by',
        'created_time',
        'completed_time',
    )
}

REQUIRED_INDEXES = {
    ('mindmap_folder', 'uq_mindmap_folder_active_sibling'): FOLDER_MIGRATION,
    ('mindmap', 'idx_mindmap_owner_folder'): FOLDER_MIGRATION,
    ('mindmap', 'idx_mindmap_owner_status'): ARCHIVE_MIGRATION,
    (
        'mindmap_creation_request',
        'uk_mindmap_creation_owner_request',
    ): CREATION_IDEMPOTENCY_MIGRATION,
    ('mindmap_creation_request', 'idx_mindmap_creation_result'): CREATION_IDEMPOTENCY_MIGRATION,
    ('mindmap_creation_request', 'idx_mindmap_creation_created'): CREATION_IDEMPOTENCY_MIGRATION,
    ('mindmap_creation_request', 'idx_mindmap_creation_retention'): RETENTION_INDEX_MIGRATION,
    ('mindmap_change_log', 'idx_mindmap_change_retention'): RETENTION_INDEX_MIGRATION,
    ('mindmap_comment_thread', 'idx_mindmap_comment_thread_file'): COMMENT_MIGRATION,
    ('mindmap_comment_thread', 'idx_mindmap_comment_thread_node'): COMMENT_MIGRATION,
    ('mindmap_comment', 'idx_mindmap_comment_thread'): COMMENT_MIGRATION,
    ('mindmap_comment', 'idx_mindmap_comment_author'): COMMENT_MIGRATION,
    (
        'mindmap_comment',
        'uk_mindmap_comment_author_request',
    ): COMMENT_IDEMPOTENCY_MIGRATION,
    (
        'mindmap_tag_category',
        'uq_mindmap_tag_category_owner_name',
    ): TAG_CATEGORY_INTEGRITY_MIGRATION,
}

REQUIRED_INDEX_DEFINITIONS = {
    ('mindmap_folder', 'uq_mindmap_folder_active_sibling'): (
        ('owner_id', 'parent_id', 'active_name'),
        True,
    ),
    ('mindmap', 'idx_mindmap_owner_folder'): (
        ('owner_id', 'folder_id', 'del_flag'),
        False,
    ),
    ('mindmap', 'idx_mindmap_owner_status'): (
        ('owner_id', 'status', 'del_flag', 'update_time'),
        False,
    ),
    ('mindmap_creation_request', 'uk_mindmap_creation_owner_request'): (
        ('owner_id', 'request_id'),
        True,
    ),
    ('mindmap_creation_request', 'idx_mindmap_creation_result'): (
        ('result_file_id',),
        False,
    ),
    ('mindmap_creation_request', 'idx_mindmap_creation_created'): (
        ('created_time',),
        False,
    ),
    ('mindmap_creation_request', 'idx_mindmap_creation_retention'): (
        ('completed_time', 'id'),
        False,
    ),
    ('mindmap_change_log', 'idx_mindmap_change_retention'): (
        ('created_time', 'id'),
        False,
    ),
    ('mindmap_tag_category', 'uq_mindmap_tag_category_owner_name'): (
        ('owner_id', 'name'),
        True,
    ),
    ('mindmap_comment_thread', 'idx_mindmap_comment_thread_file'): (
        ('mindmap_id', 'status', 'last_comment_time'),
        False,
    ),
    ('mindmap_comment_thread', 'idx_mindmap_comment_thread_node'): (
        ('mindmap_id', 'node_uid', 'status'),
        False,
    ),
    ('mindmap_comment', 'idx_mindmap_comment_thread'): (
        ('thread_id', 'created_time'),
        False,
    ),
    ('mindmap_comment', 'idx_mindmap_comment_author'): (
        ('created_by', 'created_time'),
        False,
    ),
    ('mindmap_comment', 'uk_mindmap_comment_author_request'): (
        ('created_by', 'client_request_id'),
        True,
    ),
}

REQUIRED_FOREIGN_KEYS = {
    ('mindmap_tag', 'fk_mindmap_tag_category'): TAG_CATEGORY_INTEGRITY_MIGRATION,
}

REQUIRED_FOREIGN_KEY_DEFINITIONS = {
    ('mindmap_tag', 'fk_mindmap_tag_category'): (
        ('category_id',),
        'mindmap_tag_category',
        ('id',),
    ),
}

FORBIDDEN_TABLES = {
    'mindmap_tag_field': UNIFIED_TAG_MIGRATION,
    'mindmap_tag_field_option': UNIFIED_TAG_MIGRATION,
    'mindmap_template_category': TEMPLATE_REMOVAL_MIGRATION,
}
FORBIDDEN_COLUMNS = {
    ('mindmap_node_tag', 'field_id'): UNIFIED_TAG_MIGRATION,
    ('mindmap_node_tag', 'option_id'): UNIFIED_TAG_MIGRATION,
    ('mindmap', 'is_template'): TEMPLATE_REMOVAL_MIGRATION,
    ('mindmap', 'template_category_id'): TEMPLATE_REMOVAL_MIGRATION,
}
FORBIDDEN_INDEXES = {
    ('mindmap_node_tag', 'idx_mindmap_node_tag_option'): UNIFIED_TAG_MIGRATION,
    ('mindmap', 'idx_mindmap_template_market'): TEMPLATE_REMOVAL_MIGRATION,
}
FORBIDDEN_FOREIGN_KEYS = {
    ('mindmap_node_tag', 'fk_mindmap_node_tag_field'): UNIFIED_TAG_MIGRATION,
    ('mindmap_node_tag', 'fk_mindmap_node_tag_option'): UNIFIED_TAG_MIGRATION,
    ('mindmap', 'fk_mindmap_template_category'): TEMPLATE_REMOVAL_MIGRATION,
}


@dataclass(frozen=True)
class MindmapSchemaIssue:
    kind: str
    object_name: str
    migration: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def inspect_mindmap_schema(connection: Connection) -> dict[str, Any]:
    """通过 SQLAlchemy Inspector 获取跨数据库可比较的元数据快照。"""
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    relevant_tables = (
        set(REQUIRED_TABLES)
        | {table for table, _ in REQUIRED_COLUMNS}
        | {table for table, _ in REQUIRED_INDEXES}
        | {table for table, _ in REQUIRED_FOREIGN_KEYS}
        | set(FORBIDDEN_TABLES)
        | {table for table, _ in FORBIDDEN_COLUMNS}
        | {table for table, _ in FORBIDDEN_INDEXES}
        | {table for table, _ in FORBIDDEN_FOREIGN_KEYS}
    )
    columns: dict[str, set[str]] = {}
    indexes: dict[str, set[str]] = {}
    index_definitions: dict[str, dict[str, dict[str, Any]]] = {}
    foreign_keys: dict[str, set[str]] = {}
    foreign_key_definitions: dict[str, dict[str, dict[str, Any]]] = {}
    for table in sorted(relevant_tables & tables):
        columns[table] = {str(item['name']) for item in inspector.get_columns(table)}
        table_indexes = [item for item in inspector.get_indexes(table) if item.get('name')]
        indexes[table] = {str(item['name']) for item in table_indexes}
        index_definitions[table] = {
            str(item['name']): {
                'columns': tuple(str(column) for column in item.get('column_names') or ()),
                'unique': bool(item.get('unique')),
            }
            for item in table_indexes
        }
        table_foreign_keys = [
            item for item in inspector.get_foreign_keys(table) if item.get('name')
        ]
        foreign_keys[table] = {str(item['name']) for item in table_foreign_keys}
        foreign_key_definitions[table] = {
            str(item['name']): {
                'columns': tuple(str(column) for column in item.get('constrained_columns') or ()),
                'referredTable': str(item.get('referred_table') or ''),
                'referredColumns': tuple(
                    str(column) for column in item.get('referred_columns') or ()
                ),
            }
            for item in table_foreign_keys
        }
    return {
        'tables': tables,
        'columns': columns,
        'indexes': indexes,
        'indexDefinitions': index_definitions,
        'foreignKeys': foreign_keys,
        'foreignKeyDefinitions': foreign_key_definitions,
    }


def _find_required_schema_issues(snapshot: dict[str, Any], tables: set[str]) -> list[MindmapSchemaIssue]:
    columns = snapshot.get('columns') or {}
    issues = [
        MindmapSchemaIssue('table', table, migration)
        for table, migration in REQUIRED_TABLES.items()
        if table not in tables
    ]
    issues.extend(
        MindmapSchemaIssue('column', f'{table}.{column}', migration)
        for (table, column), migration in REQUIRED_COLUMNS.items()
        if table in tables and column not in set(columns.get(table) or ())
    )
    return issues


def _find_required_index_issues(snapshot: dict[str, Any], tables: set[str]) -> list[MindmapSchemaIssue]:
    indexes = snapshot.get('indexes') or {}
    index_definitions = snapshot.get('indexDefinitions')
    issues: list[MindmapSchemaIssue] = []
    for (table, index), migration in REQUIRED_INDEXES.items():
        if table in tables and index not in set(indexes.get(table) or ()):
            issues.append(MindmapSchemaIssue('index', f'{table}.{index}', migration))
        elif table in tables and index_definitions is not None:
            actual = (index_definitions.get(table) or {}).get(index) or {}
            expected_columns, expected_unique = REQUIRED_INDEX_DEFINITIONS[(table, index)]
            if (
                tuple(actual.get('columns') or ()) != expected_columns
                or bool(actual.get('unique')) != expected_unique
            ):
                issues.append(MindmapSchemaIssue('index_definition', f'{table}.{index}', migration))
    return issues


def _find_required_foreign_key_issues(snapshot: dict[str, Any], tables: set[str]) -> list[MindmapSchemaIssue]:
    foreign_keys = snapshot.get('foreignKeys') or {}
    foreign_key_definitions = snapshot.get('foreignKeyDefinitions')
    issues: list[MindmapSchemaIssue] = []
    for (table, foreign_key), migration in REQUIRED_FOREIGN_KEYS.items():
        if table in tables and foreign_key not in set(foreign_keys.get(table) or ()):
            issues.append(MindmapSchemaIssue('foreign_key', f'{table}.{foreign_key}', migration))
        elif table in tables and foreign_key_definitions is not None:
            actual = (foreign_key_definitions.get(table) or {}).get(foreign_key) or {}
            expected_columns, expected_table, expected_referred_columns = (
                REQUIRED_FOREIGN_KEY_DEFINITIONS[(table, foreign_key)]
            )
            if (
                tuple(actual.get('columns') or ()) != expected_columns
                or actual.get('referredTable') != expected_table
                or tuple(actual.get('referredColumns') or ()) != expected_referred_columns
            ):
                issues.append(
                    MindmapSchemaIssue('foreign_key_definition', f'{table}.{foreign_key}', migration)
                )
    return issues


def _find_forbidden_schema_issues(snapshot: dict[str, Any], tables: set[str]) -> list[MindmapSchemaIssue]:
    columns = snapshot.get('columns') or {}
    indexes = snapshot.get('indexes') or {}
    foreign_keys = snapshot.get('foreignKeys') or {}
    issues = [
        MindmapSchemaIssue('legacy_table', table, FORBIDDEN_TABLES[table])
        for table in set(FORBIDDEN_TABLES) & tables
    ]
    for (table, column), migration in FORBIDDEN_COLUMNS.items():
        if table in tables and column in set(columns.get(table) or ()):
            issues.append(MindmapSchemaIssue('legacy_column', f'{table}.{column}', migration))
    for (table, index), migration in FORBIDDEN_INDEXES.items():
        if table in tables and index in set(indexes.get(table) or ()):
            issues.append(MindmapSchemaIssue('legacy_index', f'{table}.{index}', migration))
    for (table, foreign_key), migration in FORBIDDEN_FOREIGN_KEYS.items():
        if table in tables and foreign_key in set(foreign_keys.get(table) or ()):
            issues.append(MindmapSchemaIssue(
                'legacy_foreign_key', f'{table}.{foreign_key}', migration,
            ))
    return issues


def find_mindmap_schema_issues(snapshot: dict[str, Any]) -> list[MindmapSchemaIssue]:
    """返回缺失迁移产物；不检查或输出任何业务数据。"""
    tables = set(snapshot.get('tables') or ())
    issues = _find_required_schema_issues(snapshot, tables)
    issues.extend(_find_required_index_issues(snapshot, tables))
    issues.extend(_find_required_foreign_key_issues(snapshot, tables))
    issues.extend(_find_forbidden_schema_issues(snapshot, tables))

    return sorted(issues, key=lambda item: (item.migration, item.kind, item.object_name))
