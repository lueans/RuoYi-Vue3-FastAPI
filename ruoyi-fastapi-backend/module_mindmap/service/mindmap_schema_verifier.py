"""脑图数据库迁移产物的只读契约校验。"""

import re
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

STRUCTURED_MIGRATION = '20260817_mindmap_structured_content.sql'
INCREMENTAL_MIGRATION = '20260817_mindmap_incremental_changes.sql'
VERSION_MIGRATION = '20260817_mindmap_version_tag_snapshots.sql'
FOLDER_MIGRATION = '20260818_mindmap_folder_lifecycle.sql'
ARCHIVE_MIGRATION = '20260818_mindmap_archive_lifecycle.sql'
CREATION_IDEMPOTENCY_MIGRATION = '20260819_mindmap_creation_idempotency.sql'
RETENTION_INDEX_MIGRATION = '20260819_mindmap_retention_indexes.sql'
TAG_CATEGORY_INTEGRITY_MIGRATION = '20260819_mindmap_tag_category_integrity.sql'
UNIFIED_TAG_MIGRATION = '20260824_mindmap_unified_tags.sql'
COMMENT_MIGRATION = '20260825_mindmap_comments.sql'
COMMENT_IDEMPOTENCY_MIGRATION = '20260826_mindmap_comment_idempotency.sql'
TEMPLATE_REMOVAL_MIGRATION = '20260827_remove_mindmap_template_feature.sql'
TAG_CATEGORY_HOME_MIGRATION = '20260828_mindmap_tag_category_home.sql'
TAG_CATEGORY_SELECTION_MIGRATION = '20260828_mindmap_tag_category_selection_mode.sql'
AI_AGENT_MIGRATION = '20260910_mindmap_ai_agent.sql'

