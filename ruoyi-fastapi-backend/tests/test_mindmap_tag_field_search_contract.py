"""标签字段和选项搜索的输入、SQL 与 OpenAPI 契约。"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pydantic import ValidationError

from module_mindmap.dao.mindmap_tag_field_dao import MindmapTagFieldDao
from module_mindmap.entity.vo.mindmap_tag_field_vo import TagFieldSuggestionQueryModel
from module_mindmap.entity.vo.mindmap_tag_vo import MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH
from server import create_app


class MindmapTagFieldSearchModelTest(unittest.TestCase):
    def test_keyword_is_trimmed_and_blank_disables_filtering(self) -> None:
        self.assertEqual(TagFieldSuggestionQueryModel(keyword='  优先级  ').keyword, '优先级')
        self.assertIsNone(TagFieldSuggestionQueryModel(keyword='   ').keyword)

    def test_keyword_rejects_controls_and_oversized_values(self) -> None:
        with self.assertRaises(ValidationError):
            TagFieldSuggestionQueryModel(keyword='优先\n级')
        with self.assertRaises(ValidationError):
            TagFieldSuggestionQueryModel(
                keyword='标' * (MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH + 1),
            )


class MindmapTagFieldSearchSqlTest(unittest.IsolatedAsyncioTestCase):
    async def test_field_and_option_search_use_explicit_literal_escape(self) -> None:
        field = SimpleNamespace(id=7, name='优先级', field_key='priority')
        field_result = SimpleNamespace(scalars=lambda: [field])
        option_result = SimpleNamespace(scalars=list)
        db = SimpleNamespace(execute=AsyncMock(side_effect=[field_result, option_result]))

        await MindmapTagFieldDao.get_suggestions(db, user_id=42, keyword='%_\\')

        statement = db.execute.await_args_list[0].args[0]
        sql = str(statement.compile(compile_kwargs={'literal_binds': True}))
        self.assertEqual(sql.count("ESCAPE '\\'"), 4)
        self.assertIn(r'%\%\_\\%', sql)


class MindmapTagFieldSearchOpenApiTest(unittest.TestCase):
    def test_suggestions_publish_the_shared_keyword_boundary(self) -> None:
        schema = create_app().openapi()
        parameters = schema['paths']['/mindmap/tag-field/suggestions']['get']['parameters']
        keyword_schema = next(item['schema'] for item in parameters if item['name'] == 'keyword')
        string_schema = next(item for item in keyword_schema['anyOf'] if item.get('type') == 'string')

        self.assertEqual(
            string_schema['maxLength'],
            MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH,
        )
        self.assertEqual(string_schema['pattern'], r'^[^\x00-\x1f\x7f]*$')


if __name__ == '__main__':
    unittest.main()
