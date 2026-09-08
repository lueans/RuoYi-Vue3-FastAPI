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
    MindmapTagCategoryMutationModel,
    MindmapTagModel,
    MindmapTagQueryModel,
)
from module_mindmap.service.mindmap_document_service import MindmapDocumentService
from module_mindmap.service.mindmap_tag_service import (
    MindmapTagService,
    _TagGovernanceContext,
    _TagGovernanceScopeChanged,
)
from server import create_app


class MindmapTagServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_category_create_freezes_id_before_commit_expires_orm_state(self) -> None:
        class ExpiringCategory:
            expired = False
            id = 17

            def __getattribute__(self, name: str) -> Any:
                if (
                    name not in {'expired', '__dict__', '__class__'}
                    and object.__getattribute__(self, 'expired')
                ):
                    raise RuntimeError(f'expired ORM attribute accessed after commit: {name}')
                return object.__getattribute__(self, name)

        category = ExpiringCategory()

        async def commit() -> None:
            category.expired = True

        db = SimpleNamespace(commit=AsyncMock(side_effect=commit), rollback=AsyncMock())
        with (
            patch.object(
                MindmapTagDao,
                'check_category_name_unique',
                new=AsyncMock(return_value=True),
            ),
            patch.object(
                MindmapTagDao,
                'add_category',
                new=AsyncMock(return_value=category),
            ),
        ):
            result = await MindmapTagService.add_category(
                db,
                MindmapTagCategoryMutationModel(name='风险', ownerScope='mine'),
                user_id=42,
                user_name='owner',
            )

        self.assertEqual(result.result, {'categoryId': 17})
        db.commit.assert_awaited_once()

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
            patch.object(
                MindmapTagService,
                '_lock_definition_update_context',
                new=AsyncMock(return_value=_TagGovernanceContext(
                    mindmaps={126: SimpleNamespace(id=126)},
                    tags={8: tag},
                    affected_bindings=[SimpleNamespace(
                        id=1,
                        file_id=126,
                        node_id=11,
                        tag_id=8,
                    )],
                    related_bindings=[],
                )),
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

    async def test_create_rejects_duplicate_active_marker_icon(self) -> None:
        model = MindmapTagModel(
            tagKey='custom_priority',
            name='重复优先级',
            ownerId=0,
            status=0,
            style={'iconKey': 'priority_1'},
        )
        with (
            patch(
                'module_mindmap.service.mindmap_tag_service.MindmapTagDao.check_key_unique',
                new=AsyncMock(return_value=True),
            ),
            patch(
                'module_mindmap.service.mindmap_tag_service.MindmapTagDao.check_marker_icon_unique',
                new=AsyncMock(return_value=False),
            ),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapTagService.add_tag(
                SimpleNamespace(), model, user_id=1, user_name='admin',
            )

        self.assertIn('已被其他启用标签使用', context.exception.message)

    async def test_builtin_marker_key_must_match_immutable_icon_mapping(self) -> None:
        tag = SimpleNamespace(
            id=8,
            owner_id=0,
            tag_key='builtin_marker_priority_1',
            status=0,
        )
        model = MindmapTagModel(
            id=8,
            tagKey='builtin_marker_priority_1',
            name='优先级 1',
            ownerId=0,
            status=0,
            style={'iconKey': 'priority_2'},
        )
        with (
            patch.object(
                MindmapTagService,
                '_lock_definition_update_context',
                new=AsyncMock(return_value=_TagGovernanceContext(
                    mindmaps={},
                    tags={8: tag},
                    affected_bindings=[],
                    related_bindings=[],
                )),
            ),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapTagService.update_tag(SimpleNamespace(), model, user_id=1)

        self.assertIn('必须与节点标记图标保持一致', context.exception.message)

    async def test_builtin_marker_cannot_leave_global_reserved_identity(self) -> None:
        tag = SimpleNamespace(
            id=8,
            owner_id=0,
            tag_key='builtin_marker_priority_1',
            status=0,
        )
        model = MindmapTagModel(
            id=8,
            tagKey='renamed_priority',
            name='优先级 1',
            ownerId=42,
            status=0,
            style={'iconKey': 'priority_1'},
        )
        with (
            patch.object(
                MindmapTagService,
                '_lock_definition_update_context',
                new=AsyncMock(return_value=_TagGovernanceContext(
                    mindmaps={},
                    tags={8: tag},
                    affected_bindings=[],
                    related_bindings=[],
                )),
            ),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapTagService.update_tag(SimpleNamespace(), model, user_id=1)

        self.assertIn('Key 和全局作用域不可修改', context.exception.message)

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
            patch.object(
                MindmapTagService,
                '_lock_definition_update_context',
                new=AsyncMock(return_value=_TagGovernanceContext(
                    mindmaps={},
                    tags={8: tag},
                    affected_bindings=[],
                    related_bindings=[],
                )),
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
        db = SimpleNamespace(rollback=AsyncMock())
        context = _TagGovernanceContext(
            mindmaps={
                101: SimpleNamespace(id=101, owner_id=2, del_flag='0'),
                102: SimpleNamespace(id=102, owner_id=3, del_flag='0'),
            },
            tags={8: tag},
            affected_bindings=[
                SimpleNamespace(id=1, file_id=101, node_id=11, tag_id=8),
                SimpleNamespace(id=2, file_id=102, node_id=12, tag_id=8),
            ],
            related_bindings=[],
        )

        with (
            patch.object(
                MindmapTagService,
                '_lock_definition_update_context',
                new=AsyncMock(return_value=context),
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
            patch.object(
                MindmapTagService,
                '_lock_governance_context',
                new=AsyncMock(return_value=_TagGovernanceContext(
                    mindmaps={},
                    tags={8: source, 9: target},
                    affected_bindings=[],
                    related_bindings=[],
                )),
            ),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapTagService.replace_tag(SimpleNamespace(), 8, 9, user_id=1)

        self.assertIn('全局标签只能替换为全局标签', context.exception.message)

    async def test_private_tag_cannot_move_bindings_to_another_private_scope(self) -> None:
        source = SimpleNamespace(id=8, owner_id=42, definition_revision=1)
        target = SimpleNamespace(id=9, owner_id=43, status=0)
        with (
            patch.object(
                MindmapTagService,
                '_lock_governance_context',
                new=AsyncMock(return_value=_TagGovernanceContext(
                    mindmaps={},
                    tags={8: source, 9: target},
                    affected_bindings=[],
                    related_bindings=[],
                )),
            ),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapTagService.replace_tag(SimpleNamespace(), 8, 9, user_id=42)

        self.assertIn('同属一个私有范围', context.exception.message)

    async def test_batch_file_access_rejects_any_uneditable_file(self) -> None:
        query_result = MagicMock()
        query_result.all.return_value = []
        db = SimpleNamespace(execute=AsyncMock(return_value=query_result))
        mindmaps = {
            101: SimpleNamespace(id=101, owner_id=42, del_flag='0', status=0),
            102: SimpleNamespace(id=102, owner_id=99, del_flag='0', status=0),
        }

        with self.assertRaises(ServiceException) as context:
            await MindmapTagService._check_locked_files_edit_access(
                db, mindmaps, [101, 102], user_id=42,
            )

        self.assertIn('1 个受影响脑图无编辑权限', context.exception.message)
        db.execute.assert_awaited_once()
        permission_query = db.execute.await_args.args[0]
        self.assertIn('mindmap_collaborator.permission', str(permission_query))
        self.assertIsNotNone(permission_query._for_update_arg)

    async def test_admin_batch_access_still_rejects_archived_files(self) -> None:
        db = SimpleNamespace(execute=AsyncMock())
        mindmaps = {
            101: SimpleNamespace(id=101, owner_id=42, del_flag='0', status=0),
            102: SimpleNamespace(id=102, owner_id=42, del_flag='0', status=1),
        }

        with self.assertRaises(ServiceException):
            await MindmapTagService._check_locked_files_edit_access(
                db, mindmaps, [101, 102], user_id=1,
            )

        db.execute.assert_not_awaited()

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
        db = SimpleNamespace(execute=AsyncMock(), rollback=AsyncMock())
        context = _TagGovernanceContext(
            mindmaps={},
            tags={8: SimpleNamespace(id=8, owner_id=42, name='风险')},
            affected_bindings=[],
            related_bindings=[],
        )

        with (
            patch.object(
                MindmapTagService,
                '_lock_governance_context',
                new=AsyncMock(return_value=context),
            ),
            self.assertRaises(ServiceException) as error_context,
        ):
            await MindmapTagService.delete_tags(db, '8,9', user_id=42, unbind=True)

        self.assertIn('1 个标签不存在', error_context.exception.message)
        db.execute.assert_not_awaited()
        db.rollback.assert_awaited_once()

    async def test_safe_broadcast_does_not_fail_committed_operation(self) -> None:
        with patch(
            'module_mindmap.service.mindmap_tag_service.room_manager.broadcast',
            new=AsyncMock(side_effect=RuntimeError('redis unavailable')),
        ):
            await MindmapTagService._safe_broadcast(
                101, {'type': 'tag_unbound'}, revision=7, operation='测试通知',
            )

    async def test_delete_tags_uses_batch_queries_and_one_access_check(self) -> None:
        tags = {
            8: SimpleNamespace(id=8, owner_id=42, name='风险'),
            9: SimpleNamespace(id=9, owner_id=42, name='阻塞'),
        }
        bindings = [
            SimpleNamespace(id=1, file_id=101, node_id=11, tag_id=8),
            SimpleNamespace(id=2, file_id=101, node_id=12, tag_id=8),
            SimpleNamespace(id=3, file_id=102, node_id=13, tag_id=8),
            SimpleNamespace(id=4, file_id=102, node_id=14, tag_id=9),
            SimpleNamespace(id=5, file_id=102, node_id=15, tag_id=9),
        ]
        mindmaps = {
            101: SimpleNamespace(id=101, owner_id=42, del_flag='0', status=0),
            102: SimpleNamespace(id=102, owner_id=42, del_flag='0', status=0),
        }
        context = _TagGovernanceContext(
            mindmaps=mindmaps,
            tags=tags,
            affected_bindings=bindings,
            related_bindings=[],
        )
        db = SimpleNamespace(
            execute=AsyncMock(),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        with (
            patch.object(
                MindmapTagService,
                '_lock_governance_context',
                new=AsyncMock(return_value=context),
            ),
            patch.object(
                MindmapTagService, '_check_locked_files_edit_access', new=AsyncMock(),
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
        self.assertEqual(db.execute.await_count, 2)
        access_mock.assert_awaited_once_with(db, mindmaps, [101, 102], 42)
        revision_mock.assert_awaited_once()
        self.assertEqual(broadcast_mock.await_count, 2)
        db.commit.assert_awaited_once()
        db.rollback.assert_not_awaited()

    async def test_governance_scope_uses_mindmap_tag_binding_lock_order(self) -> None:
        calls: list[str] = []
        source = SimpleNamespace(id=8)

        async def affected_files(*_args: Any, **_kwargs: Any) -> list[int]:
            calls.append('preview')
            return [101]

        async def lock_mindmaps(*_args: Any, **_kwargs: Any) -> dict[int, Any]:
            calls.append('mindmap')
            return {101: SimpleNamespace(id=101)}

        async def lock_tags(*_args: Any, **_kwargs: Any) -> list[Any]:
            calls.append('tag')
            return [source]

        async def lock_bindings(*_args: Any, **_kwargs: Any) -> list[Any]:
            calls.append('binding')
            return [
                SimpleNamespace(id=1, file_id=101, node_id=11, tag_id=8),
                SimpleNamespace(id=2, file_id=102, node_id=12, tag_id=8),
            ]

        with (
            patch.object(MindmapTagService, '_affected_file_ids', new=affected_files),
            patch.object(MindmapTagService, '_lock_mindmaps', new=lock_mindmaps),
            patch.object(MindmapTagDao, 'get_tags_by_ids', new=lock_tags),
            patch.object(MindmapTagService, '_lock_tag_bindings', new=lock_bindings),
            self.assertRaises(_TagGovernanceScopeChanged),
        ):
            await MindmapTagService._lock_governance_context(
                SimpleNamespace(),
                affected_tag_ids={8},
            )

        self.assertEqual(calls, ['preview', 'mindmap', 'tag', 'binding'])

    async def test_replace_retries_newly_discovered_file_before_writes(self) -> None:
        source = SimpleNamespace(
            id=8,
            owner_id=42,
            definition_revision=2,
        )
        target = SimpleNamespace(
            id=9,
            owner_id=42,
            status=0,
            definition_revision=4,
            category_id=3,
            uuid='target-uuid',
            tag_key='target',
            name='目标',
            style={'fill': '#fff'},
        )
        mindmap = SimpleNamespace(
            id=102,
            owner_id=42,
            del_flag='0',
            status=0,
            content_revision=6,
        )
        stable_context = _TagGovernanceContext(
            mindmaps={102: mindmap},
            tags={8: source, 9: target},
            affected_bindings=[
                SimpleNamespace(id=1, file_id=102, node_id=11, tag_id=8),
            ],
            related_bindings=[],
        )
        ordering: list[str] = []

        async def commit() -> None:
            ordering.append('commit')

        async def broadcast(*_args: Any, **_kwargs: Any) -> None:
            ordering.append('broadcast')

        db = SimpleNamespace(
            execute=AsyncMock(),
            commit=AsyncMock(side_effect=commit),
            rollback=AsyncMock(),
        )
        broadcast_mock = AsyncMock(side_effect=broadcast)
        with (
            patch.object(
                MindmapTagService,
                '_lock_governance_context',
                new=AsyncMock(side_effect=[_TagGovernanceScopeChanged(), stable_context]),
            ) as context_mock,
            patch.object(
                MindmapTagService, '_check_locked_files_edit_access', new=AsyncMock(),
            ),
            patch.object(
                MindmapTagService,
                '_advance_file_revisions',
                new=AsyncMock(return_value={102: 7}),
            ),
            patch.object(MindmapTagService, '_refresh_usage', new=AsyncMock()),
            patch.object(MindmapTagDao, 'update_tag', new=AsyncMock()),
            patch.object(MindmapTagService, '_safe_broadcast', new=broadcast_mock),
        ):
            result = await MindmapTagService.replace_tag(db, 8, 9, user_id=42)

        self.assertTrue(result.is_success)
        self.assertEqual(context_mock.await_count, 2)
        db.rollback.assert_awaited_once()
        db.commit.assert_awaited_once()
        self.assertEqual(ordering, ['commit', 'broadcast'])
        event = broadcast_mock.await_args.args[1]
        self.assertEqual(event['contentRevision'], 7)
        self.assertEqual(event['authoritativeRevision'], 7)

    async def test_document_binding_validation_uses_locked_fresh_tag_context(self) -> None:
        old_tag = SimpleNamespace(
            id=9,
            uuid='old-uuid',
            owner_id=42,
            tag_key='old',
            name='旧标签',
            status=0,
        )
        archived_target = SimpleNamespace(
            id=8,
            uuid='new-uuid',
            owner_id=42,
            tag_key='new',
            name='已归档',
            status=2,
        )
        old_ids_result = MagicMock()
        old_ids_result.scalars.return_value = [9]
        locked_tags_result = MagicMock()
        locked_tags_result.scalars.return_value = [archived_target, old_tag]
        db = SimpleNamespace(execute=AsyncMock(side_effect=[old_ids_result, locked_tags_result]))
        bindings = [{
            'node_uid': 'node-1',
            'raw': {'tagId': 8, 'text': '陈旧客户端名称'},
        }]

        with (
            patch.object(
                MindmapDocumentService,
                '_load_existing_tag_bindings',
                new=AsyncMock(return_value=set()),
            ),
            self.assertRaisesRegex(ValueError, '已停用或归档'),
        ):
            await MindmapDocumentService._lock_and_resolve_tag_bindings(
                db,
                file_id=101,
                bindings=bindings,
                owner_id=42,
                operator='tester',
                allow_disabled_bindings=False,
            )

        locked_query = db.execute.await_args_list[1].args[0]
        self.assertIsNotNone(locked_query._for_update_arg)
        self.assertTrue(locked_query.get_execution_options()['populate_existing'])
        self.assertIn('ORDER BY mindmap_tag.id ASC', str(locked_query))

    async def test_affected_files_uses_current_read_after_tag_lock(self) -> None:
        result = MagicMock()
        result.scalars.return_value = [101, 101, 102]
        db = SimpleNamespace(execute=AsyncMock(return_value=result))

        file_ids = await MindmapTagService._affected_file_ids(
            db,
            {8},
            for_update=True,
        )

        self.assertEqual(file_ids, [101, 102])
        query = db.execute.await_args.args[0]
        self.assertIsNotNone(query._for_update_arg)
        self.assertTrue(query._for_update_arg.read)
        self.assertTrue(query.get_execution_options()['populate_existing'])

    async def test_tag_binding_scope_is_a_nonaggregate_locking_current_read(self) -> None:
        result = MagicMock()
        result.scalars.return_value = []
        db = SimpleNamespace(execute=AsyncMock(return_value=result))

        bindings = await MindmapTagService._lock_tag_bindings(db, {8})

        self.assertEqual(bindings, [])
        query = db.execute.await_args.args[0]
        self.assertIsNotNone(query._for_update_arg)
        self.assertTrue(query.get_execution_options()['populate_existing'])
        self.assertNotIn('count(', str(query).lower())

    async def test_usage_refresh_counts_rows_from_a_locking_current_read(self) -> None:
        result = MagicMock()
        result.all.return_value = [(8, 101), (8, 101), (8, 102)]
        db = SimpleNamespace(execute=AsyncMock(return_value=result))
        update_tag = AsyncMock()

        with patch.object(MindmapTagDao, 'update_tag', new=update_tag):
            await MindmapTagService._refresh_usage(db, {8, 9})

        query = db.execute.await_args.args[0]
        self.assertIsNotNone(query._for_update_arg)
        self.assertTrue(query._for_update_arg.read)
        self.assertTrue(query.get_execution_options()['populate_existing'])
        updates = {call.args[1]: call.args[2] for call in update_tag.await_args_list}
        self.assertEqual(updates, {
            8: {'usage_node_count': 3, 'usage_file_count': 2},
            9: {'usage_node_count': 0, 'usage_file_count': 0},
        })

    async def test_advance_revision_uses_prelocked_mindmap_then_locks_ws_state(self) -> None:
        db = SimpleNamespace(
            execute=AsyncMock(return_value=MagicMock()),
            add=MagicMock(),
        )
        mindmaps = {
            101: SimpleNamespace(id=101, content_revision=3),
            102: SimpleNamespace(id=102, content_revision=7),
        }

        revisions = await MindmapTagService._advance_file_revisions(
            db,
            mindmaps,
            [102, 101],
            user_id=42,
            operation={'type': 'tag.unbind'},
        )

        self.assertEqual(revisions, {101: 4, 102: 8})
        ws_lock_query = db.execute.await_args_list[0].args[0]
        self.assertIn('mindmap_ws_state', str(ws_lock_query))
        self.assertIsNotNone(ws_lock_query._for_update_arg)
        self.assertIn('ORDER BY mindmap_ws_state.mindmap_id ASC', str(ws_lock_query))
        self.assertEqual(db.add.call_count, 2)

    async def test_locked_permission_failure_rolls_back_update_transaction(self) -> None:
        tag = SimpleNamespace(id=8, owner_id=99)
        db = SimpleNamespace(rollback=AsyncMock())
        model = MindmapTagModel(
            id=8,
            tagKey='stable',
            name='标签',
            ownerId=99,
            style={},
            status=0,
        )
        lock_context = AsyncMock(return_value=_TagGovernanceContext(
            mindmaps={},
            tags={8: tag},
            affected_bindings=[],
            related_bindings=[],
        ))

        with (
            patch.object(
                MindmapTagService,
                '_lock_definition_update_context',
                new=lock_context,
            ),
            self.assertRaises(ServiceException),
        ):
            await MindmapTagService.update_tag(db, model, user_id=42)

        lock_context.assert_awaited_once_with(db, 8)
        db.rollback.assert_awaited_once()


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
