"""脑图标签跨所有者携带规则测试。"""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

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
            'categoryId': 6,
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
            target_owner_id=42,
        ))
        self.assertFalse(MindmapTagPortabilityService._is_reference_portable(
            raw,
            SimpleNamespace(owner_id=7, status=0),
            target_owner_id=42,
        ))
        self.assertFalse(MindmapTagPortabilityService._is_reference_portable(
            raw,
            SimpleNamespace(owner_id=0, status=1),
            target_owner_id=42,
        ))
        self.assertTrue(MindmapTagPortabilityService._is_reference_portable(
            raw,
            SimpleNamespace(owner_id=0, status=1),
            target_owner_id=42,
            allow_disabled_references=True,
        ))

    def test_detached_tag_keeps_unified_style(self) -> None:
        name, style = MindmapTagPortabilityService._fallback_definition(
            SimpleNamespace(name='高优先级', style={'fontSize': 14, 'radius': 6, 'fill': '#f00'}),
        )

        self.assertEqual(name, '高优先级')
        self.assertEqual(style, {'fontSize': 14, 'radius': 6, 'fill': '#f00'})


class MindmapTagPortabilityConcurrencyTest(unittest.IsolatedAsyncioTestCase):
    async def test_restore_mode_uses_a_locking_current_read_for_tag_identity(self) -> None:
        current_tag = SimpleNamespace(
            id=7,
            uuid='global-tag',
            owner_id=0,
            status=0,
        )
        result = MagicMock()
        result.scalars.return_value = [current_tag]
        db = AsyncMock()
        db.execute.return_value = result
        historical_tree = {
            'data': {
                'uid': 'root',
                'tag': [{
                    'tagId': 7,
                    'uuid': 'global-tag',
                    'status': 2,
                    'text': '历史标签',
                }],
            },
            'children': [],
        }

        restored_tree = await MindmapTagPortabilityService.prepare_tree_for_owner(
            db,
            historical_tree,
            target_owner_id=42,
            allow_disabled_references=True,
            for_update=True,
        )

        query = db.execute.await_args.args[0]
        self.assertIsNotNone(query._for_update_arg)
        self.assertTrue(query.get_execution_options()['populate_existing'])
        self.assertIn('ORDER BY mindmap_tag.id ASC', str(query))
        self.assertEqual(restored_tree['data']['tag'][0]['tagId'], 7)


if __name__ == '__main__':
    unittest.main()
