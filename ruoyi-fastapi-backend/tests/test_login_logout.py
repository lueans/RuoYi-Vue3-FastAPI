import unittest
from unittest.mock import Mock, patch

from module_admin.controller.login_controller import _get_logout_token_id
from module_admin.service.login_service import optional_oauth2_scheme


class LogoutTokenTestCase(unittest.TestCase):
    def test_logout_bearer_dependency_allows_missing_authorization(self) -> None:
        self.assertFalse(optional_oauth2_scheme.auto_error)

    def test_malformed_token_is_treated_as_an_already_logged_out_session(self) -> None:
        self.assertIsNone(_get_logout_token_id('undefined'))

    @patch('module_admin.controller.login_controller.AppConfig.app_same_time_login', True)
    @patch('module_admin.controller.login_controller.jwt.decode')
    def test_same_time_login_uses_session_id(self, decode_mock: Mock) -> None:
        decode_mock.return_value = {'session_id': 'session-1', 'user_id': '2'}

        self.assertEqual(_get_logout_token_id('valid-token'), 'session-1')

    @patch('module_admin.controller.login_controller.AppConfig.app_same_time_login', False)
    @patch('module_admin.controller.login_controller.jwt.decode')
    def test_single_session_login_uses_user_id(self, decode_mock: Mock) -> None:
        decode_mock.return_value = {'session_id': 'session-1', 'user_id': 2}

        self.assertEqual(_get_logout_token_id('valid-token'), '2')

    @patch('module_admin.controller.login_controller.jwt.decode')
    def test_missing_token_identifier_is_already_logged_out(self, decode_mock: Mock) -> None:
        decode_mock.return_value = {}

        self.assertIsNone(_get_logout_token_id('valid-token'))


if __name__ == '__main__':
    unittest.main()
