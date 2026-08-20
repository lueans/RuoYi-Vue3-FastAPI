"""脑图协作者在线权限生命周期测试。"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from module_mindmap.dao.mindmap_collaborator_dao import MindmapCollaboratorDao
from module_mindmap.entity.vo.mindmap_collaborator_vo import (
    MindmapCollaboratorAddModel,
    MindmapCollaboratorUpdateModel,
)
from module_mindmap.service.mindmap_collaborator_service import MindmapCollaboratorService


class MindmapCollaboratorServiceTest(unittest.IsolatedAsyncioTestCase):
    def test_permission_models_only_accept_view_or_edit(self) -> None:
        for permission in (-1, 2, 999):
            with self.subTest(permission=permission), self.assertRaises(ValidationError):
                MindmapCollaboratorAddModel(mindmapId=5, userId=7, permission=permission)
            with self.subTest(permission=permission), self.assertRaises(ValidationError):
                MindmapCollaboratorUpdateModel(id=3, permission=permission)

    async def test_inactive_target_user_cannot_be_added(self) -> None:
        mindmap = SimpleNamespace(id=5, owner_id=42, status=0)
        db = SimpleNamespace(rollback=AsyncMock())
        with (
            patch(
                'module_mindmap.service.mindmap_collaborator_service.MindmapDao.get_mindmap_for_update',
                new=AsyncMock(return_value=mindmap),
            ),
            patch(
                'module_mindmap.service.mindmap_collaborator_service.MindmapCollaboratorDao.is_active_user',
                new=AsyncMock(return_value=False),
            ),
            patch(
                'module_mindmap.service.mindmap_collaborator_service.MindmapCollaboratorDao.add_collaborator',
                new=AsyncMock(),
            ) as add_mock,
            self.assertRaises(Exception) as context,
        ):
            await MindmapCollaboratorService.add_collaborator(
                db,
                MindmapCollaboratorAddModel(mindmapId=5, userId=7, permission=1),
                operator_id=42,
            )

        self.assertEqual(context.exception.message, '目标用户不存在或已停用')
        add_mock.assert_not_awaited()

    async def test_duplicate_insert_race_returns_stable_business_error(self) -> None:
        mindmap = SimpleNamespace(id=5, owner_id=42, status=0)
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        duplicate_error = IntegrityError('insert', {}, Exception('duplicate'))
        with (
            patch(
                'module_mindmap.service.mindmap_collaborator_service.MindmapDao.get_mindmap_for_update',
                new=AsyncMock(return_value=mindmap),
            ),
            patch(
                'module_mindmap.service.mindmap_collaborator_service.MindmapCollaboratorDao.is_active_user',
                new=AsyncMock(return_value=True),
            ),
            patch(
                'module_mindmap.service.mindmap_collaborator_service.MindmapCollaboratorDao.check_exists',
                new=AsyncMock(return_value=False),
            ),
            patch(
                'module_mindmap.service.mindmap_collaborator_service.MindmapCollaboratorDao.add_collaborator',
                new=AsyncMock(side_effect=duplicate_error),
            ),
            self.assertRaises(Exception) as context,
        ):
            await MindmapCollaboratorService.add_collaborator(
                db,
                MindmapCollaboratorAddModel(mindmapId=5, userId=7, permission=1),
                operator_id=42,
            )

        self.assertEqual(context.exception.message, '该用户已是协作者')
        db.rollback.assert_awaited_once()

    async def test_search_query_excludes_owner_existing_users_and_escapes_wildcards(self) -> None:
        class RecordingDb:
            statement: object | None = None

            async def execute(self, statement: object) -> SimpleNamespace:
                self.statement = statement
                return SimpleNamespace(all=list)

        db = RecordingDb()
        result = await MindmapCollaboratorDao.search_available_users(
            db, mindmap_id=5, owner_id=42, keyword='100%_match',
        )

        sql = str(db.statement).lower()
        self.assertEqual(result, [])
        self.assertIn('not in', sql)
        self.assertIn('mindmap_collaborator', sql)
        self.assertIn('escape', sql)
        self.assertIn('sys_user.user_id !=', sql)

    async def test_downgrade_notifies_target_after_commit(self) -> None:
        collab = SimpleNamespace(id=3, mindmap_id=5, user_id=7, permission=1)
        mindmap = SimpleNamespace(id=5, owner_id=42, status=0)
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        with (
            patch(
                'module_mindmap.service.mindmap_collaborator_service.MindmapCollaboratorDao.get_collaborator_by_id',
                new=AsyncMock(return_value=collab),
            ),
            patch(
                'module_mindmap.service.mindmap_collaborator_service.MindmapDao.get_mindmap_for_update',
                new=AsyncMock(return_value=mindmap),
            ),
            patch(
                'module_mindmap.service.mindmap_collaborator_service.MindmapCollaboratorDao.update_permission',
                new=AsyncMock(),
            ),
            patch.object(
                MindmapCollaboratorService, '_notify_access_revoked', new=AsyncMock(),
            ) as notify_mock,
        ):
            result = await MindmapCollaboratorService.update_permission(
                db, MindmapCollaboratorUpdateModel(id=3, permission=0), operator_id=42,
            )

        self.assertTrue(result.is_success)
        db.commit.assert_awaited_once()
        notify_mock.assert_awaited_once_with(5, 7, unittest.mock.ANY)

    async def test_unchanged_permission_skips_write_and_disconnect(self) -> None:
        collab = SimpleNamespace(id=3, mindmap_id=5, user_id=7, permission=0)
        mindmap = SimpleNamespace(id=5, owner_id=42, status=0)
        db = SimpleNamespace(rollback=AsyncMock())
        with (
            patch(
                'module_mindmap.service.mindmap_collaborator_service.MindmapCollaboratorDao.get_collaborator_by_id',
                new=AsyncMock(return_value=collab),
            ),
            patch(
                'module_mindmap.service.mindmap_collaborator_service.MindmapDao.get_mindmap_for_update',
                new=AsyncMock(return_value=mindmap),
            ),
            patch(
                'module_mindmap.service.mindmap_collaborator_service.MindmapCollaboratorDao.update_permission',
                new=AsyncMock(),
            ) as update_mock,
            patch.object(
                MindmapCollaboratorService, '_notify_access_revoked', new=AsyncMock(),
            ) as notify_mock,
        ):
            result = await MindmapCollaboratorService.update_permission(
                db, MindmapCollaboratorUpdateModel(id=3, permission=0), operator_id=42,
            )

        self.assertTrue(result.is_success)
        update_mock.assert_not_awaited()
        notify_mock.assert_not_awaited()

    async def test_search_is_scoped_to_owner_and_current_mindmap(self) -> None:
        mindmap = SimpleNamespace(id=5, owner_id=42)
        users = [{
            'user_id': 7,
            'user_name': 'niangao',
            'nick_name': '年糕',
            'avatar': None,
        }]
        with (
            patch(
                'module_mindmap.service.mindmap_collaborator_service.MindmapDao.get_mindmap_by_id',
                new=AsyncMock(return_value=mindmap),
            ),
            patch(
                'module_mindmap.service.mindmap_collaborator_service.MindmapCollaboratorDao.search_available_users',
                new=AsyncMock(return_value=users),
            ) as search_mock,
        ):
            result = await MindmapCollaboratorService.search_available_users(
                SimpleNamespace(), mindmap_id=5, keyword='  年糕  ', operator_id=42,
            )

        search_mock.assert_awaited_once_with(unittest.mock.ANY, 5, 42, '年糕')
        self.assertEqual(result[0]['userName'], 'niangao')

    async def test_non_owner_cannot_search_workspace_users(self) -> None:
        mindmap = SimpleNamespace(id=5, owner_id=42)
        with (
            patch(
                'module_mindmap.service.mindmap_collaborator_service.MindmapDao.get_mindmap_by_id',
                new=AsyncMock(return_value=mindmap),
            ),
            patch(
                'module_mindmap.service.mindmap_collaborator_service.MindmapCollaboratorDao.search_available_users',
                new=AsyncMock(),
            ) as search_mock,
            self.assertRaises(Exception) as context,
        ):
            await MindmapCollaboratorService.search_available_users(
                SimpleNamespace(), mindmap_id=5, keyword='年糕', operator_id=7,
            )

        self.assertEqual(context.exception.message, '只有脑图所有者可以搜索协作者')
        search_mock.assert_not_awaited()

    async def test_collaborator_list_contains_user_identity(self) -> None:
        mindmap = SimpleNamespace(id=5, owner_id=42)
        collaborator = {
            'id': 3,
            'mindmap_id': 5,
            'user_id': 7,
            'permission': 1,
            'user_name': 'niangao',
            'nick_name': '年糕',
            'avatar': '/profile/avatar.png',
        }
        with (
            patch(
                'module_mindmap.service.mindmap_collaborator_service.MindmapDao.get_mindmap_by_id',
                new=AsyncMock(return_value=mindmap),
            ),
            patch(
                'module_mindmap.service.mindmap_collaborator_service.MindmapCollaboratorDao.get_collaborators_by_mindmap',
                new=AsyncMock(return_value=[collaborator]),
            ),
        ):
            result = await MindmapCollaboratorService.get_collaborator_list(
                SimpleNamespace(), mindmap_id=5, user_id=42,
            )

        self.assertEqual(result[0].user_name, 'niangao')
        self.assertEqual(result[0].nick_name, '年糕')
        self.assertEqual(result[0].avatar, '/profile/avatar.png')

    async def test_removal_notifies_target_after_commit(self) -> None:
        collab = SimpleNamespace(id=3, mindmap_id=5, user_id=7)
        mindmap = SimpleNamespace(id=5, owner_id=42)
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        with (
            patch(
                'module_mindmap.service.mindmap_collaborator_service.MindmapCollaboratorDao.get_collaborator_by_id',
                new=AsyncMock(return_value=collab),
            ),
            patch(
                'module_mindmap.service.mindmap_collaborator_service.MindmapDao.get_mindmap_by_id',
                new=AsyncMock(return_value=mindmap),
            ),
            patch(
                'module_mindmap.service.mindmap_collaborator_service.MindmapCollaboratorDao.remove_collaborator',
                new=AsyncMock(),
            ),
            patch.object(
                MindmapCollaboratorService, '_notify_access_revoked', new=AsyncMock(),
            ) as notify_mock,
        ):
            result = await MindmapCollaboratorService.remove_collaborator(
                db, collab_id=3, operator_id=42,
            )

        self.assertTrue(result.is_success)
        db.commit.assert_awaited_once()
        notify_mock.assert_awaited_once_with(5, 7, unittest.mock.ANY)


if __name__ == '__main__':
    unittest.main()
