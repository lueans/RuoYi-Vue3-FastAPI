"""生成脑图数据库结构迁移的只读发布计划。"""

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

from module_mindmap.service.mindmap_schema_verifier import MindmapSchemaIssue


@dataclass(frozen=True)
class MindmapMigrationDefinition:
    filename: str
    purpose: str


@dataclass(frozen=True)
class MindmapMigrationPlanItem:
    order: int
    migration: str
    purpose: str
    sha256: str
    missing_objects: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload['missingObjects'] = payload.pop('missing_objects')
        return payload


MINDMAP_SCHEMA_MIGRATIONS = (
    MindmapMigrationDefinition(
        '20260817_mindmap_structured_content.sql',
        '建立文件/节点结构化内容、统一标签绑定和内容迁移记录',
    ),
    MindmapMigrationDefinition(
        '20260817_mindmap_incremental_changes.sql',
        '建立增量变更日志并补齐协作内容修订号',
    ),
    MindmapMigrationDefinition(
        '20260817_mindmap_version_tag_snapshots.sql',
        '补齐版本结构号和标签定义快照',
    ),
    MindmapMigrationDefinition(
        '20260818_mindmap_archive_lifecycle.sql',
        '归一化归档状态并建立所有者归档列表索引',
    ),
    MindmapMigrationDefinition(
        '20260818_mindmap_folder_lifecycle.sql',
        '修复目录历史数据并建立活动目录唯一约束和列表索引',
    ),
    MindmapMigrationDefinition(
        '20260818_mindmap_template_workflow.sql',
        '合并模板重复分类并建立唯一约束、外键和市场索引',
    ),
    MindmapMigrationDefinition(
        '20260819_mindmap_creation_idempotency.sql',
        '建立脑图创建请求幂等记录，保证响应丢失与并发重试只创建一个文件',
    ),
    MindmapMigrationDefinition(
        '20260819_mindmap_retention_indexes.sql',
        '建立创建幂等与增量变更日志的有界保留扫描索引',
    ),
    MindmapMigrationDefinition(
        '20260819_mindmap_tag_category_integrity.sql',
        '合并标签重复分类并建立作用域唯一约束和标签分类外键',
    ),
    MindmapMigrationDefinition(
        '20260820_mindmap_node_tag_integrity.sql',
        '收敛字段与选项悬空引用并建立节点标签绑定外键',
    ),
    MindmapMigrationDefinition(
        '20260824_mindmap_unified_tags.sql',
        '把历史标签字段选项迁移为统一标签并删除旧字段模型',
    ),
)

POSTGRESQL_MIGRATION_OVERRIDES = {
    '20260824_mindmap_unified_tags.sql': '20260824_mindmap_unified_tags_postgresql.sql',
}


def resolve_migration_filename(filename: str, database_type: str) -> str:
    """返回当前数据库方言实际可执行的迁移文件名。"""
    if database_type == 'postgresql':
        return POSTGRESQL_MIGRATION_OVERRIDES.get(filename, filename)
    return filename


MANUAL_REVIEW_MIGRATIONS = (
    {
        'migration': '20260818_mindmap_permission_namespace.sql',
        'reason': '该迁移只调整权限业务数据，不能通过结构元数据判断是否需要执行，必须由运维核对权限清单。',
    },
    {
        'migration': '20260825_mindmap_markers_to_tags.sql',
        'postgresqlMigration': '20260825_mindmap_markers_to_tags_postgresql.sql',
        'reason': '该迁移写入 61 个内置标记标签并改写现有节点绑定，结构元数据无法判断是否已完成，发布时必须执行。',
    },
)


def referenced_migrations(issues: Iterable[MindmapSchemaIssue]) -> set[str]:
    return {issue.migration for issue in issues}


def build_mindmap_migration_plan(
    issues: Iterable[MindmapSchemaIssue],
    migrations_dir: Path,
    database_type: str = 'mysql',
) -> list[MindmapMigrationPlanItem]:
    """按固定依赖顺序归并缺失对象，并对实际 SQL 生成内容摘要。"""
    issue_list = list(issues)
    issue_migrations = referenced_migrations(issue_list)
    definitions = {item.filename: item for item in MINDMAP_SCHEMA_MIGRATIONS}
    unknown = issue_migrations - set(definitions)
    if unknown:
        raise ValueError(f'缺少迁移目录定义: {", ".join(sorted(unknown))}')

    plan: list[MindmapMigrationPlanItem] = []
    for order, definition in enumerate(MINDMAP_SCHEMA_MIGRATIONS, start=1):
        if definition.filename not in issue_migrations:
            continue
        migration_filename = resolve_migration_filename(definition.filename, database_type)
        migration_path = migrations_dir / migration_filename
        try:
            content = migration_path.read_bytes()
        except FileNotFoundError as exc:
            raise ValueError(f'迁移文件不存在: {migration_filename}') from exc
        if not content.strip():
            raise ValueError(f'迁移文件为空: {migration_filename}')
        missing_objects = tuple(
            sorted({
                f'{issue.kind}:{issue.object_name}'
                for issue in issue_list
                if issue.migration == definition.filename
            })
        )
        plan.append(
            MindmapMigrationPlanItem(
                order=order,
                migration=migration_filename,
                purpose=definition.purpose,
                sha256=sha256(content).hexdigest(),
                missing_objects=missing_objects,
            )
        )
    return plan
