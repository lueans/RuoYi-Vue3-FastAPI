from pathlib import Path

import pytest
from pytest import MonkeyPatch

from cli.runtime.base import RuntimeEnvironmentService
from cli.runtime.db import DatabaseRuntimeService
from cli.runtime.db.gateway import DatabaseInfrastructureGateway
from cli.runtime.db.support import DatabaseRevisionSupport
from module_mindmap.service import mindmap_schema_verifier
from module_mindmap.service.mindmap_schema_verifier import MindmapSchemaIssue


class FakeRuntimeEnvironment(RuntimeEnvironmentService):
    """
    模拟运行时环境服务。
    """

    @staticmethod
    def get_backend_dir() -> str:
        """
        返回固定后端目录。

        :return: 固定目录
        """
        return '/tmp/ruoyi-backend'


def test_database_revision_support_serializes_revision() -> None:
    """
    校验数据库迁移版本支持对象会序列化 Alembic revision。

    :return: None
    """

    class FakeRevision:
        """
        模拟 Alembic revision 对象。
        """

        revision = '202605110001'
        down_revision = ('202605100001',)
        branch_labels = {'main'}
        dependencies = None
        doc = ' demo revision '
        path = Path('/tmp/revision.py')

    support = DatabaseRevisionSupport(DatabaseInfrastructureGateway(), FakeRuntimeEnvironment())

    payload = support.serialize_revision(FakeRevision())

    assert payload == {
        'revision': '202605110001',
        'downRevisions': ['202605100001'],
        'branchLabels': ['main'],
        'dependsOn': [],
        'doc': 'demo revision',
        'path': '/tmp/revision.py',
    }


def test_database_runtime_service_upgrade_dry_run_returns_command_payload() -> None:
    """
    校验数据库运行时 dry-run 升级会返回命令预览结果。

    :return: None
    """
    service = DatabaseRuntimeService(runtime_environment=FakeRuntimeEnvironment())

    payload = service.upgrade_database('head', dry_run=True)

    assert payload['ok'] is True
    assert payload['dryRun'] is True
    assert payload['cwd'] == '/tmp/ruoyi-backend'
    assert payload['command'] == ['alembic', '-c', '/tmp/ruoyi-backend/alembic.ini', 'upgrade', 'head']


@pytest.mark.asyncio
async def test_database_runtime_service_ping_database_returns_failure() -> None:
    """
    校验数据库运行时在连接异常时会返回失败结果。

    :return: None
    """

    class FakeConnection:
        """
        模拟数据库连接对象。
        """

        async def __aenter__(self) -> 'FakeConnection':
            raise RuntimeError('db boom')

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: object,
        ) -> None:
            del exc_type, exc, tb

    class FakeEngine:
        """
        模拟数据库引擎。
        """

        @staticmethod
        def connect() -> FakeConnection:
            """
            返回模拟连接对象。

            :return: 模拟连接对象
            """
            return FakeConnection()

        @staticmethod
        async def dispose() -> None:
            """
            释放引擎资源。

            :return: None
            """

    gateway = DatabaseInfrastructureGateway()
    service = DatabaseRuntimeService(
        runtime_environment=FakeRuntimeEnvironment(),
        infrastructure_gateway=gateway,
    )

    def _fake_get_async_db_engine_factory() -> object:
        def _factory(*, echo: bool = False) -> FakeEngine:
            del echo
            return FakeEngine()

        return _factory

    def _fake_get_sqlalchemy_text() -> object:
        return lambda sql: sql

    object.__setattr__(gateway, 'get_async_db_engine_factory', _fake_get_async_db_engine_factory)
    object.__setattr__(gateway, 'get_sqlalchemy_text', _fake_get_sqlalchemy_text)

    payload = await service.ping_database()

    assert payload['ok'] is False
    assert payload['message'] == '数据库连接失败'
    assert 'db boom' in payload['error']


@pytest.mark.asyncio
async def test_mindmap_readiness_failure_is_actionable_without_leaking_db_error() -> None:
    """脑图门禁异常应给出恢复命令，但不回显可能包含凭据的底层异常。"""

    class FakeConnection:
        async def __aenter__(self) -> 'FakeConnection':
            raise RuntimeError('password=must-not-leak')

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: object,
        ) -> None:
            del exc_type, exc, tb

    class FakeEngine:
        @staticmethod
        def connect() -> FakeConnection:
            return FakeConnection()

        @staticmethod
        async def dispose() -> None:
            return None

    gateway = DatabaseInfrastructureGateway()
    service = DatabaseRuntimeService(
        runtime_environment=FakeRuntimeEnvironment(),
        infrastructure_gateway=gateway,
    )

    def _fake_get_async_db_engine_factory() -> object:
        def _factory(*, echo: bool = False) -> FakeEngine:
            del echo
            return FakeEngine()

        return _factory

    object.__setattr__(gateway, 'get_async_db_engine_factory', _fake_get_async_db_engine_factory)

    payload = await service.check_mindmap_readiness('dev')

    for check in payload.values():
        assert check['ok'] is False
        assert check['error'] == 'RuntimeError'
        assert 'scripts.verify_mindmap_schema --env=dev' in check['action']
        assert 'must-not-leak' not in str(check)


@pytest.mark.asyncio
async def test_mindmap_readiness_separates_schema_and_ai_bootstrap(
    monkeypatch: MonkeyPatch,
) -> None:
    """Doctor 可分别展示结构迁移与 AI 初始化数据阻塞项。"""

    class FakeConnection:
        async def __aenter__(self) -> 'FakeConnection':
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: object,
        ) -> None:
            del exc_type, exc, tb

        @staticmethod
        async def run_sync(callback: object) -> dict[str, object]:
            del callback
            return {}

    class FakeEngine:
        @staticmethod
        def connect() -> FakeConnection:
            return FakeConnection()

        @staticmethod
        async def dispose() -> None:
            return None

    gateway = DatabaseInfrastructureGateway()
    service = DatabaseRuntimeService(
        runtime_environment=FakeRuntimeEnvironment(),
        infrastructure_gateway=gateway,
    )

    def _fake_get_async_db_engine_factory() -> object:
        def _factory(*, echo: bool = False) -> FakeEngine:
            del echo
            return FakeEngine()

        return _factory

    issues = [
        MindmapSchemaIssue(
            'table',
            'mindmap_ai_job',
            '20260910_mindmap_ai_agent.sql',
        ),
        MindmapSchemaIssue(
            'seed',
            'mindmap_ai_connector.codex',
            '20260910_mindmap_ai_agent.sql',
        ),
    ]
    object.__setattr__(gateway, 'get_async_db_engine_factory', _fake_get_async_db_engine_factory)
    monkeypatch.setattr(
        mindmap_schema_verifier,
        'find_mindmap_schema_issues',
        lambda snapshot: issues,
    )

    payload = await service.check_mindmap_readiness('dev')

    assert payload['schema']['missingCount'] == 1
    assert payload['schema']['migrations'] == ['20260910_mindmap_ai_agent.sql']
    assert payload['aiBootstrap']['missingCount'] == 1
    assert payload['aiBootstrap']['migrations'] == [
        '20260910_mindmap_ai_agent.sql'
    ]
