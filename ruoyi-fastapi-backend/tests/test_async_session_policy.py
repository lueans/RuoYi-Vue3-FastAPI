"""异步数据库会话策略测试。"""
import unittest
from unittest.mock import patch

from config.database import AsyncSessionLocal, async_engine, create_sync_db_engine


class AsyncSessionPolicyTest(unittest.TestCase):
    def test_committed_objects_remain_readable_without_implicit_io(self) -> None:
        self.assertFalse(AsyncSessionLocal.kw['expire_on_commit'])

    def test_async_database_errors_hide_bound_parameters(self) -> None:
        self.assertTrue(async_engine.sync_engine.hide_parameters)

    def test_sync_database_errors_hide_bound_parameters(self) -> None:
        sentinel_engine = object()
        with patch('config.database.create_engine', return_value=sentinel_engine) as create_engine_mock:
            result = create_sync_db_engine(echo=False)

        self.assertIs(result, sentinel_engine)
        self.assertTrue(create_engine_mock.call_args.kwargs['hide_parameters'])


if __name__ == '__main__':
    unittest.main()
