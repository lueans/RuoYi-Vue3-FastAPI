"""脑图标签跨所有者携带规则测试。"""
import unittest
from types import SimpleNamespace

from module_mindmap.service.mindmap_tag_portability import (
    MindmapTagPortabilityService,
    strip_managed_tag_identity,
)


class MindmapTagPortabilityTest(unittest.TestCase):
    def test_detach_preserves_snapshot_and_local_layout(self) -> None:
        detached = strip_managed_tag_identity({
            'tagId': 9,
            'uuid': 'secret',
            'tagKey': 'private_key',
            'fieldId': 3,
            'optionId': 4,
            'text': '私有标签',
            'style': {'fill': '#123456'},
            'placement': 'right',
            'align': 'center',
        })

        self.assertEqual(detached, {
            'text': '私有标签',
            'style': {'fill': '#123456'},
            'placement': 'right',
            'align': 'center',
        })

    def test_missing_definition_gets_migration_label(self) -> None:
        detached = strip_managed_tag_identity({'tagId': 999})
        self.assertEqual(detached['text'], '迁移待整理')

    def test_only_active_visible_reference_is_portable(self) -> None:
        raw = {'tagId': 7}
        self.assertTrue(MindmapTagPortabilityService._is_reference_portable(
            raw,
            SimpleNamespace(owner_id=0, status=0),
            None,
            target_owner_id=42,
        ))
        self.assertFalse(MindmapTagPortabilityService._is_reference_portable(
            raw,
            SimpleNamespace(owner_id=7, status=0),
            None,
            target_owner_id=42,
        ))
        self.assertFalse(MindmapTagPortabilityService._is_reference_portable(
            raw,
            SimpleNamespace(owner_id=0, status=1),
            None,
            target_owner_id=42,
        ))
        self.assertTrue(MindmapTagPortabilityService._is_reference_portable(
            raw,
            SimpleNamespace(owner_id=0, status=1),
            None,
            target_owner_id=42,
            allow_disabled_references=True,
        ))

    def test_detached_field_tag_keeps_resolved_inherited_style(self) -> None:
        name, style = MindmapTagPortabilityService._fallback_definition(
            SimpleNamespace(name='高优先级', style={'fill': '#f00'}),
            (
                SimpleNamespace(fill='#f00', color=None),
                SimpleNamespace(style={'fontSize': 14, 'radius': 6}),
            ),
        )

        self.assertEqual(name, '高优先级')
        self.assertEqual(style, {'fontSize': 14, 'radius': 6, 'fill': '#f00'})


if __name__ == '__main__':
    unittest.main()
