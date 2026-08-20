"""脑图模板浏览、发布和创建生命周期测试。"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from common.vo import CrudResponseModel
from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_template_dao import MindmapTemplateDao
from module_mindmap.entity.vo.mindmap_template_vo import (
    MAX_TEMPLATE_NAME_LENGTH,
    MindmapTemplatePublishModel,
    MindmapTemplateQueryModel,
)
from module_mindmap.service.mindmap_service import MindmapService
from module_mindmap.service.mindmap_tag_portability import MindmapTagPortabilityService
from module_mindmap.service.mindmap_template_service import MindmapTemplateService


class MindmapTemplateModelTest(unittest.TestCase):
    def test_publish_model_normalizes_text_and_safe_cover(self) -> None:
        model = MindmapTemplatePublishModel(
            mindmapId=9,
            name='  项目复盘  ',
            description='  复盘模板  ',
            coverImage='/uploads/template.png',
        )

        self.assertEqual(model.name, '项目复盘')
        self.assertEqual(model.description, '复盘模板')
        self.assertEqual(model.cover_image, '/uploads/template.png')
        relative = MindmapTemplatePublishModel(
            mindmapId=9,
            name='相对封面',
            coverImage='assets/template.png',
        )
        self.assertEqual(relative.cover_image, 'assets/template.png')

    def test_publish_model_rejects_invalid_boundaries_and_cover_protocols(self) -> None:
        invalid_values = (
            {'mindmapId': 0, 'name': '模板'},
            {'mindmapId': 1, 'name': ' '},
            {'mindmapId': 1, 'name': '模' * (MAX_TEMPLATE_NAME_LENGTH + 1)},
            {'mindmapId': 1, 'name': '模板\n注入'},
            {'mindmapId': 1, 'name': '模板', 'coverImage': 'javascript:alert(1)'},
            {'mindmapId': 1, 'name': '模板', 'coverImage': 'https://user:secret@example.com/a.png'},
            {'mindmapId': 1, 'name': '模板', 'templateCategoryId': 0},
        )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                MindmapTemplatePublishModel(**value)

    def test_query_model_trims_keyword_and_limits_pagination(self) -> None:
        query = MindmapTemplateQueryModel(keyword='  复盘  ', pageNum=2, pageSize=100)
        self.assertEqual(query.keyword, '复盘')
        with self.assertRaises(ValidationError):
            MindmapTemplateQueryModel(pageNum=0)
        with self.assertRaises(ValidationError):
            MindmapTemplateQueryModel(pageSize=101)


class MindmapTemplateServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_use_template_returns_created_mindmap_id(self) -> None:
        tree = {'data': {'uid': 'root', 'text': '模板'}, 'children': []}
        template = SimpleNamespace(
            name='项目复盘',
            description='模板描述',
            layout='logicalStructure',
            theme=None,
            node_tree=tree,
            view_data=None,
            document_data={'simpleMindMap': {'config': {'imgTextMargin': 9}}},
        )
        created = CrudResponseModel(
            is_success=True,
            message='新增成功',
            result={'id': 88},
        )
        create_mindmap = AsyncMock(return_value=created)
        with (
            patch.object(
                MindmapTemplateDao,
                'get_template_by_id',
                new=AsyncMock(return_value=template),
            ),
            patch.object(
                MindmapTagPortabilityService,
                'prepare_tree_for_owner',
                new=AsyncMock(return_value=tree),
            ),
            patch.object(
                MindmapService,
                'add_mindmap_services',
                new=create_mindmap,
            ),
        ):
            result = await MindmapTemplateService.use_template(
                None,
                template_id=12,
                user_id=7,
                user_name='tester',
                creation_request_id='request-key-1234567890',
            )

        self.assertEqual(result.result, {'id': 88})
        created_model = create_mindmap.await_args.args[1]
        self.assertEqual(created_model.document_data['simpleMindMap']['config']['imgTextMargin'], 9)
        self.assertEqual(
            create_mindmap.await_args.kwargs,
            {
                'creation_request_id': 'request-key-1234567890',
                'creation_operation': 'template',
                'creation_intent': {'templateId': 12},
            },
        )

    async def test_publish_rejects_missing_category_before_copying_document(self) -> None:
        source = SimpleNamespace(id=3)
        with (
            patch.object(
                MindmapTemplateDao,
                'get_category_by_id',
                new=AsyncMock(return_value=None),
            ),
            patch(
                'module_mindmap.service.mindmap_template_service.MindmapDao.get_mindmap_by_id',
                new=AsyncMock(return_value=source),
            ),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapTemplateService.publish_template(
                None,
                MindmapTemplatePublishModel(
                    mindmapId=3,
                    name='模板',
                    templateCategoryId=99,
                ),
                user_name='admin',
            )

        self.assertIn('分类不存在', context.exception.message)

    async def test_publish_returns_created_template_id(self) -> None:
        tree = {'data': {'uid': 'root', 'text': '源脑图'}, 'children': []}
        source = SimpleNamespace(
            id=3,
            schema_version=1,
            node_tree=tree,
            layout='logicalStructure',
            theme=None,
            view_data=None,
            document_data={'simpleMindMap': {'config': {'textContentMargin': 4}}},
        )
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        publish_template = AsyncMock(return_value=SimpleNamespace(id=73))
        with (
            patch(
                'module_mindmap.service.mindmap_template_service.MindmapDao.get_mindmap_by_id',
                new=AsyncMock(return_value=source),
            ),
            patch.object(
                MindmapTagPortabilityService,
                'prepare_tree_for_owner',
                new=AsyncMock(return_value=tree),
            ),
            patch.object(
                MindmapTemplateDao,
                'publish_template',
                new=publish_template,
            ),
        ):
            result = await MindmapTemplateService.publish_template(
                db,
                MindmapTemplatePublishModel(mindmapId=3, name='项目模板'),
                user_name='admin',
            )

        self.assertEqual(result.result, {'id': 73})
        published = publish_template.await_args.args[1]
        self.assertEqual(published['document_data']['simpleMindMap']['config']['textContentMargin'], 4)
        db.commit.assert_awaited_once()

    async def test_add_category_normalizes_and_rejects_duplicates(self) -> None:
        with (
            patch.object(
                MindmapTemplateDao,
                'get_category_by_name',
                new=AsyncMock(return_value=SimpleNamespace(id=1)),
            ),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapTemplateService.add_category(None, '  项目管理  ')

        self.assertIn('已存在', context.exception.message)

    async def test_add_category_translates_concurrent_unique_conflict(self) -> None:
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        with (
            patch.object(
                MindmapTemplateDao,
                'get_category_by_name',
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                MindmapTemplateDao,
                'add_category',
                new=AsyncMock(side_effect=IntegrityError('insert', {}, Exception('duplicate'))),
            ),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapTemplateService.add_category(db, '项目管理')

        self.assertIn('已存在', context.exception.message)
        db.rollback.assert_awaited_once()

    async def test_delete_category_rejects_active_template_references(self) -> None:
        delete_category = AsyncMock()
        with (
            patch.object(
                MindmapTemplateDao,
                'get_category_by_id',
                new=AsyncMock(return_value=SimpleNamespace(id=5)),
            ),
            patch.object(
                MindmapTemplateDao,
                'count_templates_in_category',
                new=AsyncMock(return_value=2),
            ),
            patch.object(MindmapTemplateDao, 'delete_category', new=delete_category),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapTemplateService.delete_category(None, 5)

        self.assertIn('仍有 2 个模板', context.exception.message)
        delete_category.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
