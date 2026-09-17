from importlib import import_module
from typing import Any

from cli.exit_codes import DATABASE_ERROR
from cli.runtime.base import RUNTIME_ENVIRONMENT, RuntimeEnvironmentService

from .gateway import DatabaseInfrastructureGateway
from .support import DatabaseAlembicCommandSupport, DatabaseRevisionSupport


class DatabaseRuntimeService:
    """
    数据库运行时服务。

    该服务作为数据库运行时 facade，对外统一暴露数据库连通性检查、
    Alembic 版本读取与迁移命令执行入口。

    :param runtime_environment: 运行时环境服务
    :param infrastructure_gateway: 数据库基础设施网关
    :param revision_support: 数据库迁移版本支持对象
    :param alembic_command_support: 数据库 Alembic 命令支持对象
    """

    def __init__(
        self,
        *,
        runtime_environment: RuntimeEnvironmentService | None = None,
        infrastructure_gateway: DatabaseInfrastructureGateway | None = None,
        revision_support: DatabaseRevisionSupport | None = None,
        alembic_command_support: DatabaseAlembicCommandSupport | None = None,
    ) -> None:
        """
        初始化数据库运行时服务。

        :param runtime_environment: 运行时环境服务
        :param infrastructure_gateway: 数据库基础设施网关
        :param revision_support: 数据库迁移版本支持对象
        :param alembic_command_support: 数据库 Alembic 命令支持对象
        :return: None
        """
        self.runtime_environment = runtime_environment or RUNTIME_ENVIRONMENT
        self.infrastructure_gateway = infrastructure_gateway or DatabaseInfrastructureGateway()
        self.revision_support = revision_support or DatabaseRevisionSupport(
            self.infrastructure_gateway,
            self.runtime_environment,
        )
        self.alembic_command_support = alembic_command_support or DatabaseAlembicCommandSupport(
            self.runtime_environment
        )

    async def ping_database(self) -> dict[str, Any]:
        """
        检查数据库连通性。

        :return: 数据库检查结果
        """
        create_async_db_engine = self.infrastructure_gateway.get_async_db_engine_factory()
        text = self.infrastructure_gateway.get_sqlalchemy_text()
        engine = create_async_db_engine(echo=False)
        try:
            async with engine.connect() as connection:
                await connection.execute(text('SELECT 1'))
            return {'ok': True, 'message': '数据库连接成功'}
        except Exception as exc:
            return {'ok': False, 'message': '数据库连接失败', 'error': str(exc), 'exit_code': DATABASE_ERROR}
        finally:
            await engine.dispose()

    async def check_mindmap_readiness(self, env: str) -> dict[str, dict[str, Any]]:
        """只读检查脑图结构与 AI Agent 关键初始化数据。"""
        config_module = import_module('config.env')
        release_module = import_module('module_mindmap.service.mindmap_schema_release')
        verifier_module = import_module('module_mindmap.service.mindmap_schema_verifier')

        create_async_db_engine = self.infrastructure_gateway.get_async_db_engine_factory()
        engine = create_async_db_engine(echo=False)
        try:
            async with engine.connect() as connection:
                snapshot = await connection.run_sync(verifier_module.inspect_mindmap_schema)
        except Exception as exc:
            error_type = type(exc).__name__
            action = (
                '先修复数据库连接或只读元数据权限，再运行 '
                f'python -m scripts.verify_mindmap_schema --env={env}'
            )
            failure = {
                'ok': False,
                'message': '无法完成脑图发布就绪检查',
                'error': error_type,
                'action': action,
            }
            return {'schema': dict(failure), 'aiBootstrap': dict(failure)}
        finally:
            await engine.dispose()

        issues = verifier_module.find_mindmap_schema_issues(snapshot)
        schema_issues = [
            item for item in issues
            if item.kind not in verifier_module.AI_BOOTSTRAP_ISSUE_KINDS
        ]
        bootstrap_issues = [
            item for item in issues
            if item.kind in verifier_module.AI_BOOTSTRAP_ISSUE_KINDS
        ]
        migration_order = [
            item.filename for item in release_module.MINDMAP_SCHEMA_MIGRATIONS
        ]

        def _build_status(
            scoped_issues: list[Any],
            *,
            ready_message: str,
            failure_message: str,
        ) -> dict[str, Any]:
            if not scoped_issues:
                return {'ok': True, 'message': ready_message, 'missingCount': 0}
            referenced = {item.migration for item in scoped_issues}
            database_type = config_module.DataBaseConfig.db_type
            migrations = [
                release_module.resolve_migration_filename(
                    filename,
                    database_type,
                )
                for filename in migration_order
                if filename in referenced
            ]
            serialized_issues = []
            for item in scoped_issues:
                issue_payload = item.to_dict()
                issue_payload['migration'] = release_module.resolve_migration_filename(
                    item.migration,
                    database_type,
                )
                serialized_issues.append(issue_payload)
            return {
                'ok': False,
                'message': f'{failure_message}：{len(scoped_issues)} 项阻塞',
                'error': 'mindmap_release_not_ready',
                'missingCount': len(scoped_issues),
                'issues': serialized_issues,
                'migrations': migrations,
                'action': (
                    '先运行 '
                    f'python -m scripts.plan_mindmap_schema_migrations --env={env}，'
                    '人工审核并执行输出的迁移，再运行 '
                    f'python -m scripts.verify_mindmap_schema --env={env}'
                ),
            }

        return {
            'schema': _build_status(
                schema_issues,
                ready_message='脑图 Schema 已就绪',
                failure_message='脑图 Schema 未就绪',
            ),
            'aiBootstrap': _build_status(
                bootstrap_issues,
                ready_message='AI Agent Connector、菜单与角色授权已就绪',
                failure_message='AI Agent 初始化数据未就绪',
            ),
        }

    def get_current_revision(self) -> dict[str, Any]:
        """
        获取数据库当前迁移版本。

        :return: 当前迁移版本信息
        """
        create_sync_db_engine = self.infrastructure_gateway.get_sync_db_engine_factory()
        text = self.infrastructure_gateway.get_sqlalchemy_text()
        engine = create_sync_db_engine(echo=False)
        try:
            with engine.connect() as connection:
                revision = connection.execute(text('SELECT version_num FROM alembic_version')).scalar()
            return {'ok': True, 'currentRevision': revision}
        except Exception as exc:
            return {'ok': False, 'message': '读取数据库迁移版本失败', 'error': str(exc), 'exit_code': DATABASE_ERROR}
        finally:
            engine.dispose()

    def upgrade_database(self, revision: str = 'head', *, dry_run: bool = False) -> dict[str, Any]:
        """
        执行数据库迁移升级。

        :param revision: 目标迁移版本，默认为 `head`
        :param dry_run: 是否仅演练执行
        :return: 数据库迁移执行结果
        """
        return self.alembic_command_support.run_alembic_command(
            'upgrade',
            revision,
            success_message=f'数据库已升级到 {revision}',
            failure_message='数据库升级失败',
            dry_run=dry_run,
        )

    def init_database(self, *, dry_run: bool = False) -> dict[str, Any]:
        """
        初始化数据库到最新迁移版本。

        :param dry_run: 是否仅演练执行
        :return: 数据库初始化结果
        """
        return self.alembic_command_support.run_alembic_command(
            'upgrade',
            'head',
            success_message='数据库初始化完成，当前版本已同步到 head',
            failure_message='数据库初始化失败',
            dry_run=dry_run,
        )

    def downgrade_database(self, revision: str = '-1', *, dry_run: bool = False) -> dict[str, Any]:
        """
        执行数据库回退。

        :param revision: 目标回退版本，默认为 `-1`
        :param dry_run: 是否仅演练执行
        :return: 数据库回退结果
        """
        return self.alembic_command_support.run_alembic_command(
            'downgrade',
            revision,
            success_message=f'数据库已回退到 {revision}',
            failure_message='数据库回退失败',
            dry_run=dry_run,
        )

    def create_revision(self, message: str, *, autogenerate: bool = False, dry_run: bool = False) -> dict[str, Any]:
        """
        创建新的 Alembic 迁移版本文件。

        :param message: 迁移说明
        :param autogenerate: 是否自动生成变更
        :param dry_run: 是否仅演练执行
        :return: 迁移版本创建结果
        """
        arguments: list[str] = ['-m', message]
        if autogenerate:
            arguments.append('--autogenerate')
        return self.alembic_command_support.run_alembic_command(
            'revision',
            *arguments,
            success_message='数据库迁移版本文件创建完成',
            failure_message='数据库迁移版本文件创建失败',
            dry_run=dry_run,
        )

    def get_alembic_heads(self) -> dict[str, Any]:
        """
        读取当前代码仓库中的 Alembic heads 信息。

        :return: Alembic heads 结果
        """
        try:
            script_directory = self.revision_support.build_alembic_script_directory()
            items = [
                self.revision_support.serialize_revision(revision)
                for revision in script_directory.get_revisions('heads')
            ]
            return {
                'ok': True,
                'message': '已读取 Alembic heads',
                'count': len(items),
                'items': items,
            }
        except Exception as exc:
            return {'ok': False, 'message': '读取 Alembic heads 失败', 'error': str(exc), 'exit_code': DATABASE_ERROR}

    def get_alembic_history(self, *, limit: int = 20) -> dict[str, Any]:
        """
        读取当前代码仓库中的 Alembic 历史版本信息。

        :param limit: 返回的最大历史记录数量
        :return: Alembic 历史版本结果
        """
        try:
            script_directory = self.revision_support.build_alembic_script_directory()
            history_items = [
                self.revision_support.serialize_revision(revision) for revision in script_directory.walk_revisions()
            ]
            limited_items = history_items[:limit]
            return {
                'ok': True,
                'message': '已读取 Alembic 历史版本',
                'count': len(limited_items),
                'totalCount': len(history_items),
                'limit': limit,
                'items': limited_items,
            }
        except Exception as exc:
            return {'ok': False, 'message': '读取 Alembic 历史版本失败', 'error': str(exc), 'exit_code': DATABASE_ERROR}


DATABASE_RUNTIME = DatabaseRuntimeService()
