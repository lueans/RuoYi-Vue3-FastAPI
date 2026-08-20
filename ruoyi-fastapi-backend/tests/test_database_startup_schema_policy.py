"""Database startup must never bypass reviewed production migrations."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from config.env import DataBaseSettings
from config.get_db import init_create_table


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
        ):
            await init_create_table()

        connection.execute.assert_awaited_once()
        connection.run_sync.assert_not_awaited()

    async def test_explicit_development_flag_allows_create_all(self) -> None:
        connection = SimpleNamespace(run_sync=AsyncMock(), execute=AsyncMock())
        engine = SimpleNamespace(begin=lambda: AsyncBeginContext(connection))
        with (
            patch('config.get_db.async_engine', engine),
            patch('config.get_db.DataBaseConfig.db_auto_create_tables', True),
        ):
            await init_create_table()

        connection.run_sync.assert_awaited_once()
        connection.execute.assert_not_awaited()

    def test_production_profiles_explicitly_disable_auto_ddl(self) -> None:
        self.assertFalse(DataBaseSettings.model_fields['db_auto_create_tables'].default)
        backend_root = Path(__file__).resolve().parents[1]
        for filename in ('.env.prod', '.env.dockermy', '.env.dockerpg'):
            with self.subTest(profile=filename):
                source = (backend_root / filename).read_text(encoding='utf-8')
                self.assertIn('DB_AUTO_CREATE_TABLES = false', source)


if __name__ == '__main__':
    unittest.main()
