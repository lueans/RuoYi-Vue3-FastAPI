"""标签、字段和选项定义的规范化输入契约。"""

import unittest

from pydantic import ValidationError

from module_mindmap.entity.vo.mindmap_tag_field_vo import TagFieldModel, TagFieldOptionModel
from module_mindmap.entity.vo.mindmap_tag_vo import MindmapTagModel


class MindmapTagDefinitionModelTest(unittest.TestCase):
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

    def test_field_definition_uses_the_same_display_and_description_contract(self) -> None:
        model = TagFieldModel(
            fieldKey=' priority ',
            name=' 优先级 ',
            description='  用于\n任务排序  ',
        )

        self.assertEqual(model.field_key, 'priority')
        self.assertEqual(model.name, '优先级')
        self.assertEqual(model.description, '用于\n任务排序')

        for name in ('   ', '优先\n级'):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                TagFieldModel(fieldKey='priority', name=name)

    def test_option_definition_trims_key_and_rejects_invalid_names(self) -> None:
        model = TagFieldOptionModel(fieldId=7, optionKey=' p0 ', name=' 最高优先级 ')
        self.assertEqual(model.option_key, 'p0')
        self.assertEqual(model.name, '最高优先级')

        for name in ('   ', '最高\t优先级'):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                TagFieldOptionModel(fieldId=7, optionKey='p0', name=name)

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

    def test_field_style_and_option_colors_share_the_style_contract(self) -> None:
        field = TagFieldModel(
            fieldKey='priority',
            name='优先级',
            style={
                'fontSize': 24,
                'radius': 0,
                'paddingX': 30,
                'placement': 'bottom',
                'align': 'left',
            },
        )
        option = TagFieldOptionModel(
            fieldId=7,
            optionKey='p0',
            name='最高优先级',
            fill='rgb(255, 0, 0)',
            color='transparent',
        )

        self.assertEqual(field.style['placement'], 'bottom')
        self.assertEqual(option.fill, '#ff0000')
        self.assertEqual(option.color, 'transparent')

        for payload in (
            {'style': {'fill': '#fff'}},
            {'style': {'radius': 21}},
            {'style': {'placement': 'left', 'align': 'left'}},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                TagFieldModel(fieldKey='priority', name='优先级', **payload)
        with self.assertRaises(ValidationError):
            TagFieldOptionModel(
                fieldId=7,
                optionKey='p0',
                name='最高优先级',
                fill='currentColor',
            )


if __name__ == '__main__':
    unittest.main()