AI_ADMIN_PERMISSION = 'mindmap:ai:admin'
AI_USE_PERMISSION = 'mindmap:ai:use'
REQUIRED_AI_CONNECTOR_SEEDS = dict.fromkeys(
    ('native_mindmap', 'codex', 'claude'),
    AI_AGENT_MIGRATION,
)
REQUIRED_AI_MENU_PERMISSION_SEEDS = {
    AI_USE_PERMISSION: AI_AGENT_MIGRATION,
    AI_ADMIN_PERMISSION: AI_AGENT_MIGRATION,
}
REQUIRED_AI_ROLE_GRANTS = {
    f'role_1:{AI_USE_PERMISSION}': AI_AGENT_MIGRATION,
    f'role_1:{AI_ADMIN_PERMISSION}': AI_AGENT_MIGRATION,
    f'{AI_USE_PERMISSION}_inheritance': AI_AGENT_MIGRATION,
}
AI_ROLE_GRANT_SNAPSHOT_FIELDS = (
    ('aiAdminRoleGrant', f'role_1:{AI_ADMIN_PERMISSION}'),
    ('aiAdminUseGrant', f'role_1:{AI_USE_PERMISSION}'),
    ('aiUseRoleInheritanceComplete', f'{AI_USE_PERMISSION}_inheritance'),
)
# SQL IN 列表以 REQUIRED_AI_MENU_PERMISSION_SEEDS 为唯一来源，避免字面量双写。
_AI_MENU_PERMISSION_SQL_IN_LIST = ', '.join(
    f"'{permission}'" for permission in sorted(REQUIRED_AI_MENU_PERMISSION_SEEDS)
)
AI_BOOTSTRAP_ISSUE_KINDS = frozenset({'seed', 'role_grant'})

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
    'mindmap_ai_session': AI_AGENT_MIGRATION,
    'mindmap_ai_connector': AI_AGENT_MIGRATION,
    'mindmap_ai_job': AI_AGENT_MIGRATION,
    'mindmap_ai_artifact': AI_AGENT_MIGRATION,
    'mindmap_ai_proposal': AI_AGENT_MIGRATION,
    'mindmap_ai_job_event': AI_AGENT_MIGRATION,
    'mindmap_ai_undo': AI_AGENT_MIGRATION,
    'mindmap_ai_response': AI_AGENT_MIGRATION,
    'mindmap_ai_draft_checkpoint': AI_AGENT_MIGRATION,
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
    ('mindmap_ai_job', 'response_id'): AI_AGENT_MIGRATION,
    ('mindmap_ai_job', 'execution_epoch'): AI_AGENT_MIGRATION,
} | {
    ('mindmap_ai_response', column): AI_AGENT_MIGRATION
    for column in (
        'id', 'job_id', 'user_id', 'content_type', 'content_text',
        'content_hash', 'byte_size', 'created_time', 'expires_time',
    )
} | {
    ('mindmap_ai_draft_checkpoint', column): AI_AGENT_MIGRATION
    for column in (
        'job_id', 'preview_version', 'preview_epoch', 'document_ciphertext',
        'operations_ciphertext', 'initial_state_ciphertext', 'document_hash',
        'summary_json', 'expires_time', 'created_time', 'update_time',
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
} | {
    (table, column): AI_AGENT_MIGRATION
    for table, columns in {
        'mindmap_ai_session': (
            'id', 'user_id', 'current_agent_key', 'title', 'status',
            'latest_artifact_id', 'created_time', 'update_time', 'expires_time',
        ),
        'mindmap_ai_connector': (
            'agent_key', 'enabled', 'rollout_percentage', 'credential_ref',
            'data_region', 'retention_policy', 'network_policy', 'health_status',
            'health_reason', 'conformance_status', 'conformance_report_json',
            'last_health_time', 'last_conformance_time', 'create_by',
            'created_time', 'update_by', 'update_time',
        ),
        'mindmap_ai_job': (
            'id', 'user_id', 'session_id', 'parent_job_id', 'retry_of_job_id',
            'turn_index', 'agent_key', 'adapter_version', 'sdk_version',
            'runtime_version', 'model_ref', 'intent', 'target', 'source_type',
            'source_mindmap_id', 'base_revision', 'base_hash', 'base_room_epoch',
            'request_json', 'request_fingerprint', 'idempotency_key', 'status',
            'progress', 'title', 'artifact_id', 'proposal_id',
            'external_session_ref', 'usage_json', 'error_code', 'error_message',
            'cancel_requested_time', 'completed_time', 'expires_time',
            'created_time', 'update_time',
        ),
        'mindmap_ai_artifact': (
            'id', 'job_id', 'user_id', 'title', 'content_json', 'document_hash',
            'validation_status', 'validator_version', 'node_count', 'tree_depth',
            'byte_size', 'created_time', 'expires_time',
        ),
        'mindmap_ai_proposal': (
            'id', 'job_id', 'user_id', 'proposal_type', 'base_document_id',
            'target_mindmap_id', 'base_revision', 'base_hash', 'base_room_epoch',
            'scope_json', 'operations_json', 'result_artifact_id', 'result_hash',
            'impact_json', 'warnings_json', 'status', 'applied_revision',
            'applied_time', 'created_time', 'expires_time',
        ),
        'mindmap_ai_job_event': (
            'id', 'job_id', 'sequence', 'event_type', 'payload_json', 'created_time',
        ),
        'mindmap_ai_undo': (
            'proposal_id', 'user_id', 'mindmap_id', 'before_document_json',
            'before_hash', 'applied_hash', 'applied_revision', 'status',
            'undone_revision', 'created_time', 'expires_time',
        ),
    }.items()
    for column in columns
} | {
    ('mindmap_ai_connector', column): AI_AGENT_MIGRATION
    for column in (
        'model_allowlist_json', 'max_budget_usd', 'timeout_seconds',
        'max_nodes', 'max_depth', 'max_concurrent_jobs',
    )
} | {
    ('mindmap_ai_job', column): AI_AGENT_MIGRATION
    for column in (
        'max_budget_usd', 'timeout_seconds', 'max_nodes', 'max_depth', 'retention_days',
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
    ('mindmap_ai_session', 'idx_mindmap_ai_session_user_updated'): AI_AGENT_MIGRATION,
    ('mindmap_ai_job', 'uk_mindmap_ai_job_user_idempotency'): AI_AGENT_MIGRATION,
    ('mindmap_ai_job', 'idx_mindmap_ai_job_user_created'): AI_AGENT_MIGRATION,
    ('mindmap_ai_job', 'idx_mindmap_ai_job_session_turn'): AI_AGENT_MIGRATION,
    ('mindmap_ai_job', 'idx_mindmap_ai_job_status_updated'): AI_AGENT_MIGRATION,
    ('mindmap_ai_job', 'idx_mindmap_ai_job_status_expires'): AI_AGENT_MIGRATION,
    ('mindmap_ai_artifact', 'uk_mindmap_ai_artifact_job'): AI_AGENT_MIGRATION,
    ('mindmap_ai_artifact', 'idx_mindmap_ai_artifact_user_created'): AI_AGENT_MIGRATION,
    ('mindmap_ai_artifact', 'idx_mindmap_ai_artifact_expires'): AI_AGENT_MIGRATION,
    ('mindmap_ai_proposal', 'uk_mindmap_ai_proposal_job'): AI_AGENT_MIGRATION,
    ('mindmap_ai_proposal', 'idx_mindmap_ai_proposal_user_status'): AI_AGENT_MIGRATION,
    ('mindmap_ai_job_event', 'uk_mindmap_ai_event_job_sequence'): AI_AGENT_MIGRATION,
    ('mindmap_ai_job_event', 'idx_mindmap_ai_event_job_id'): AI_AGENT_MIGRATION,
    ('mindmap_ai_undo', 'idx_mindmap_ai_undo_user_created'): AI_AGENT_MIGRATION,
    ('mindmap_ai_undo', 'idx_mindmap_ai_undo_expires'): AI_AGENT_MIGRATION,
    ('mindmap_ai_response', 'uk_mindmap_ai_response_job'): AI_AGENT_MIGRATION,
    ('mindmap_ai_response', 'idx_mindmap_ai_response_user_created'): AI_AGENT_MIGRATION,
    ('mindmap_ai_response', 'idx_mindmap_ai_response_expires'): AI_AGENT_MIGRATION,
    (
        'mindmap_ai_draft_checkpoint',
        'idx_mindmap_ai_draft_checkpoint_expires',
    ): AI_AGENT_MIGRATION,
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
    ('mindmap_ai_session', 'idx_mindmap_ai_session_user_updated'): (
        ('user_id', 'update_time'),
        False,
    ),
    ('mindmap_ai_job', 'uk_mindmap_ai_job_user_idempotency'): (
        ('user_id', 'idempotency_key'),
        True,
    ),
    ('mindmap_ai_job', 'idx_mindmap_ai_job_user_created'): (
        ('user_id', 'created_time'),
        False,
    ),
    ('mindmap_ai_job', 'idx_mindmap_ai_job_session_turn'): (
        ('session_id', 'turn_index'),
        False,
    ),
    ('mindmap_ai_job', 'idx_mindmap_ai_job_status_updated'): (
        ('status', 'update_time'),
        False,
    ),
    ('mindmap_ai_job', 'idx_mindmap_ai_job_status_expires'): (
        ('status', 'expires_time', 'id'),
        False,
    ),
    ('mindmap_ai_artifact', 'uk_mindmap_ai_artifact_job'): (
        ('job_id',),
        True,
    ),
    ('mindmap_ai_artifact', 'idx_mindmap_ai_artifact_user_created'): (
        ('user_id', 'created_time'),
        False,
    ),
    ('mindmap_ai_artifact', 'idx_mindmap_ai_artifact_expires'): (
        ('expires_time',),
        False,
    ),
    ('mindmap_ai_proposal', 'uk_mindmap_ai_proposal_job'): (
        ('job_id',),
        True,
    ),
    ('mindmap_ai_proposal', 'idx_mindmap_ai_proposal_user_status'): (
        ('user_id', 'status'),
        False,
    ),
    ('mindmap_ai_job_event', 'uk_mindmap_ai_event_job_sequence'): (
        ('job_id', 'sequence'),
        True,
    ),
    ('mindmap_ai_job_event', 'idx_mindmap_ai_event_job_id'): (
        ('job_id', 'id'),
        False,
    ),
    ('mindmap_ai_undo', 'idx_mindmap_ai_undo_user_created'): (
        ('user_id', 'created_time'),
        False,
    ),
    ('mindmap_ai_undo', 'idx_mindmap_ai_undo_expires'): (
        ('expires_time', 'proposal_id'),
        False,
    ),
    ('mindmap_ai_response', 'uk_mindmap_ai_response_job'): (
        ('job_id',),
        True,
    ),
    ('mindmap_ai_response', 'idx_mindmap_ai_response_user_created'): (
        ('user_id', 'created_time'),
        False,
    ),
    ('mindmap_ai_response', 'idx_mindmap_ai_response_expires'): (
        ('expires_time', 'id'),
        False,
    ),
    ('mindmap_ai_draft_checkpoint', 'idx_mindmap_ai_draft_checkpoint_expires'): (
        ('expires_time', 'job_id'),
        False,
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

REQUIRED_FOREIGN_KEY_DELETE_RULES = {}

REQUIRED_CHECK_CONSTRAINTS = {}

REQUIRED_CHECK_CONSTRAINT_DEFINITIONS = {}

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
    """获取跨数据库可比较的结构和 AI 控制面关键种子快照。"""
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    relevant_tables = (
        set(REQUIRED_TABLES)
        | {table for table, _ in REQUIRED_COLUMNS}
        | {table for table, _ in REQUIRED_INDEXES}
        | {table for table, _ in REQUIRED_FOREIGN_KEYS}
        | {table for table, _ in REQUIRED_CHECK_CONSTRAINTS}
        | set(FORBIDDEN_TABLES)
        | {table for table, _ in FORBIDDEN_COLUMNS}
        | {table for table, _ in FORBIDDEN_INDEXES}
        | {table for table, _ in FORBIDDEN_FOREIGN_KEYS}
        | {'sys_menu', 'sys_role_menu'}
    )
    columns: dict[str, set[str]] = {}
    indexes: dict[str, set[str]] = {}
    index_definitions: dict[str, dict[str, dict[str, Any]]] = {}
    foreign_keys: dict[str, set[str]] = {}
    foreign_key_definitions: dict[str, dict[str, dict[str, Any]]] = {}
    check_constraints: dict[str, set[str]] = {}
    check_constraint_definitions: dict[str, dict[str, str]] = {}
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
                'onDelete': str((item.get('options') or {}).get('ondelete') or '').upper(),
            }
            for item in table_foreign_keys
        }
        table_checks = [
            item for item in inspector.get_check_constraints(table) if item.get('name')
        ]
        check_constraints[table] = {str(item['name']) for item in table_checks}
        check_constraint_definitions[table] = {
            str(item['name']): str(item.get('sqltext') or '')
            for item in table_checks
        }

    ai_connector_keys: set[str] = set()
    if (
        'mindmap_ai_connector' in tables
        and 'agent_key' in columns.get('mindmap_ai_connector', set())
    ):
        connector_rows = connection.execute(text(
            "SELECT agent_key FROM mindmap_ai_connector "
            "WHERE agent_key IN ('native_mindmap', 'codex', 'claude')"
        ))
        ai_connector_keys = {str(value) for value in connector_rows.scalars()}

    ai_menu_permissions: set[str] = set()
    if {'perms', 'status'} <= columns.get('sys_menu', set()):
        menu_rows = connection.execute(text(
            "SELECT perms FROM sys_menu "
            f"WHERE perms IN ({_AI_MENU_PERMISSION_SQL_IN_LIST}) "
            "AND status = '0'"
        ))
        ai_menu_permissions = {str(value) for value in menu_rows.scalars()}

    ai_admin_role_grant = False
    ai_admin_use_grant = False
    ai_use_role_inheritance_complete = False
    if (
        {'menu_id', 'perms'} <= columns.get('sys_menu', set())
        and {'menu_id', 'role_id'} <= columns.get('sys_role_menu', set())
    ):
        granted_role_perms = {
            str(value)
            for value in connection.execute(text(
                "SELECT menu.perms FROM sys_role_menu role_menu "
                "JOIN sys_menu menu ON menu.menu_id = role_menu.menu_id "
                "WHERE role_menu.role_id = 1 "
                f"AND menu.perms IN ({_AI_MENU_PERMISSION_SQL_IN_LIST})"
            )).scalars()
        }
        ai_admin_role_grant = AI_ADMIN_PERMISSION in granted_role_perms
        ai_admin_use_grant = AI_USE_PERMISSION in granted_role_perms

        missing_inherited_grant_count = connection.execute(text(
            "SELECT COUNT(DISTINCT source_role_menu.role_id) "
            "FROM sys_role_menu source_role_menu "
            "JOIN sys_menu source_menu ON source_menu.menu_id = source_role_menu.menu_id "
            "WHERE source_menu.perms IN ("
            "'mindmap:list', 'mindmap:query', "
            "'mindmap:mindmap:list', 'mindmap:mindmap:query'"
            ") AND NOT EXISTS ("
            "SELECT 1 FROM sys_role_menu ai_role_menu "
            "JOIN sys_menu ai_menu ON ai_menu.menu_id = ai_role_menu.menu_id "
            "WHERE ai_role_menu.role_id = source_role_menu.role_id "
            f"AND ai_menu.perms = '{AI_USE_PERMISSION}'"
            ")"
        )).scalar()
        ai_use_role_inheritance_complete = int(missing_inherited_grant_count or 0) == 0
    return {
        'tables': tables,
        'columns': columns,
        'indexes': indexes,
        'indexDefinitions': index_definitions,
        'foreignKeys': foreign_keys,
        'foreignKeyDefinitions': foreign_key_definitions,
        'checkConstraints': check_constraints,
        'checkConstraintDefinitions': check_constraint_definitions,
        'aiConnectorKeys': ai_connector_keys,
        'aiMenuPermissions': ai_menu_permissions,
        'aiAdminRoleGrant': ai_admin_role_grant,
        'aiAdminUseGrant': ai_admin_use_grant,
        'aiUseRoleInheritanceComplete': ai_use_role_inheritance_complete,
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
                or (
                    (expected_delete_rule := REQUIRED_FOREIGN_KEY_DELETE_RULES.get(
                        (table, foreign_key)
                    )) is not None
                    and str(actual.get('onDelete') or '').upper() != expected_delete_rule
                )
            ):
                issues.append(
                    MindmapSchemaIssue('foreign_key_definition', f'{table}.{foreign_key}', migration)
                )
    return issues


def _find_required_check_constraint_issues(
    snapshot: dict[str, Any],
    tables: set[str],
) -> list[MindmapSchemaIssue]:
    check_constraints = snapshot.get('checkConstraints') or {}
    definitions = snapshot.get('checkConstraintDefinitions')
    issues: list[MindmapSchemaIssue] = []
    for (table, constraint), migration in REQUIRED_CHECK_CONSTRAINTS.items():
        if table not in tables:
            continue
        if constraint not in set(check_constraints.get(table) or ()):
            issues.append(MindmapSchemaIssue(
                'check_constraint',
                f'{table}.{constraint}',
                migration,
            ))
            continue
        if definitions is None:
            continue
        sqltext = str((definitions.get(table) or {}).get(constraint) or '')
        expected_column, expected_values = REQUIRED_CHECK_CONSTRAINT_DEFINITIONS[
            (table, constraint)
        ]
        normalized = re.sub(r'[`"\[\]\s()]', '', sqltext).lower()
        literal_values = frozenset(re.findall(r"'((?:''|[^'])*)'", sqltext.lower()))
        if expected_column.lower() not in normalized or literal_values != expected_values:
            issues.append(MindmapSchemaIssue(
                'check_constraint_definition',
                f'{table}.{constraint}',
                migration,
            ))
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


def _find_ai_bootstrap_issues(snapshot: dict[str, Any]) -> list[MindmapSchemaIssue]:
    """检查 AI Agent 可运行所需的非敏感控制面种子与角色授权。"""
    connector_keys = set(snapshot.get('aiConnectorKeys') or ())
    menu_permissions = set(snapshot.get('aiMenuPermissions') or ())
    issues = [
        MindmapSchemaIssue(
            'seed',
            f'mindmap_ai_connector.{agent_key}',
            migration,
        )
        for agent_key, migration in REQUIRED_AI_CONNECTOR_SEEDS.items()
        if agent_key not in connector_keys
    ]
    issues.extend(
        MindmapSchemaIssue('seed', f'sys_menu.{permission}', migration)
        for permission, migration in REQUIRED_AI_MENU_PERMISSION_SEEDS.items()
        if permission not in menu_permissions
    )
    issues.extend(
        MindmapSchemaIssue(
            'role_grant',
            f'sys_role_menu.{grant_key}',
            REQUIRED_AI_ROLE_GRANTS[grant_key],
        )
        for snapshot_key, grant_key in AI_ROLE_GRANT_SNAPSHOT_FIELDS
        if not snapshot.get(snapshot_key, False)
    )
    return issues


def find_mindmap_schema_issues(snapshot: dict[str, Any]) -> list[MindmapSchemaIssue]:
    """返回缺失迁移产物与非敏感 AI 控制面种子；不输出业务数据。"""
    tables = set(snapshot.get('tables') or ())
    issues = _find_required_schema_issues(snapshot, tables)
    issues.extend(_find_required_index_issues(snapshot, tables))
    issues.extend(_find_required_foreign_key_issues(snapshot, tables))
    issues.extend(_find_required_check_constraint_issues(snapshot, tables))
    issues.extend(_find_forbidden_schema_issues(snapshot, tables))
    issues.extend(_find_ai_bootstrap_issues(snapshot))

    return sorted(issues, key=lambda item: (item.migration, item.kind, item.object_name))
