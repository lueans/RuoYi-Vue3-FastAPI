"""脑图所有者/协作者列表与有效权限测试。"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from common.vo import PageModel
from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_dao import MindmapDao
from module_mindmap.entity.vo.mindmap_vo import MindmapPageQueryModel
from module_mindmap.service.mindmap_service import MindmapService


class MindmapAccessServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_owner_resolves_full_permission_without_collaborator_query(self) -> None:
        mindmap = SimpleNamespace(id=8, owner_id=42)
        with (
            patch.object(MindmapDao, 'get_mindmap_by_id', new=AsyncMock(return_value=mindmap)),
            patch(
                'module_mindmap.service.mindmap_service.MindmapCollaboratorDao.get_collaborator_permission',
                new=AsyncMock(),
            ) as permission_mock,
        ):
            result = await MindmapService.resolve_mindmap_access(object(), 8, 42)

        self.assertEqual(result, (mindmap, 1, True))
        permission_mock.assert_not_awaited()

    async def test_viewer_cannot_resolve_edit_access(self) -> None:
        mindmap = SimpleNamespace(id=8, owner_id=42, status=0)
        with (
            patch.object(MindmapDao, 'get_mindmap_for_update', new=AsyncMock(return_value=mindmap)),
            patch(
                'module_mindmap.service.mindmap_service.MindmapCollaboratorDao.get_collaborator_permission',
                new=AsyncMock(return_value=0),
            ),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapService.resolve_mindmap_access(object(), 8, 9, require_edit=True)

        self.assertEqual(context.exception.message, '无编辑权限')

    async def test_failed_migration_keeps_owner_in_readonly_mode(self) -> None:
        mindmap = SimpleNamespace(id=8, owner_id=42, status=0)
        with (
            patch.object(MindmapDao, 'get_mindmap_for_update', new=AsyncMock(return_value=mindmap)),
            patch.object(MindmapDao, 'get_migration_status', new=AsyncMock(return_value='failed')),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapService.resolve_mindmap_access(object(), 8, 42, require_edit=True)

        self.assertIn('仅可只读访问', context.exception.message)

    async def test_shared_list_is_scoped_by_authenticated_user(self) -> None:
        query_model = MindmapPageQueryModel(ownerId=9, accessScope='shared')
        with patch(
            'module_mindmap.dao.mindmap_dao.PageUtil.paginate',
            new=AsyncMock(return_value=SimpleNamespace(rows=[], total=0)),
        ) as paginate_mock:
            await MindmapDao.get_mindmap_list(object(), query_model, is_page=True)

        statement = paginate_mock.await_args.args[1]
        sql = str(statement)
        self.assertIn('mindmap_collaborator', sql)
        self.assertIn('mindmap_collaborator.user_id', sql)
        self.assertIn('mindmap.del_flag', sql)

    async def test_trash_list_is_owner_scoped_and_excludes_active_files(self) -> None:
        query_model = MindmapPageQueryModel(ownerId=9, accessScope='trash')
        with patch(
            'module_mindmap.dao.mindmap_dao.PageUtil.paginate',
            new=AsyncMock(return_value=SimpleNamespace(rows=[], total=0)),
        ) as paginate_mock:
            await MindmapDao.get_mindmap_list(object(), query_model, is_page=True)

        statement = paginate_mock.await_args.args[1]
        sql = str(statement.compile(compile_kwargs={'literal_binds': True}))
        self.assertIn("mindmap.owner_id = 9", sql)
        self.assertIn("mindmap.del_flag = '2'", sql)
        self.assertIn("'trash' AS access_type", sql)
        self.assertNotIn('JOIN mindmap_collaborator', sql)

    async def test_list_service_normalizes_database_permission_types(self) -> None:
        page = PageModel(
            rows=[{
                'id': 8,
                'name': '共享脑图',
                'ownerId': 42,
                'ownerName': '所有者',
                'accessType': 'shared',
                'effectivePermission': 0,
                'isOwner': 0,
                'canEdit': 0,
                'contentState': 'ready',
            }],
            pageNum=1,
            pageSize=10,
            total=1,
            hasNext=False,
        )
        with patch.object(MindmapDao, 'get_mindmap_list', new=AsyncMock(return_value=page)):
            result = await MindmapService.get_mindmap_list_services(
                object(), MindmapPageQueryModel(accessScope='shared'),
            )

        self.assertIs(result.rows[0]['canEdit'], False)
        self.assertIs(result.rows[0]['isOwner'], False)
        self.assertEqual(result.rows[0]['effectivePermission'], 0)
        self.assertEqual(result.rows[0]['contentState'], 'ready')

    def test_access_scope_rejects_unknown_values(self) -> None:
        self.assertEqual(MindmapPageQueryModel(accessScope='trash').access_scope, 'trash')
        with self.assertRaises(ValueError):
            MindmapPageQueryModel(accessScope='all')

    def test_file_keyword_is_normalized_and_bounded(self) -> None:
        self.assertEqual(
            MindmapPageQueryModel(keyword='  季度目标  ').keyword,
            '季度目标',
        )
        with self.assertRaises(ValueError):
            MindmapPageQueryModel(keyword='目标\n范围')
        with self.assertRaises(ValueError):
            MindmapPageQueryModel(keyword='脑' * 101)

    async def test_file_keyword_matches_name_and_description_with_literal_wildcards(self) -> None:
        query_model = MindmapPageQueryModel(ownerId=9, keyword='计划%_\\')
        with patch(
            'module_mindmap.dao.mindmap_dao.PageUtil.paginate',
            new=AsyncMock(return_value=SimpleNamespace(rows=[], total=0)),
        ) as paginate_mock:
            await MindmapDao.get_mindmap_list(object(), query_model, is_page=True)

        statement = paginate_mock.await_args.args[1]
        sql = str(statement.compile(compile_kwargs={'literal_binds': True}))
        self.assertIn('lower(mindmap.name) LIKE lower(', sql)
        self.assertIn('lower(mindmap.description) LIKE lower(', sql)
        self.assertIn("%计划\\%\\_\\\\%", sql)
        self.assertEqual(sql.count("ESCAPE '\\'"), 2)

    def test_list_sort_contract_rejects_unknown_field_and_direction(self) -> None:
        self.assertEqual(
            MindmapPageQueryModel(sortField='name', sortOrder='asc').sort_field,
            'name',
        )
        with self.assertRaises(ValueError):
            MindmapPageQueryModel(sortField='owner_id')
        with self.assertRaises(ValueError):
            MindmapPageQueryModel(sortOrder='sideways')

    async def test_list_sort_uses_stable_file_id_tiebreaker(self) -> None:
        query_model = MindmapPageQueryModel(ownerId=9, sortField='name', sortOrder='asc')
        with patch(
            'module_mindmap.dao.mindmap_dao.PageUtil.paginate',
            new=AsyncMock(return_value=SimpleNamespace(rows=[], total=0)),
        ) as paginate_mock:
            await MindmapDao.get_mindmap_list(object(), query_model, is_page=True)

        statement = paginate_mock.await_args.args[1]
        sql = str(statement.compile(compile_kwargs={'literal_binds': True}))
        self.assertIn('ORDER BY mindmap.name ASC, mindmap.id ASC', sql)


if __name__ == '__main__':
    unittest.main()
