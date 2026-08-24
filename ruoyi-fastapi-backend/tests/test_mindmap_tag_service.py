"""统一标签主数据约束测试。"""
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from common.vo import PageModel
from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_tag_dao import MindmapTagDao
from module_mindmap.entity.vo.mindmap_tag_vo import (
    MAX_MINDMAP_TAG_BATCH_IDS_TEXT_LENGTH,
    MAX_MINDMAP_TAG_BATCH_SIZE,
    MAX_MINDMAP_TAG_ID,
    MINDMAP_TAG_BATCH_IDS_PATTERN,
    MindmapTagModel,
    MindmapTagQueryModel,
)
from module_mindmap.service.mindmap_document_service import MindmapDocumentService
from module_mindmap.service.mindmap_tag_service import MindmapTagService
from server import create_app


class MindmapTagServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_update_captures_definition_before_commit_expires_orm_state(self) -> None:
        class ExpiringTag:
            expired = False
            id = 8
            owner_id = 0
            tag_key = 'testcase_priority_p0'
            uuid = 'tag-uuid'
            name = 'P0'
            style = {'fill': '#fa0000'}
            status = 0
            definition_revision = 2

            def __getattribute__(self, name: str) -> Any:
                if (
                    name not in {'expired', '__dict__', '__class__'}
                    and object.__getattribute__(self, 'expired')
                ):
                    raise RuntimeError(f'expired ORM attribute accessed after commit: {name}')
                return object.__getattribute__(self, name)

        tag = ExpiringTag()
        affected_result = MagicMock()
        affected_result.scalars.return_value = [126]

        async def commit() -> None:
            tag.expired = True

        db = SimpleNamespace(
            execute=AsyncMock(return_value=affected_result),
            commit=AsyncMock(side_effect=commit),
            rollback=AsyncMock(),
        )
        model = MindmapTagModel(
            id=8,
            tagKey='testcase_priority_p0',
            name='P0',
            categoryId=2,
            ownerId=0,
            status=0,
            style={
                'fill': '#fa0000',
                'color': '#ffffff',
                'fontSize': 12,
                'radius': 3,
                'paddingX': 8,
                'placement': 'top',
                'align': 'left',
            },
        )
        with (
            patch(
                'module_mindmap.service.mindmap_tag_service.MindmapTagDao.get_tag_by_id',
                new=AsyncMock(return_value=tag),
            ),
            patch(
                'module_mindmap.service.mindmap_tag_service.MindmapTagDao.get_category_by_id',
                new=AsyncMock(return_value=SimpleNamespace(id=2, owner_id=0)),
            ),
            patch(
                'module_mindmap.service.mindmap_tag_service.MindmapTagDao.update_tag',
                new=AsyncMock(),
            ),
            patch.object(MindmapTagService, '_safe_broadcast', new=AsyncMock()) as broadcast_mock,
        ):
            result = await MindmapTagService.update_tag(db, model, user_id=1)

        self.assertTrue(result.is_success)
        event = broadcast_mock.await_args.args[1]
        self.assertEqual(event['definition']['style']['placement'], 'top')
        self.assertEqual(event['definition']['style']['align'], 'left')
        db.commit.assert_awaited_once()
        db.rollback.assert_not_awaited()

    async def test_legacy_option_only_binding_cannot_be_recreated_by_display_name(self) -> None:
        with self.assertRaisesRegex(ValueError, '旧版标签草稿缺少 tagId'):
            await MindmapDocumentService._resolve_single_tag(
                AsyncMock(),
                {'fieldId': 3, 'optionId': 8, 'text': '高优先级'},
                owner_id=42,
                operator='tester',
                cache={},
            )

    async def test_ungrouped_filter_uses_null_category_without_breaking_pagination(self) -> None:
        page = PageModel(rows=[], pageNum=1, pageSize=20, total=0, hasNext=False)
        with patch(
            'module_mindmap.dao.mindmap_tag_dao.PageUtil.paginate',
            new=AsyncMock(return_value=page),
        ) as paginate_mock:
            result = await MindmapTagDao.get_tag_list(
                SimpleNamespace(),
                user_id=42,
                category_id=0,
            )

        query = paginate_mock.await_args.args[1]
        self.assertIn('mindmap_tag.category_id IS NULL', str(query))
        self.assertEqual(result.total, 0)

    async def test_create_rejects_another_users_private_category(self) -> None:
        model = MindmapTagModel(
            tagKey='risk',
            name='风险',
            categoryId=9,
            ownerId=42,
            style={},
        )
        with (
            patch(
                'module_mindmap.service.mindmap_tag_service.MindmapTagDao.get_category_by_id',
                new=AsyncMock(return_value=SimpleNamespace(id=9, owner_id=77)),
            ),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapTagService.add_tag(
                SimpleNamespace(), model, user_id=42, user_name='tester',
            )

        self.assertIn('不属于当前标签作用域', context.exception.message)

    async def test_global_tag_rejects_private_category(self) -> None:
        model = MindmapTagModel(
            tagKey='global_risk',
            name='全局风险',
            categoryId=9,
            ownerId=0,
            style={},
        )
        with (
            patch(
                'module_mindmap.service.mindmap_tag_service.MindmapTagDao.get_category_by_id',
                new=AsyncMock(return_value=SimpleNamespace(id=9, owner_id=1)),
            ),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapTagService.add_tag(
                SimpleNamespace(), model, user_id=1, user_name='admin',
            )

        self.assertIn('不属于当前标签作用域', context.exception.message)

    async def test_list_forwards_unified_tag_filters(self) -> None:
        page = PageModel(
            rows=[{'id': 11, 'style': {'color': '#111'}}],
            pageNum=1,
            pageSize=20,
            total=1,
            hasNext=False,
        )
        query = MindmapTagQueryModel(
            categoryId=3,
            status=1,
            keyword='风险',
            ownerScope='mine',
        )
        with (
            patch(
                'module_mindmap.service.mindmap_tag_service.MindmapTagDao.get_tag_list',
                new=AsyncMock(return_value=page),
            ) as list_mock,
        ):
            result = await MindmapTagService.get_tag_list(SimpleNamespace(), query, user_id=42)

        list_mock.assert_awaited_once_with(
            ANY,
            42,
            category_id=3,
            status=1,
            keyword='风险',
            owner_scope='mine',
            page_num=1,
            page_size=20,
        )
        self.assertEqual(result.rows[0]['style'], {'color': '#111'})

    def test_query_accepts_zero_as_the_ungrouped_sentinel(self) -> None:
        self.assertEqual(MindmapTagQueryModel(categoryId=0).category_id, 0)

    async def test_non_admin_cannot_change_stable_tag_key(self) -> None:
        tag = SimpleNamespace(id=8, owner_id=42, tag_key='stable_key')
        model = MindmapTagModel(
            id=8,
            tagKey='changed_key',
            name='标签',
            ownerId=42,
            style={},
            status=0,
        )
        with (
            patch(
                'module_mindmap.service.mindmap_tag_service.MindmapTagDao.get_tag_by_id',
                new=AsyncMock(return_value=tag),
            ),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapTagService.update_tag(SimpleNamespace(), model, user_id=42)

        self.assertIn('稳定外部标识', context.exception.message)

    async def test_global_tag_cannot_be_narrowed_while_other_owners_use_it(self) -> None:
        tag = SimpleNamespace(id=8, owner_id=0, tag_key='shared')
        model = MindmapTagModel(
            id=8,
            tagKey='shared',
            name='共享标签',
            ownerId=1,
            style={},
            status=0,
        )
        foreign_count = MagicMock()
        foreign_count.scalar_one.return_value = 2
        db = SimpleNamespace(execute=AsyncMock(return_value=foreign_count))

        with (
            patch(
                'module_mindmap.service.mindmap_tag_service.MindmapTagDao.get_tag_by_id',
                new=AsyncMock(return_value=tag),
            ),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapTagService.update_tag(db, model, user_id=1)

        self.assertIn('2 个其他所有者', context.exception.message)

    def test_replacement_duplicate_query_uses_node_and_tag_identity_only(self) -> None:
        query = MindmapTagService._replacement_duplicate_query(8, 9)
        sql = str(query.compile(compile_kwargs={'literal_binds': True}))
        self.assertIn('mindmap_node_tag.tag_id = 8', sql)
        self.assertIn('mindmap_node_tag.tag_id = 9', sql)
        self.assertNotIn('field_id', sql)
        self.assertNotIn('option_id', sql)

    async def test_global_tag_cannot_be_replaced_with_private_tag(self) -> None:
        source = SimpleNamespace(id=8, owner_id=0, definition_revision=1)
        target = SimpleNamespace(id=9, owner_id=1, status=0)
        with (
            patch(
                'module_mindmap.service.mindmap_tag_service.MindmapTagDao.get_tag_by_id',
                new=AsyncMock(side_effect=[source, target]),
            ),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapTagService.replace_tag(SimpleNamespace(), 8, 9, user_id=1)

        self.assertIn('全局标签只能替换为全局标签', context.exception.message)

    async def test_private_tag_cannot_move_bindings_to_another_private_scope(self) -> None:
        source = SimpleNamespace(id=8, owner_id=42, definition_revision=1)
        target = SimpleNamespace(id=9, owner_id=43, status=0)
        with (
            patch(
                'module_mindmap.service.mindmap_tag_service.MindmapTagDao.get_tag_by_id',
                new=AsyncMock(side_effect=[source, target]),
            ),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapTagService.replace_tag(SimpleNamespace(), 8, 9, user_id=42)

        self.assertIn('同属一个私有范围', context.exception.message)

    async def test_batch_file_access_rejects_any_uneditable_file(self) -> None:
        query_result = MagicMock()
        query_result.scalars.return_value = [101]
        db = SimpleNamespace(execute=AsyncMock(return_value=query_result))

        with self.assertRaises(ServiceException) as context:
            await MindmapTagService._check_files_edit_access(db, [101, 102], user_id=42)

        self.assertIn('1 个受影响脑图无编辑权限', context.exception.message)
        db.execute.assert_awaited_once()
        self.assertIn('mindmap.status', str(db.execute.await_args.args[0]))

    async def test_admin_batch_access_still_rejects_archived_files(self) -> None:
        query_result = MagicMock()
        query_result.scalars.return_value = [101]
        db = SimpleNamespace(execute=AsyncMock(return_value=query_result))

        with self.assertRaises(ServiceException):
            await MindmapTagService._check_files_edit_access(db, [101, 102], user_id=1)

        query_text = str(db.execute.await_args.args[0])
        self.assertIn('mindmap.status', query_text)
        self.assertNotIn('mindmap_collaborator', query_text)

    def test_parse_tag_ids_deduplicates_and_rejects_invalid_values(self) -> None:
        self.assertEqual(MindmapTagService._parse_tag_ids('3, 2,3'), [3, 2])
        for invalid_value in ('', '1,abc', '0', '-1'):
            with self.subTest(invalid_value=invalid_value), self.assertRaises(ServiceException):
                MindmapTagService._parse_tag_ids(invalid_value)

        with self.assertRaises(ServiceException) as oversized_context:
            MindmapTagService._parse_tag_ids(str(MAX_MINDMAP_TAG_ID + 1))
        self.assertIn('数据库整数范围', oversized_context.exception.message)
        with self.assertRaises(ServiceException) as batch_context:
            MindmapTagService._parse_tag_ids(
                ','.join(str(tag_id) for tag_id in range(1, MAX_MINDMAP_TAG_BATCH_SIZE + 2))
            )
        self.assertIn('单次最多处理', batch_context.exception.message)

    async def test_delete_tags_rejects_partial_target_sets_before_writes(self) -> None:
        tags_result = MagicMock()
        tags_result.scalars.return_value = [
            SimpleNamespace(id=8, owner_id=42, name='风险'),
        ]
        db = SimpleNamespace(execute=AsyncMock(return_value=tags_result))

        with self.assertRaises(ServiceException) as context:
            await MindmapTagService.delete_tags(db, '8,9', user_id=42, unbind=True)

        self.assertIn('1 个标签不存在', context.exception.message)
        db.execute.assert_awaited_once()

    async def test_safe_broadcast_does_not_fail_committed_operation(self) -> None:
        with patch(
            'module_mindmap.service.mindmap_tag_service.room_manager.broadcast',
            new=AsyncMock(side_effect=RuntimeError('redis unavailable')),
        ):
            await MindmapTagService._safe_broadcast(
                101, {'type': 'tag_unbound'}, revision=7, operation='测试通知',
            )

    async def test_delete_tags_uses_batch_queries_and_one_access_check(self) -> None:
        tags_result = MagicMock()
        tags_result.scalars.return_value = [
            SimpleNamespace(id=8, owner_id=42, name='风险'),
            SimpleNamespace(id=9, owner_id=42, name='阻塞'),
        ]
        usage_result = MagicMock()
        usage_result.all.return_value = [(8, 3), (9, 2)]
        files_result = MagicMock()
        files_result.scalars.return_value = [101, 102]
        write_result = MagicMock()
        db = SimpleNamespace(
            execute=AsyncMock(side_effect=[
                tags_result, usage_result, files_result, write_result, write_result,
            ]),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        with (
            patch.object(
                MindmapTagService, '_check_files_edit_access', new=AsyncMock(),
            ) as access_mock,
            patch.object(
                MindmapTagService, '_advance_file_revisions',
                new=AsyncMock(return_value={101: 7, 102: 8}),
            ) as revision_mock,
            patch.object(
                MindmapTagService, '_safe_broadcast', new=AsyncMock(),
            ) as broadcast_mock,
        ):
            result = await MindmapTagService.delete_tags(
                db, '8,9,8', user_id=42, unbind=True,
            )

        self.assertTrue(result.is_success)
        self.assertEqual(result.result['tagIds'], [8, 9])
        self.assertEqual(db.execute.await_count, 5)
        self.assertIsNotNone(db.execute.await_args_list[0].args[0]._for_update_arg)
        access_mock.assert_awaited_once_with(db, [101, 102], 42)
        revision_mock.assert_awaited_once()
        self.assertEqual(broadcast_mock.await_count, 2)
        db.commit.assert_awaited_once()
        db.rollback.assert_not_awaited()


class MindmapTagBatchArchiveOpenApiTest(unittest.TestCase):
    def test_archive_route_publishes_bounded_ids_and_typed_result(self) -> None:
        schema = create_app().openapi()
        operation = schema['paths']['/mindmap/tag/{tag_ids}']['delete']
        path_parameter = next(item for item in operation['parameters'] if item['name'] == 'tag_ids')

        self.assertEqual(path_parameter['schema']['maxLength'], MAX_MINDMAP_TAG_BATCH_IDS_TEXT_LENGTH)
        self.assertEqual(path_parameter['schema']['pattern'], MINDMAP_TAG_BATCH_IDS_PATTERN)

        response_schema = operation['responses']['200']['content']['application/json']['schema']
        response_model = schema['components']['schemas'][response_schema['$ref'].rsplit('/', 1)[-1]]
        data_schema = response_model['properties']['data']
        result_model = schema['components']['schemas'][data_schema['$ref'].rsplit('/', 1)[-1]]
        self.assertEqual(result_model['properties']['tagIds']['maxItems'], MAX_MINDMAP_TAG_BATCH_SIZE)
        self.assertEqual(result_model['properties']['affectedFileCount']['minimum'], 0)


if __name__ == '__main__':
    unittest.main()
