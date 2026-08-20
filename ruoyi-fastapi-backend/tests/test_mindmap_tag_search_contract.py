"""统一标签列表与建议搜索的输入和 SQL 字面量契约。"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from common.vo import PageModel
from module_mindmap.dao.mindmap_tag_dao import MindmapTagDao
from module_mindmap.entity.vo.mindmap_tag_vo import (
    MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH,
    MindmapTagQueryModel,
    MindmapTagSuggestionQueryModel,
)
from server import create_app


class MindmapTagSearchModelTest(unittest.TestCase):
    def test_keywords_are_trimmed_and_blank_values_disable_filtering(self) -> None:
        self.assertEqual(MindmapTagQueryModel(keyword='  风险等级  ').keyword, '风险等级')
        self.assertIsNone(MindmapTagQueryModel(keyword='   ').keyword)
        self.assertEqual(MindmapTagSuggestionQueryModel(keyword='  P0  ').keyword, 'P0')

    def test_keywords_reject_controls_and_oversized_values(self) -> None:
        for model_type in (MindmapTagQueryModel, MindmapTagSuggestionQueryModel):
            with self.subTest(model=model_type.__name__), self.assertRaises(ValidationError):
                model_type(keyword='风险\n等级')
            with self.subTest(model=model_type.__name__), self.assertRaises(ValidationError):
                model_type(keyword='标' * (MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH + 1))


class MindmapTagSearchSqlTest(unittest.IsolatedAsyncioTestCase):
    async def test_governance_search_uses_explicit_escape_on_all_text_fields(self) -> None:
        page = PageModel(rows=[], pageNum=1, pageSize=20, total=0, hasNext=False)
        with patch(
            'module_mindmap.dao.mindmap_tag_dao.PageUtil.paginate',
            new=AsyncMock(return_value=page),
        ) as paginate_mock:
            await MindmapTagDao.get_tag_list(
                SimpleNamespace(),
                user_id=42,
                keyword='%_\\',
            )

        statement = paginate_mock.await_args.args[1]
        sql = str(statement.compile(compile_kwargs={'literal_binds': True}))
        self.assertEqual(sql.count("ESCAPE '\\'"), 3)
        self.assertIn(r'%\%\_\\%', sql)

    async def test_suggestions_use_explicit_escape_on_name_and_key(self) -> None:
        result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=list))
        db = SimpleNamespace(execute=AsyncMock(return_value=result))

        await MindmapTagDao.get_suggestions(db, user_id=42, keyword='%_\\')

        statement = db.execute.await_args.args[0]
        sql = str(statement.compile(compile_kwargs={'literal_binds': True}))
        self.assertEqual(sql.count("ESCAPE '\\'"), 2)
        self.assertIn(r'%\%\_\\%', sql)


class MindmapTagSearchOpenApiTest(unittest.TestCase):
    def test_list_and_suggestions_publish_the_same_keyword_boundary(self) -> None:
        schema = create_app().openapi()
        for path in ('/mindmap/tag/list', '/mindmap/tag/suggestions'):
            with self.subTest(path=path):
                parameters = schema['paths'][path]['get']['parameters']
                keyword_schema = next(item['schema'] for item in parameters if item['name'] == 'keyword')
                string_schema = next(
                    item for item in keyword_schema['anyOf'] if item.get('type') == 'string'
                )
                self.assertEqual(
                    string_schema['maxLength'],
                    MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH,
                )
                self.assertEqual(string_schema['pattern'], r'^[^\x00-\x1f\x7f]*$')


if __name__ == '__main__':
    unittest.main()
