"""统一标签定义的规范化输入契约。"""

import unittest

from pydantic import ValidationError

from module_mindmap.entity.vo.mindmap_tag_vo import MindmapTagModel, MindmapTagSuggestionModel


class MindmapTagDefinitionModelTest(unittest.TestCase):
    def test_tag_suggestion_exposes_group_and_runtime_definition_fields(self) -> None:
        suggestion = MindmapTagSuggestionModel(
            id=1,
            name='风险',
            categoryId=9,
            status=0,
            definitionRevision=3,
        )

        self.assertEqual(suggestion.category_id, 9)
        self.assertEqual(
            suggestion.model_dump(by_alias=True, exclude_none=True),
            {
                'id': 1,
                'name': '风险',
                'categoryId': 9,
                'status': 0,
                'definitionRevision': 3,
            },
        )

    def test_tag_definition_trims_key_name_and_description(self) -> None:
        model = MindmapTagModel(
            tagKey=' risk_level ',
            name=' 风险等级 ',
            description='  第一行\n第二行  ',
        )

        self.assertEqual(model.tag_key, 'risk_level')
        self.assertEqual(model.name, '风险等级')
        self.assertEqual(model.description, '第一行\n第二行')
        self.assertIsNone(MindmapTagModel(tagKey='risk', name='风险', description='  ').description)

    def test_tag_definition_rejects_blank_or_control_character_names(self) -> None:
        for name in ('   ', '风险\n等级', '风险\x7f等级'):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                MindmapTagModel(tagKey='risk', name=name)

        with self.assertRaises(ValidationError):
            MindmapTagModel(tagKey='risk', name='风险', description='不可见\x00说明')
        with self.assertRaises(ValidationError):
            MindmapTagModel(tagKey='risk', name='风险', status=3)

    def test_tag_style_normalizes_colors_and_keeps_bounded_engine_fields(self) -> None:
        model = MindmapTagModel(
            tagKey='risk',
            name='风险',
            style={
                'fill': ' RGBA(255, 0, 16, 0.5) ',
                'color': '#ABC',
                'fontSize': 12.0,
                'radius': 3.5,
                'paddingX': 8,
                'placement': 'right',
                'align': 'center',
            },
        )

        self.assertEqual(model.style, {
            'fill': '#ff001080',
            'color': '#abc',
            'fontSize': 12,
            'radius': 3.5,
            'paddingX': 8,
            'placement': 'right',
            'align': 'center',
        })

    def test_tag_style_rejects_unknown_unsafe_or_out_of_range_values(self) -> None:
        invalid_styles = (
            {'width': 100},
            {'fill': 'url(https://example.test/pixel)'},
            {'fill': 'rgb(999, 0, 0)'},
            {'fontSize': 9},
            {'fontSize': True},
            {'paddingX': float('inf')},
            {'placement': 'near'},
            {'placement': 'top', 'align': 'top'},
        )
        for style in invalid_styles:
            with self.subTest(style=style), self.assertRaises(ValidationError):
                MindmapTagModel(tagKey='risk', name='风险', style=style)

if __name__ == '__main__':
    unittest.main()
