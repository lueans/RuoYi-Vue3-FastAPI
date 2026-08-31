"""Yjs 多来源持久化状态包测试。"""

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from sqlalchemy.exc import IntegrityError

from module_mindmap.websocket.yjs_doc import (
    STATE_BUNDLE_MAGIC,
    YjsDocManager,
    merge_yjs_state_bundle,
    normalize_yjs_state_source_changes,
    normalize_yjs_state_source_ids,
    pack_yjs_state_bundle,
    unpack_yjs_state_bundle,
)


class MindmapYjsStateBundleTest(unittest.TestCase):
    def test_legacy_single_state_remains_readable(self) -> None:
        self.assertEqual(unpack_yjs_state_bundle(b'legacy-update'), {'legacy': b'legacy-update'})

    def test_divergent_sources_are_preserved(self) -> None:
        bundle = merge_yjs_state_bundle(None, 'client-a', b'state-a')
        bundle = merge_yjs_state_bundle(bundle, 'client-b', b'state-b')

        self.assertEqual(
            unpack_yjs_state_bundle(bundle),
            {'client-a': b'state-a', 'client-b': b'state-b'},
        )

    def test_identical_complete_states_are_collapsed(self) -> None:
        bundle = pack_yjs_state_bundle({'client-a': b'same'})
        bundle = merge_yjs_state_bundle(bundle, 'client-b', b'same')

        self.assertEqual(unpack_yjs_state_bundle(bundle), {'client-b': b'same'})

    def test_consolidated_state_replaces_only_proven_sources(self) -> None:
        bundle = pack_yjs_state_bundle({
            'loaded-a': b'state-a',
            'loaded-b': b'state-b',
            'concurrent-c': b'state-c',
        })

        compacted = merge_yjs_state_bundle(
            bundle,
            'consolidated-d',
            b'merged-a-b',
            ['loaded-a', 'loaded-b'],
        )

        self.assertEqual(unpack_yjs_state_bundle(compacted), {
            'concurrent-c': b'state-c',
            'consolidated-d': b'merged-a-b',
        })

    def test_repeated_full_state_consolidation_remains_bounded(self) -> None:
        bundle = pack_yjs_state_bundle({'seed': b'state-0'})
        for index in range(1, 80):
            previous_sources = list(unpack_yjs_state_bundle(bundle))
            bundle = merge_yjs_state_bundle(
                bundle,
                f'client-{index}',
                f'state-{index}'.encode(),
                replace_source_ids=previous_sources,
            )

        self.assertEqual(
            unpack_yjs_state_bundle(bundle),
            {'client-79': b'state-79'},
        )

    def test_replacement_source_list_is_bounded_unique_and_strict(self) -> None:
        self.assertEqual(
            normalize_yjs_state_source_ids([' source-a ', 'source-b']),
            ['source-a', 'source-b'],
        )
        self.assertIsNone(normalize_yjs_state_source_ids(['duplicate', 'duplicate']))
        self.assertIsNone(normalize_yjs_state_source_ids([7]))

    def test_merged_and_invalid_sources_form_one_disjoint_bounded_replacement(self) -> None:
        self.assertEqual(
            normalize_yjs_state_source_changes(
                ['merged-a', 'merged-b'],
                ['invalid-c'],
            ),
            (
                ['merged-a', 'merged-b'],
                ['invalid-c'],
                ['merged-a', 'merged-b', 'invalid-c'],
            ),
        )
        self.assertIsNone(normalize_yjs_state_source_changes(
            ['same-source'],
            ['same-source'],
        ))
        self.assertIsNone(normalize_yjs_state_source_changes(
            [f'merged-{index}' for index in range(32)],
            ['invalid-overflow'],
        ))

    def test_corrupted_bundle_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, '格式损坏|不完整'):
            unpack_yjs_state_bundle(STATE_BUNDLE_MAGIC + b'\x00\x01\x00')

class MindmapYjsStatePersistenceTest(unittest.IsolatedAsyncioTestCase):
    async def test_first_writer_insert_race_retries_and_merges_winner_state(self) -> None:
        winner_bundle = pack_yjs_state_bundle({'winner': b'winner-state'})
        winner_row = SimpleNamespace(yjs_state=winner_bundle, content_revision=5)

        def result(value: Any) -> SimpleNamespace:
            return SimpleNamespace(scalar_one_or_none=lambda: value)

        db = SimpleNamespace(
            execute=AsyncMock(side_effect=[
                result(None),
                result(5),
                result(winner_row),
                result(5),
                result(None),
            ]),
            add=lambda _row: None,
            commit=AsyncMock(side_effect=[IntegrityError('insert', {}, Exception()), None]),
            rollback=AsyncMock(),
        )

        saved = await YjsDocManager.save_state(
            db, 9, b'loser-state', content_revision=5, source_id='loser',
        )

        self.assertTrue(saved)
        db.rollback.assert_awaited_once()
        self.assertEqual(db.commit.await_count, 2)
        revision_query = db.execute.await_args_list[1].args[0]
        self.assertIn('mindmap.del_flag', str(revision_query))

    async def test_save_state_compacts_acknowledged_sources_and_keeps_concurrent_state(self) -> None:
        existing = SimpleNamespace(
            yjs_state=pack_yjs_state_bundle({
                'loaded-a': b'state-a',
                'concurrent-b': b'state-b',
            }),
            content_revision=8,
        )

        def result(value: Any) -> SimpleNamespace:
            return SimpleNamespace(scalar_one_or_none=lambda: value)

        db = SimpleNamespace(
            execute=AsyncMock(side_effect=[result(existing), result(8), result(None)]),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )

        saved = await YjsDocManager.save_state(
            db,
            9,
            b'merged-state',
            content_revision=8,
            source_id='consolidated-c',
            replace_source_ids=['loaded-a'],
        )

        self.assertTrue(saved)
        update_statement = db.execute.await_args_list[2].args[0]
        stored_bundle = update_statement.compile().params['yjs_state']
        self.assertEqual(unpack_yjs_state_bundle(stored_bundle), {
            'concurrent-b': b'state-b',
            'consolidated-c': b'merged-state',
        })


if __name__ == '__main__':
    unittest.main()
