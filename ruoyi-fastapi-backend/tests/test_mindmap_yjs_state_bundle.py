"""Yjs 多来源持久化状态包测试。"""

import struct
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from sqlalchemy.exc import IntegrityError

from module_mindmap.websocket.yjs_doc import (
    DRAFT_STATE_BUNDLE_MAGIC,
    LINEAGE_SOURCE_ID_PREFIX,
    STATE_BUNDLE_MAGIC,
    YjsDocManager,
    get_yjs_lineage_digest,
    get_yjs_state_digest,
    merge_yjs_state_bundle,
    normalize_yjs_state_source_changes,
    normalize_yjs_state_source_ids,
    pack_yjs_state_bundle,
    unpack_yjs_state_bundle,
    unpack_yjs_state_bundle_with_lineages,
)


def unpack_as_old_mmys2_worker(blob: bytes) -> dict[str, bytes]:
    """模拟尚未认识 lineage 编码、只理解 MMYS2 的旧 worker。"""
    if not blob.startswith(STATE_BUNDLE_MAGIC):
        return {'legacy': blob}
    offset = len(STATE_BUNDLE_MAGIC)
    (count,) = struct.unpack_from('>H', blob, offset)
    offset += 2
    states = {}
    for _ in range(count):
        (key_length,) = struct.unpack_from('>H', blob, offset)
        offset += 2
        source_id = blob[offset:offset + key_length].decode('utf-8')
        offset += key_length
        (state_length,) = struct.unpack_from('>I', blob, offset)
        offset += 4
        states[source_id] = blob[offset:offset + state_length]
        offset += state_length
    if offset != len(blob):
        raise ValueError('old MMYS2 parser found trailing bytes')
    return states


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

    def test_lineage_metadata_keeps_the_mmys2_wire_layout(self) -> None:
        lineage_digest = get_yjs_lineage_digest('lineage-a')

        bundle = pack_yjs_state_bundle(
            {'client-a': b'state-a'},
            {'client-a': lineage_digest},
        )

        self.assertTrue(bundle.startswith(STATE_BUNDLE_MAGIC))
        self.assertFalse(bundle.startswith(DRAFT_STATE_BUNDLE_MAGIC))
        old_worker_states = unpack_as_old_mmys2_worker(bundle)
        self.assertEqual(list(old_worker_states.values()), [b'state-a'])
        physical_source_id = next(iter(old_worker_states))
        self.assertTrue(physical_source_id.startswith(
            f'{LINEAGE_SOURCE_ID_PREFIX}{lineage_digest}:',
        ))
        states, lineages = unpack_yjs_state_bundle_with_lineages(bundle)
        self.assertEqual(states, {'client-a': b'state-a'})
        self.assertEqual(lineages, {'client-a': lineage_digest})

    def test_draft_mmys3_bundle_is_read_and_rewritten_as_mmys2(self) -> None:
        source_id = b'draft-client'
        lineage_id = b'draft-lineage'
        state = b'draft-state'
        draft_bundle = b''.join((
            DRAFT_STATE_BUNDLE_MAGIC,
            struct.pack('>H', 1),
            struct.pack('>H', len(source_id)),
            source_id,
            struct.pack('>H', len(lineage_id)),
            lineage_id,
            struct.pack('>I', len(state)),
            state,
        ))

        states, lineages = unpack_yjs_state_bundle_with_lineages(draft_bundle)
        self.assertEqual(states, {'draft-client': state})
        self.assertEqual(
            lineages,
            {'draft-client': get_yjs_lineage_digest('draft-lineage')},
        )
        rewritten = pack_yjs_state_bundle(states, lineages)
        self.assertTrue(rewritten.startswith(STATE_BUNDLE_MAGIC))
        self.assertEqual(
            unpack_as_old_mmys2_worker(rewritten).popitem()[1],
            state,
        )

    def test_reserved_source_id_remains_opaque_to_public_api_and_cas(self) -> None:
        source_id = f'{LINEAGE_SOURCE_ID_PREFIX}{"a" * 64}:user-source'
        bundle = pack_yjs_state_bundle({source_id: b'old-state'})
        self.assertEqual(unpack_yjs_state_bundle(bundle), {source_id: b'old-state'})

        compacted = merge_yjs_state_bundle(
            bundle,
            'new-source',
            b'new-state',
            replace_source_ids=[source_id],
            replace_source_digests={source_id: get_yjs_state_digest(b'old-state')},
        )

        self.assertEqual(
            unpack_yjs_state_bundle(compacted),
            {'new-source': b'new-state'},
        )

    def test_same_lineage_sources_can_merge_without_replacement(self) -> None:
        bundle = merge_yjs_state_bundle(
            None,
            'client-a',
            b'state-a',
            source_lineage_id='shared-lineage',
        )

        bundle = merge_yjs_state_bundle(
            bundle,
            'client-b',
            b'state-b',
            source_lineage_id='shared-lineage',
        )

        states, lineages = unpack_yjs_state_bundle_with_lineages(bundle)
        lineage_digest = get_yjs_lineage_digest('shared-lineage')
        self.assertEqual(states, {
            'client-a': b'state-a',
            'client-b': b'state-b',
        })
        self.assertEqual(lineages, {
            'client-a': lineage_digest,
            'client-b': lineage_digest,
        })

    def test_different_lineage_is_rejected_without_complete_cas_replacement(self) -> None:
        bundle = merge_yjs_state_bundle(
            None,
            'client-a',
            b'state-a',
            source_lineage_id='lineage-a',
        )

        with self.assertRaisesRegex(ValueError, 'lineage'):
            merge_yjs_state_bundle(
                bundle,
                'client-b',
                b'state-b',
                source_lineage_id='lineage-b',
            )

    def test_different_lineage_can_atomically_replace_all_mismatched_sources(self) -> None:
        bundle = merge_yjs_state_bundle(
            None,
            'client-a',
            b'state-a',
            source_lineage_id='lineage-a',
        )

        bundle = merge_yjs_state_bundle(
            bundle,
            'client-b',
            b'state-b',
            replace_source_ids=['client-a'],
            replace_source_digests={
                'client-a': get_yjs_state_digest(b'state-a'),
            },
            source_lineage_id='lineage-b',
        )

        states, lineages = unpack_yjs_state_bundle_with_lineages(bundle)
        self.assertEqual(states, {'client-b': b'state-b'})
        self.assertEqual(
            lineages,
            {'client-b': get_yjs_lineage_digest('lineage-b')},
        )

    def test_partial_cas_replacement_cannot_switch_lineage(self) -> None:
        lineage_digest = get_yjs_lineage_digest('lineage-a')
        bundle = pack_yjs_state_bundle(
            {'client-a': b'state-a', 'client-b': b'state-b'},
            {'client-a': lineage_digest, 'client-b': lineage_digest},
        )

        with self.assertRaisesRegex(ValueError, 'lineage'):
            merge_yjs_state_bundle(
                bundle,
                'client-c',
                b'state-c',
                replace_source_ids=['client-a'],
                replace_source_digests={
                    'client-a': get_yjs_state_digest(b'state-a'),
                },
                source_lineage_id='lineage-b',
            )

    def test_lineage_switch_also_replaces_concurrent_unknown_legacy_source(self) -> None:
        lineage_digest = get_yjs_lineage_digest('lineage-a')
        bundle = pack_yjs_state_bundle(
            {'known-a': b'state-a', 'legacy-b': b'legacy-state'},
            {'known-a': lineage_digest},
        )

        with self.assertRaisesRegex(ValueError, 'lineage'):
            merge_yjs_state_bundle(
                bundle,
                'new-lineage-source',
                b'new-state',
                replace_source_ids=['known-a'],
                replace_source_digests={
                    'known-a': get_yjs_state_digest(b'state-a'),
                },
                source_lineage_id='lineage-b',
            )

    def test_lineage_switch_rejects_a_source_changed_after_snapshot(self) -> None:
        bundle = merge_yjs_state_bundle(
            None,
            'client-a',
            b'newer-state',
            source_lineage_id='lineage-a',
        )

        with self.assertRaisesRegex(ValueError, '握手后变化'):
            merge_yjs_state_bundle(
                bundle,
                'client-b',
                b'state-b',
                replace_source_ids=['client-a'],
                replace_source_digests={
                    'client-a': get_yjs_state_digest(b'older-state'),
                },
                source_lineage_id='lineage-b',
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
    async def test_load_snapshot_returns_file_revision_with_matching_state_sources(self) -> None:
        bundle = pack_yjs_state_bundle({'writer-a': b'complete-state'})
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
            first=lambda: (12, bundle, 12),
        )))

        revision, states = await YjsDocManager.load_state_snapshot(db, 9)

        self.assertEqual(revision, 12)
        self.assertEqual(states, {'writer-a': b'complete-state'})
        statement = db.execute.await_args.args[0]
        self.assertIn('LEFT OUTER JOIN mindmap_ws_state', str(statement))
        self.assertIn('mindmap.del_flag', str(statement))

    async def test_load_snapshot_keeps_new_revision_but_rejects_old_checkpoint(self) -> None:
        bundle = pack_yjs_state_bundle({'writer-a': b'old-state'})
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
            first=lambda: (13, bundle, 12),
        )))

        revision, states = await YjsDocManager.load_state_snapshot(db, 9)

        self.assertEqual(revision, 13)
        self.assertEqual(states, {})

    async def test_load_snapshot_keeps_revision_when_state_bundle_is_corrupt(self) -> None:
        corrupt_bundle = STATE_BUNDLE_MAGIC + b'broken'
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
            first=lambda: (14, corrupt_bundle, 14),
        )))

        revision, states = await YjsDocManager.load_state_snapshot(db, 9)

        self.assertEqual(revision, 14)
        self.assertEqual(states, {})

    async def test_first_writer_insert_race_retries_and_merges_winner_state(self) -> None:
        winner_bundle = pack_yjs_state_bundle({'winner': b'winner-state'})
        winner_row = SimpleNamespace(yjs_state=winner_bundle, content_revision=5)

        def result(value: Any) -> SimpleNamespace:
            return SimpleNamespace(scalar_one_or_none=lambda: value)

        db = SimpleNamespace(
            execute=AsyncMock(side_effect=[
                result(5),
                result(None),
                result(5),
                result(winner_row),
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
        revision_query = db.execute.await_args_list[0].args[0]
        self.assertIn('mindmap.del_flag', str(revision_query))
        self.assertIsNotNone(revision_query._for_update_arg)
        checkpoint_query = db.execute.await_args_list[1].args[0]
        self.assertIn('mindmap_ws_state', str(checkpoint_query))
        self.assertIsNotNone(checkpoint_query._for_update_arg)

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
            execute=AsyncMock(side_effect=[result(8), result(existing), result(None)]),
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

    async def test_save_state_rejects_same_revision_lineage_switch_without_cas(self) -> None:
        existing = SimpleNamespace(
            yjs_state=merge_yjs_state_bundle(
                None,
                'writer-a',
                b'state-a',
                source_lineage_id='lineage-a',
            ),
            content_revision=8,
        )

        def result(value: Any) -> SimpleNamespace:
            return SimpleNamespace(scalar_one_or_none=lambda: value)

        db = SimpleNamespace(
            execute=AsyncMock(side_effect=[result(8), result(existing)]),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )

        saved = await YjsDocManager.save_state(
            db,
            9,
            b'state-b',
            content_revision=8,
            source_id='writer-b',
            lineage_id='lineage-b',
        )

        self.assertFalse(saved)
        db.rollback.assert_awaited_once()
        db.commit.assert_not_awaited()
        self.assertEqual(db.execute.await_count, 2)

    async def test_save_state_ignores_old_replacement_claims_on_new_revision(self) -> None:
        old_state = b'old-state'
        existing = SimpleNamespace(
            yjs_state=merge_yjs_state_bundle(
                None,
                'old-writer',
                old_state,
                source_lineage_id='old-lineage',
            ),
            content_revision=8,
        )

        def result(value: Any) -> SimpleNamespace:
            return SimpleNamespace(scalar_one_or_none=lambda: value)

        db = SimpleNamespace(
            execute=AsyncMock(side_effect=[result(9), result(existing), result(None)]),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )

        saved = await YjsDocManager.save_state(
            db,
            9,
            b'new-state',
            content_revision=9,
            source_id='new-writer',
            replace_source_ids=['old-writer'],
            replace_source_digests={
                'old-writer': get_yjs_state_digest(old_state),
            },
            lineage_id='new-lineage',
        )

        self.assertTrue(saved)
        update_statement = db.execute.await_args_list[2].args[0]
        stored_bundle = update_statement.compile().params['yjs_state']
        states, lineages = unpack_yjs_state_bundle_with_lineages(stored_bundle)
        self.assertEqual(states, {'new-writer': b'new-state'})
        self.assertEqual(
            lineages,
            {'new-writer': get_yjs_lineage_digest('new-lineage')},
        )
        db.commit.assert_awaited_once()
        db.rollback.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
