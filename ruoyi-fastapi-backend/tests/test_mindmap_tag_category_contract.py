"""标签分类生命周期输入、权限和响应契约。"""

import unittest
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, patch

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from exceptions.exception import ServiceException
from module_mindmap.entity.do.mindmap_tag_do import MindmapTagCategory
from module_mindmap.entity.vo.mindmap_tag_vo import (
    MAX_MINDMAP_TAG_CATEGORY_NAME_LENGTH,
    MAX_MINDMAP_TAG_CATEGORY_BATCH_SIZE,
    MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER,
    MindmapTagCategoryListItemModel,
    MindmapTagCategoryMutationModel,
    MindmapTagCategoryReorderModel,
)
from module_mindmap.service.mindmap_tag_service import MindmapTagService
from server import create_app


class MindmapTagCategoryModelTest(unittest.TestCase):
    def test_category_normalizes_name_and_bounds_sort_order(self) -> None:
        model = MindmapTagCategoryMutationModel(
            name=' 业务风险 ',
            sortOrder=-MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER,
            ownerScope='global',
        )

        self.assertEqual(model.name, '业务风险')
        self.assertEqual(model.sort_order, -MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER)
        self.assertEqual(model.owner_scope, 'global')

        for payload in (
            {'name': '   '},
            {'name': '风险\n分类'},
            {'name': '类' * (MAX_MINDMAP_TAG_CATEGORY_NAME_LENGTH + 1)},
            {'name': '风险', 'sortOrder': MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER + 1},
            {'name': '风险', 'ownerScope': 'team'},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                MindmapTagCategoryMutationModel(**payload)

    def test_category_type_and_reorder_payload_are_explicit_and_bounded(self) -> None:
        category = MindmapTagCategoryListItemModel(
            id=7, name='优先级', categoryType='system', ownerId=0,
        )
        self.assertEqual(category.category_type, 'system')
        self.assertEqual(
            MindmapTagCategoryReorderModel(categoryIds=[8, 7]).category_ids,
            [8, 7],
        )

        for category_ids in ([7, 7], [0], [True], [1.5]):
            with self.subTest(category_ids=category_ids), self.assertRaises(ValidationError):
                MindmapTagCategoryReorderModel(categoryIds=category_ids)


class MindmapTagCategoryServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_non_admin_cannot_create_global_category(self) -> None:
        model = MindmapTagCategoryMutationModel(name='全局风险', ownerScope='global')

        with self.assertRaises(ServiceException) as context:
            await MindmapTagService.add_category(
                SimpleNamespace(),
                model,
                user_id=42,
                user_name='tester',
            )

        self.assertIn('仅管理员', context.exception.message)

    async def test_create_rejects_duplicate_name_in_the_same_scope(self) -> None:
        model = MindmapTagCategoryMutationModel(name='风险')
        with (
            patch(
                'module_mindmap.service.mindmap_tag_service.MindmapTagDao.check_category_name_unique',
                new=AsyncMock(return_value=False),
            ),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapTagService.add_category(
                SimpleNamespace(),
                model,
                user_id=42,
                user_name='tester',
            )

        self.assertIn('已存在', context.exception.message)

    async def test_create_returns_server_generated_category_id(self) -> None:
        model = MindmapTagCategoryMutationModel(name='风险', sortOrder=8)
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        with (
            patch(
                'module_mindmap.service.mindmap_tag_service.MindmapTagDao.check_category_name_unique',
                new=AsyncMock(return_value=True),
            ),
            patch(
                'module_mindmap.service.mindmap_tag_service.MindmapTagDao.add_category',
                new=AsyncMock(return_value=SimpleNamespace(id=73)),
            ) as add_mock,
        ):
            result = await MindmapTagService.add_category(
                db,
                model,
                user_id=42,
                user_name='tester',
            )

        self.assertEqual(result.result, {'categoryId': 73})
        self.assertEqual(add_mock.await_args.args[1]['owner_id'], 42)
        self.assertEqual(add_mock.await_args.args[1]['category_type'], 'custom')
        self.assertEqual(add_mock.await_args.args[1]['sort_order'], 8)
        db.commit.assert_awaited_once()

    async def test_concurrent_duplicate_is_reported_as_a_business_conflict(self) -> None:
        model = MindmapTagCategoryMutationModel(name='风险')
        db = SimpleNamespace(
            commit=AsyncMock(side_effect=IntegrityError('INSERT', {}, Exception('duplicate'))),
            rollback=AsyncMock(),
        )
        with (
            patch(
                'module_mindmap.service.mindmap_tag_service.MindmapTagDao.check_category_name_unique',
                new=AsyncMock(return_value=True),
            ),
            patch(
                'module_mindmap.service.mindmap_tag_service.MindmapTagDao.add_category',
                new=AsyncMock(return_value=SimpleNamespace(id=73)),
            ),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapTagService.add_category(db, model, user_id=42, user_name='tester')

        self.assertIn('已存在', context.exception.message)
        db.rollback.assert_awaited_once()

    async def test_delete_locks_category_and_rechecks_references(self) -> None:
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        with (
            patch(
                'module_mindmap.service.mindmap_tag_service.MindmapTagDao.get_category_by_id',
                new=AsyncMock(return_value=SimpleNamespace(id=7, owner_id=42)),
            ) as category_mock,
            patch(
                'module_mindmap.service.mindmap_tag_service.MindmapTagDao.count_tags_in_category',
                new=AsyncMock(return_value=0),
            ) as count_mock,
            patch(
                'module_mindmap.service.mindmap_tag_service.MindmapTagDao.delete_category',
                new=AsyncMock(),
            ) as delete_mock,
        ):
            await MindmapTagService.delete_category(db, category_id=7, user_id=42)

        category_mock.assert_awaited_once_with(db, 7, for_update=True)
        count_mock.assert_awaited_once_with(db, 7)
        delete_mock.assert_awaited_once_with(db, 7)
        db.commit.assert_awaited_once()

    async def test_list_exposes_tag_count_for_delete_feedback(self) -> None:
        categories = [
            MindmapTagCategory(id=7, name='风险', owner_id=42, sort_order=0),
            MindmapTagCategory(id=8, name='进度', owner_id=0, sort_order=1),
        ]
        with (
            patch(
                'module_mindmap.service.mindmap_tag_service.MindmapTagDao.get_categories',
                new=AsyncMock(return_value=categories),
            ),
            patch(
                'module_mindmap.service.mindmap_tag_service.MindmapTagDao.get_category_tag_counts',
                new=AsyncMock(return_value={7: 3}),
            ) as count_mock,
        ):
            result = await MindmapTagService.get_categories(SimpleNamespace(), user_id=42)

        self.assertEqual([item['tagCount'] for item in result], [3, 0])
        count_mock.assert_awaited_once_with(ANY, [7, 8])

    async def test_reorder_updates_a_complete_single_owner_scope(self) -> None:
        categories = [
            SimpleNamespace(id=7, owner_id=42),
            SimpleNamespace(id=8, owner_id=42),
        ]
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        model = MindmapTagCategoryReorderModel(categoryIds=[8, 7])
        with (
            patch(
                'module_mindmap.service.mindmap_tag_service.MindmapTagDao.get_categories',
                new=AsyncMock(return_value=categories),
            ),
            patch(
                'module_mindmap.service.mindmap_tag_service.MindmapTagDao.get_categories_by_owner',
                new=AsyncMock(return_value=categories),
            ) as owner_mock,
            patch(
                'module_mindmap.service.mindmap_tag_service.MindmapTagDao.update_category_sort_orders',
                new=AsyncMock(),
            ) as update_mock,
        ):
            result = await MindmapTagService.reorder_categories(db, model, user_id=42)

        self.assertTrue(result.is_success)
        owner_mock.assert_awaited_once_with(db, 42, for_update=True)
        update_mock.assert_awaited_once_with(db, [8, 7])
        db.commit.assert_awaited_once()
        db.rollback.assert_not_awaited()

    async def test_reorder_rejects_mixed_owner_scopes(self) -> None:
        categories = [
            SimpleNamespace(id=7, owner_id=0),
            SimpleNamespace(id=8, owner_id=42),
        ]
        with (
            patch(
                'module_mindmap.service.mindmap_tag_service.MindmapTagDao.get_categories',
                new=AsyncMock(return_value=categories),
            ),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapTagService.reorder_categories(
                SimpleNamespace(),
                MindmapTagCategoryReorderModel(categoryIds=[8, 7]),
                user_id=42,
            )

        self.assertIn('同一范围', context.exception.message)


class MindmapTagCategoryOpenApiTest(unittest.TestCase):
    def test_mutation_routes_publish_name_sort_scope_and_positive_id_bounds(self) -> None:
        schema = create_app().openapi()
        create_parameters = schema['paths']['/mindmap/tag/category']['post']['parameters']
        update_parameters = schema['paths']['/mindmap/tag/category']['put']['parameters']
        delete_parameters = schema['paths']['/mindmap/tag/category/{category_id}']['delete']['parameters']

        create_by_name = {item['name']: item['schema'] for item in create_parameters}
        update_by_name = {item['name']: item['schema'] for item in update_parameters}
        delete_by_name = {item['name']: item['schema'] for item in delete_parameters}
        self.assertEqual(create_by_name['categoryName']['maxLength'], MAX_MINDMAP_TAG_CATEGORY_NAME_LENGTH)
        self.assertEqual(create_by_name['categoryName']['pattern'], r'^[^\x00-\x1f\x7f]*$')
        self.assertEqual(create_by_name['sortOrder']['minimum'], -MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER)
        self.assertEqual(create_by_name['sortOrder']['maximum'], MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER)
        self.assertEqual(create_by_name['ownerScope']['enum'], ['mine', 'global'])
        self.assertEqual(update_by_name['categoryId']['exclusiveMinimum'], 0)
        self.assertEqual(delete_by_name['category_id']['exclusiveMinimum'], 0)
        response_schema = schema['paths']['/mindmap/tag/category']['post']['responses']['200'][
            'content'
        ]['application/json']['schema']
        response_model = schema['components']['schemas'][response_schema['$ref'].rsplit('/', 1)[-1]]
        data_schema = response_model['properties']['data']
        create_result = schema['components']['schemas'][data_schema['$ref'].rsplit('/', 1)[-1]]
        self.assertEqual(create_result['properties']['categoryId']['exclusiveMinimum'], 0)

        list_response_schema = schema['paths']['/mindmap/tag/categories']['get']['responses']['200'][
            'content'
        ]['application/json']['schema']
        list_response_model = schema['components']['schemas'][
            list_response_schema['$ref'].rsplit('/', 1)[-1]
        ]
        list_items = list_response_model['properties']['data']['items']
        category_item = schema['components']['schemas'][list_items['$ref'].rsplit('/', 1)[-1]]
        self.assertEqual(category_item['properties']['tagCount']['minimum'], 0)
        self.assertEqual(category_item['properties']['categoryType']['enum'], ['system', 'custom'])

        reorder_schema = schema['paths']['/mindmap/tag/categories/order']['put']['requestBody'][
            'content'
        ]['application/json']['schema']
        reorder_model = schema['components']['schemas'][reorder_schema['$ref'].rsplit('/', 1)[-1]]
        self.assertEqual(
            reorder_model['properties']['categoryIds']['maxItems'],
            MAX_MINDMAP_TAG_CATEGORY_BATCH_SIZE,
        )


if __name__ == '__main__':
    unittest.main()
