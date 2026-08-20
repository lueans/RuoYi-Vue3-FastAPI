"""脑图跨文件节点搜索的权限、路径与分页契约测试。"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from exceptions.exception import ServiceException
from module_mindmap.entity.vo.mindmap_vo import MindmapGlobalNodeSearchItemModel
from module_mindmap.service.mindmap_service import MindmapService


class MindmapGlobalSearchModelTest(unittest.TestCase):
    def test_result_contract_preserves_file_access_and_path_context(self) -> None:
        result = MindmapGlobalNodeSearchItemModel(id=91, nodeUid='node-plan', text='季度计划', mindmapId=11, mindmapName='产品规划', ownerName='Alice', accessType='shared', effectivePermission=0, status=0, canEdit=False, path=[
                {'nodeUid': 'root', 'text': '产品'},
                {'nodeUid': 'node-plan', 'text': '季度计划'},
            ], pathText='产品 / 季度计划')

        self.assertEqual(result.mindmap_id, 11)
        self.assertEqual(result.path[-1].node_uid, 'node-plan')
        self.assertFalse(result.can_edit)


class MindmapGlobalSearchServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_blank_keyword_is_rejected_before_database_access(self) -> None:
        db = SimpleNamespace(execute=AsyncMock())

        with self.assertRaises(ServiceException) as context:
            await MindmapService.search_global_nodes_services(db, 7, '   ')

        self.assertIn('搜索关键词', context.exception.message)
        db.execute.assert_not_awaited()

    async def test_search_returns_owned_and_shared_results_with_one_path_query(self) -> None:
        rows = [
            SimpleNamespace(
                id=91,
                node_uid='owned-node',
                text_plain='季度目标',
                file_id=11,
                mindmap_name='我的规划',
                status=0,
                owner_name='Owner',
                access_type='owned',
                effective_permission=1,
            ),
            SimpleNamespace(
                id=92,
                node_uid='shared-node',
                text_plain='季度复盘',
                file_id=12,
                mindmap_name='共享复盘',
                status=1,
                owner_name='Alice',
                access_type='shared',
                effective_permission=1,
            ),
        ]
        path_rows = [
            SimpleNamespace(origin_id=91, node_uid='root-a', text='目标', depth=1),
            SimpleNamespace(origin_id=91, node_uid='owned-node', text='季度目标', depth=0),
            SimpleNamespace(origin_id=92, node_uid='root-b', text='复盘', depth=1),
            SimpleNamespace(origin_id=92, node_uid='shared-node', text='季度复盘', depth=0),
        ]
        db = SimpleNamespace(execute=AsyncMock(side_effect=[
            SimpleNamespace(scalar_one=lambda: 2),
            SimpleNamespace(all=lambda: rows),
            SimpleNamespace(all=lambda: path_rows),
        ]))

        result = await MindmapService.search_global_nodes_services(
            db,
            user_id=7,
            keyword='季度',
            page_num=1,
            page_size=20,
        )

        self.assertEqual(result.total, 2)
        self.assertEqual(db.execute.await_count, 3)
        self.assertEqual(result.rows[0]['pathText'], '目标 / 季度目标')
        self.assertTrue(result.rows[0]['canEdit'])
        self.assertEqual(result.rows[1]['accessType'], 'shared')
        self.assertFalse(result.rows[1]['canEdit'], '归档共享文件必须只读打开')

        count_query = db.execute.await_args_list[0].args[0]
        sql = str(count_query.compile(compile_kwargs={'literal_binds': True}))
        self.assertIn('mindmap_collaborator.user_id = 7', sql)
        self.assertIn("mindmap.del_flag = '0'", sql)
        self.assertIn('mindmap.is_template = 0', sql)
        self.assertIn("mindmap_migration_record.status != 'failed'", sql)

        path_query = db.execute.await_args_list[2].args[0]
        path_sql = str(path_query.compile(compile_kwargs={'literal_binds': True}))
        self.assertIn('mindmap_node_ancestor_chain.file_id', path_sql)
        self.assertIn('mindmap_node_ancestor_chain.parent_id', path_sql)


if __name__ == '__main__':
    unittest.main()
