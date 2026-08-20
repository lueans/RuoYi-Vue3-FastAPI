"""脑图标签字段变更一致性测试。"""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from exceptions.exception import ServiceException
from module_mindmap.entity.vo.mindmap_tag_field_vo import TagFieldModel, TagFieldOptionModel
from module_mindmap.service.mindmap_document_service import resolve_option_tag_styles
from module_mindmap.service.mindmap_tag_field_service import MindmapTagFieldService


def build_field(*, select_mode: str = 'multi', style: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=7,
        owner_id=42,
        field_key='priority',
        name='优先级',
        select_mode=select_mode,
        style=style or {'fontSize': 12},
    )


def build_model(*, select_mode: str = 'multi', style: dict | None = None) -> TagFieldModel:
    return TagFieldModel(
        id=7,
        fieldKey='priority',
        name='优先级',
        selectMode=select_mode,
        style=style or {'fontSize': 12},
        ownerId=42,
    )


class MindmapTagFieldServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_field_returns_persisted_identifier(self) -> None:
        field = SimpleNamespace(id=73)
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        with (
            patch(
                'module_mindmap.service.mindmap_tag_field_service.'
                'MindmapTagFieldDao.check_field_key_unique',
                new=AsyncMock(return_value=True),
            ),
            patch(
                'module_mindmap.service.mindmap_tag_field_service.'
                'MindmapTagFieldDao.add_field',
                new=AsyncMock(return_value=field),
            ),
        ):
            result = await MindmapTagFieldService.add_field(
                db,
                build_model(select_mode='single'),
                user_id=42,
                user_name='tester',
            )

        self.assertEqual(result.result, {'fieldId': 73})
        db.commit.assert_awaited_once()

    async def test_create_option_returns_option_and_unified_tag_identifiers(self) -> None:
        field = build_field(select_mode='single')
        option = SimpleNamespace(id=81)
        tag = SimpleNamespace(id=91)
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        with (
            patch(
                'module_mindmap.service.mindmap_tag_field_service.'
                'MindmapTagFieldDao.get_field_by_id',
                new=AsyncMock(return_value=field),
            ),
            patch(
                'module_mindmap.service.mindmap_tag_field_service.'
                'MindmapTagFieldDao.check_option_key_unique',
                new=AsyncMock(return_value=True),
            ),
            patch(
                'module_mindmap.service.mindmap_tag_field_service.'
                'MindmapTagFieldDao.add_option',
                new=AsyncMock(return_value=option),
            ),
            patch(
                'module_mindmap.service.mindmap_tag_field_service.'
                'MindmapDocumentService.sync_option_tag_definition',
                new=AsyncMock(return_value=(tag, [], {})),
            ),
        ):
            result = await MindmapTagFieldService.add_option(
                db,
                TagFieldOptionModel(
                    fieldId=7,
                    optionKey='p0',
                    name='最高优先级',
                    fill='#ff0000',
                    color='#ffffff',
                ),
                user_id=42,
            )

        self.assertEqual(result.result, {'optionId': 81, 'tagId': 91})
        db.commit.assert_awaited_once()

    def test_field_defaults_and_tag_overrides_are_resolved_without_materializing_defaults(self) -> None:
        own_style, resolved_style = resolve_option_tag_styles(
            {'fontSize': 16, 'radius': 3, 'fill': '#old'},
            {'fontSize': 12, 'radius': 8, 'paddingX': 10},
            '#new',
            '#fff',
            inherited_style={'fontSize': 12, 'radius': 3, 'paddingX': 8},
        )

        self.assertEqual(own_style, {'fontSize': 16, 'fill': '#new', 'color': '#fff'})
        self.assertEqual(resolved_style, {
            'fontSize': 16,
            'radius': 8,
            'paddingX': 10,
            'fill': '#new',
            'color': '#fff',
        })

    async def test_switching_to_single_rejects_existing_multi_selections(self) -> None:
        db = SimpleNamespace()
        with (
            patch(
                'module_mindmap.service.mindmap_tag_field_service.'
                'MindmapTagFieldDao.get_field_by_id',
                new=AsyncMock(return_value=build_field()),
            ),
            patch.object(
                MindmapTagFieldService,
                '_count_multi_selection_nodes',
                new=AsyncMock(return_value=3),
            ),
            patch(
                'module_mindmap.service.mindmap_tag_field_service.'
                'MindmapTagFieldDao.update_field',
                new=AsyncMock(),
            ) as update_field,
        ):
            with self.assertRaises(ServiceException) as context:
                await MindmapTagFieldService.update_field(
                    db, build_model(select_mode='single'), user_id=42,
                )
            self.assertIn('3 个节点', context.exception.message)
            update_field.assert_not_awaited()

    async def test_metadata_only_update_does_not_advance_all_tag_revisions(self) -> None:
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        with (
            patch(
                'module_mindmap.service.mindmap_tag_field_service.'
                'MindmapTagFieldDao.get_field_by_id',
                new=AsyncMock(return_value=build_field(select_mode='single')),
            ),
            patch(
                'module_mindmap.service.mindmap_tag_field_service.'
                'MindmapTagFieldDao.update_field',
                new=AsyncMock(),
            ),
            patch(
                'module_mindmap.service.mindmap_tag_field_service.'
                'MindmapTagFieldDao.get_options_by_field_id',
                new=AsyncMock(),
            ) as get_options,
        ):
            result = await MindmapTagFieldService.update_field(
                db, build_model(select_mode='single'), user_id=42,
            )

        self.assertTrue(result.is_success)
        db.commit.assert_awaited_once()
        get_options.assert_not_awaited()

    async def test_style_update_resolves_every_option_for_online_refresh(self) -> None:
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        options = [SimpleNamespace(id=11), SimpleNamespace(id=12)]
        sync_definition = AsyncMock(return_value=(None, [], {}))
        with (
            patch(
                'module_mindmap.service.mindmap_tag_field_service.'
                'MindmapTagFieldDao.get_field_by_id',
                new=AsyncMock(return_value=build_field(select_mode='single')),
            ),
            patch(
                'module_mindmap.service.mindmap_tag_field_service.'
                'MindmapTagFieldDao.update_field',
                new=AsyncMock(),
            ),
            patch(
                'module_mindmap.service.mindmap_tag_field_service.'
                'MindmapTagFieldDao.get_options_by_field_id',
                new=AsyncMock(return_value=options),
            ),
            patch(
                'module_mindmap.service.mindmap_tag_field_service.'
                'MindmapDocumentService.sync_option_tag_definition',
                new=sync_definition,
            ),
        ):
            await MindmapTagFieldService.update_field(
                db,
                build_model(select_mode='single', style={'fontSize': 16}),
                user_id=42,
            )

        self.assertEqual(sync_definition.await_count, 2)
        self.assertEqual(
            [call.args[1] for call in sync_definition.await_args_list],
            [11, 12],
        )
        self.assertEqual(
            [call.kwargs['inherited_style'] for call in sync_definition.await_args_list],
            [{'fontSize': 12}, {'fontSize': 12}],
        )

    async def test_style_update_keeps_old_style_even_if_orm_syncs_loaded_field(self) -> None:
        field = build_field(select_mode='single')
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        sync_definition = AsyncMock(return_value=(None, [], {}))

        async def mutate_loaded_field(*_args, **_kwargs) -> None:
            field.style = {'fontSize': 16}

        with (
            patch(
                'module_mindmap.service.mindmap_tag_field_service.'
                'MindmapTagFieldDao.get_field_by_id',
                new=AsyncMock(return_value=field),
            ),
            patch(
                'module_mindmap.service.mindmap_tag_field_service.'
                'MindmapTagFieldDao.update_field',
                new=AsyncMock(side_effect=mutate_loaded_field),
            ),
            patch(
                'module_mindmap.service.mindmap_tag_field_service.'
                'MindmapTagFieldDao.get_options_by_field_id',
                new=AsyncMock(return_value=[SimpleNamespace(id=11)]),
            ),
            patch(
                'module_mindmap.service.mindmap_tag_field_service.'
                'MindmapDocumentService.sync_option_tag_definition',
                new=sync_definition,
            ),
        ):
            await MindmapTagFieldService.update_field(
                db,
                build_model(select_mode='single', style={'fontSize': 16}),
                user_id=42,
            )

        self.assertEqual(sync_definition.await_args.kwargs['inherited_style'], {'fontSize': 12})

    async def test_field_scope_change_updates_linked_tag_scope_atomically(self) -> None:
        field = build_field(select_mode='single')
        field.owner_id = 0
        option = SimpleNamespace(id=11, tag_id=91)
        tag = SimpleNamespace(
            id=91,
            tag_key='field_priority_p0',
            owner_id=0,
            definition_revision=3,
        )
        tags_result = MagicMock()
        tags_result.scalars.return_value = [tag]
        no_foreign_files = MagicMock()
        no_foreign_files.scalar_one.return_value = 0
        no_linked_field_mismatch = MagicMock()
        no_linked_field_mismatch.scalar_one.return_value = 0
        no_category_mismatch = MagicMock()
        no_category_mismatch.scalar_one.return_value = 0
        no_conflict = MagicMock()
        no_conflict.scalar_one.return_value = 0
        db = SimpleNamespace(
            execute=AsyncMock(side_effect=[
                tags_result,
                no_foreign_files,
                no_linked_field_mismatch,
                no_category_mismatch,
                no_conflict,
            ]),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        model = build_model(select_mode='single')
        model.owner_id = 1

        with (
            patch(
                'module_mindmap.service.mindmap_tag_field_service.'
                'MindmapTagFieldDao.get_field_by_id',
                new=AsyncMock(return_value=field),
            ),
            patch(
                'module_mindmap.service.mindmap_tag_field_service.'
                'MindmapTagFieldDao.check_field_key_unique',
                new=AsyncMock(return_value=True),
            ),
            patch(
                'module_mindmap.service.mindmap_tag_field_service.'
                'MindmapTagFieldDao.get_options_by_field_id',
                new=AsyncMock(return_value=[option]),
            ),
            patch(
                'module_mindmap.service.mindmap_tag_field_service.'
                'MindmapTagFieldDao.update_field',
                new=AsyncMock(),
            ),
        ):
            await MindmapTagFieldService.update_field(db, model, user_id=1)

        self.assertEqual(tag.owner_id, 1)
        self.assertEqual(tag.definition_revision, 4)
        db.commit.assert_awaited_once()

    async def test_delete_option_checks_real_bindings_instead_of_usage_cache(self) -> None:
        option = SimpleNamespace(id=11, field_id=7, tag_id=91, name='高')
        field = build_field(select_mode='single')
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        db = SimpleNamespace(execute=AsyncMock(return_value=count_result))

        with (
            patch(
                'module_mindmap.service.mindmap_tag_field_service.'
                'MindmapTagFieldDao.get_option_by_id',
                new=AsyncMock(return_value=option),
            ),
            patch(
                'module_mindmap.service.mindmap_tag_field_service.'
                'MindmapTagFieldDao.get_field_by_id',
                new=AsyncMock(return_value=field),
            ),
            patch(
                'module_mindmap.service.mindmap_tag_field_service.'
                'MindmapTagFieldDao.delete_option',
                new=AsyncMock(),
            ) as delete_option,
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapTagFieldService.delete_option(db, 11, user_id=42)

        self.assertIn('1 个节点', context.exception.message)
        delete_option.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
