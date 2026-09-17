"""Database startup must never bypass reviewed production migrations."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from config.database import Base
from config.env import DataBaseSettings
from config.get_db import (
    MINDMAP_AI_SCHEMA_MIGRATIONS,
    _mindmap_ai_required_schema,
    init_create_table,
    validate_mindmap_ai_runtime_schema,
)


class AsyncBeginContext:
    def __init__(self, connection: SimpleNamespace) -> None:
        self.connection = connection

    async def __aenter__(self) -> SimpleNamespace:
        return self.connection

    async def __aexit__(self, *_args: object) -> None:
        return None


class DatabaseStartupSchemaPolicyTest(unittest.IsolatedAsyncioTestCase):
    async def test_default_startup_only_checks_connectivity(self) -> None:
        connection = SimpleNamespace(run_sync=AsyncMock(), execute=AsyncMock())
        engine = SimpleNamespace(begin=lambda: AsyncBeginContext(connection))
        with (
            patch('config.get_db.async_engine', engine),
            patch('config.get_db.DataBaseConfig.db_auto_create_tables', False),
            patch('config.get_db.AppConfig.app_env', 'dev'),
        ):
            await init_create_table()

        connection.execute.assert_awaited_once()
        connection.run_sync.assert_not_awaited()

    async def test_production_startup_runs_ai_only_schema_gate(self) -> None:
        for app_env in ('prod', 'dockermy', 'dockerpg'):
            with self.subTest(app_env=app_env):
                connection = SimpleNamespace(
                    run_sync=AsyncMock(),
                    execute=AsyncMock(),
                )
                engine = SimpleNamespace(
                    begin=lambda connection=connection: AsyncBeginContext(connection),
                )
                with (
                    patch('config.get_db.async_engine', engine),
                    patch(
                        'config.get_db.DataBaseConfig.db_auto_create_tables',
                        False,
                    ),
                    patch('config.get_db.AppConfig.app_env', app_env),
                ):
                    await init_create_table()

                connection.execute.assert_awaited_once()
                connection.run_sync.assert_awaited_once_with(
                    validate_mindmap_ai_runtime_schema,
                )

    async def test_explicit_development_flag_allows_create_all(self) -> None:
        connection = SimpleNamespace(run_sync=AsyncMock(), execute=AsyncMock())
        engine = SimpleNamespace(begin=lambda: AsyncBeginContext(connection))
        with (
            patch('config.get_db.async_engine', engine),
            patch('config.get_db.DataBaseConfig.db_auto_create_tables', True),
            patch('config.get_db.AppConfig.app_env', 'dev'),
        ):
            await init_create_table()

        self.assertEqual(
            connection.run_sync.await_args_list,
            [
                call(Base.metadata.create_all),
                call(validate_mindmap_ai_runtime_schema),
            ],
        )
        connection.execute.assert_not_awaited()

    async def test_development_auto_create_still_rejects_a_stale_ai_schema(
        self,
    ) -> None:
        connection = SimpleNamespace(
            run_sync=AsyncMock(
                side_effect=[None, RuntimeError('missing AI schema column')],
            ),
            execute=AsyncMock(),
        )
        engine = SimpleNamespace(begin=lambda: AsyncBeginContext(connection))
        with (
            patch('config.get_db.async_engine', engine),
            patch('config.get_db.DataBaseConfig.db_auto_create_tables', True),
            patch('config.get_db.AppConfig.app_env', 'dev'),
            self.assertRaisesRegex(RuntimeError, 'missing AI schema column'),
        ):
            await init_create_table()

        self.assertEqual(connection.run_sync.await_count, 2)
        connection.execute.assert_not_awaited()

    async def test_production_profiles_reject_auto_create_tables(self) -> None:
        for app_env in ('prod', 'dockermy', 'dockerpg'):
            with self.subTest(app_env=app_env):
                begin = MagicMock()
                engine = SimpleNamespace(begin=begin)
                with (
                    patch('config.get_db.async_engine', engine),
                    patch(
                        'config.get_db.DataBaseConfig.db_auto_create_tables',
                        True,
                    ),
                    patch('config.get_db.AppConfig.app_env', app_env),
                    self.assertRaisesRegex(RuntimeError, 'DB_AUTO_CREATE_TABLES'),
                ):
                    await init_create_table()

                begin.assert_not_called()

    def test_production_profiles_explicitly_disable_auto_ddl(self) -> None:
        self.assertFalse(DataBaseSettings.model_fields['db_auto_create_tables'].default)
        backend_root = Path(__file__).resolve().parents[1]
        for filename in ('.env.prod', '.env.dockermy', '.env.dockerpg'):
            with self.subTest(profile=filename):
                source = (backend_root / filename).read_text(encoding='utf-8')
                self.assertIn('DB_AUTO_CREATE_TABLES = false', source)

    def test_ai_schema_gate_ignores_unrelated_legacy_mindmap_schema(self) -> None:
        required_schema = _mindmap_ai_required_schema()
        fake_inspector = SimpleNamespace(
            get_table_names=lambda: list(required_schema),
            get_columns=lambda table: [
                {'name': column} for column in required_schema[table]
            ],
        )

        with patch('config.get_db.inspect', return_value=fake_inspector):
            validate_mindmap_ai_runtime_schema(SimpleNamespace())

    def test_ai_schema_gate_fails_closed_for_missing_current_ai_column(self) -> None:
        required_schema = _mindmap_ai_required_schema()
        columns = {
            table: set(required_columns)
            for table, required_columns in required_schema.items()
        }
        columns['mindmap_ai_job'].remove('execution_epoch')
        fake_inspector = SimpleNamespace(
            get_table_names=lambda: list(required_schema),
            get_columns=lambda table: [
                {'name': column} for column in columns[table]
            ],
        )

        with (
            patch('config.get_db.inspect', return_value=fake_inspector),
            pytest.raises(RuntimeError, match=r'mindmap_ai_job\.execution_epoch') as error,
        ):
            validate_mindmap_ai_runtime_schema(SimpleNamespace())

        assert MINDMAP_AI_SCHEMA_MIGRATIONS[-1] in str(error.value)


if __name__ == '__main__':
    unittest.main()
