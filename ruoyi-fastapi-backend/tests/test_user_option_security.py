from unittest.mock import AsyncMock

import pytest

from module_admin.dao.user_dao import UserDao
from module_admin.service.user_service import UserService


class _MappingResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> '_MappingResult':
        return self

    def all(self) -> list[dict]:
        return self._rows


@pytest.mark.asyncio
async def test_user_option_query_selects_only_public_option_fields() -> None:
    db = AsyncMock()
    db.execute.return_value = _MappingResult([
        {
            'user_id': 7,
            'user_name': 'reviewer',
            'nick_name': 'Reviewer',
            'avatar': '/profile/avatar.png',
        }
    ])

    result = await UserDao.get_user_option_list(db)

    statement = str(db.execute.await_args.args[0]).lower()
    assert 'sys_user.user_id' in statement
    assert 'sys_user.user_name' in statement
    assert 'sys_user.nick_name' in statement
    assert 'sys_user.avatar' in statement
    for sensitive_column in ('password', 'email', 'phonenumber', 'login_ip', 'user_openid', 'user_tenant_id'):
        assert sensitive_column not in statement
    assert result == [{
        'user_id': 7,
        'user_name': 'reviewer',
        'nick_name': 'Reviewer',
        'avatar': '/profile/avatar.png',
    }]


@pytest.mark.asyncio
async def test_user_option_service_drops_unexpected_sensitive_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        UserDao,
        'get_user_option_list',
        AsyncMock(return_value=[{
            'user_id': 7,
            'user_name': 'reviewer',
            'nick_name': 'Reviewer',
            'avatar': None,
            'password': 'must-not-leak',
            'email': 'private@example.com',
        }]),
    )

    result = await UserService.get_user_option_services(AsyncMock())

    assert [item.model_dump(by_alias=True) for item in result] == [{
        'userId': 7,
        'userName': 'reviewer',
        'nickName': 'Reviewer',
        'avatar': None,
    }]
