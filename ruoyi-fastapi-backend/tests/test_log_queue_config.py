import unittest
from unittest.mock import Mock, patch

from config.env import LogConfig
from utils.log_util import LoggerInitializer


class LogQueueConfigTest(unittest.TestCase):
    def test_configured_enqueue_mode_is_applied_to_every_log_sink(self) -> None:
        for enqueue in (False, True):
            with self.subTest(enqueue=enqueue):
                configured_logger = Mock()
                with (
                    patch.object(LogConfig, 'loguru_enqueue', enqueue),
                    patch.object(LogConfig, 'loguru_stdout', True),
                    patch.object(LogConfig, 'loguru_json', False),
                    patch.object(LogConfig, 'log_file_enabled', True),
                    patch('utils.log_util._logger.patch', return_value=configured_logger),
                    patch.object(LoggerInitializer, '_ensure_log_directory_exists'),
                ):
                    LoggerInitializer().init_log()

                self.assertEqual(configured_logger.add.call_count, 3)
                self.assertTrue(all(
                    call.kwargs.get('enqueue') is enqueue
                    for call in configured_logger.add.call_args_list
                ))


if __name__ == '__main__':
    unittest.main()
