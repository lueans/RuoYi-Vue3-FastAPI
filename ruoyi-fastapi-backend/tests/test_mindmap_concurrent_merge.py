"""脑图节点级并发合并测试。"""
import unittest
from types import SimpleNamespace

from module_mindmap.service.mindmap_service import (
    analyze_concurrent_operations,
    get_operation_conflict_key,
    is_change_history_complete,
    merge_node_operations,
)


def _node(uid: str, text: str, children: list[dict] | None = None) -> dict:
    return {'data': {'uid': uid, 'text': text}, 'children': children or []}


def _texts_by_uid(root: dict) -> dict[str, str]:
    result = {}

    def walk(node: dict) -> None:
        result[node['data']['uid']] = node['data']['text']
        for child in node.get('children') or []:
            walk(child)

    walk(root)
    return result


def _update(
    uid: str,
    *,
    data_changed: bool = False,
    old_children: list[str] | None = None,
    children: list[str] | None = None,
) -> dict:
    return {
        'type': 'node.update',
        'nodeUid': uid,
        'payload': {
            'dataChanged': data_changed,
            'childrenChanged': old_children is not None or children is not None,
            'oldChildUids': old_children or [],
            'childUids': children or [],
        },
    }


def _relation_operation(target_uid: str, action: str = 'upsert') -> dict:
    return {
        'type': f'relation.{action}',
        'payload': {
            'key': f'assoc:root:{target_uid}',
            'relationUid': f'assoc:root:{target_uid}',
            'relationType': 'associative_line',
            'sourceUid': 'root',
            'targetUid': target_uid,
            'controlData': {},
            'sortOrder': 2,
        },
    }


def _tag_operation(tag_id: int, action: str = 'bind', node_uid: str = 'a') -> dict:
    return {
        'type': f'node.tag.{action}',
        'nodeUid': node_uid,
        'payload': {
            'key': f'{node_uid}:{tag_id}',
            'tagKey': str(tag_id),
            'tag': {'tagId': tag_id},
        },
    }


class MindmapConcurrentMergeTest(unittest.TestCase):
    def test_different_tag_bindings_on_same_node_are_mergeable(self) -> None:
        result = analyze_concurrent_operations(
            [_tag_operation(11)],
            [_tag_operation(12)],
            history_complete=True,
        )
        self.assertTrue(result['mergeable'])
        self.assertEqual(result['conflictEntities'], [])

    def test_same_tag_binding_conflicts_and_node_delete_protects_binding(self) -> None:
        same_binding = analyze_concurrent_operations(
            [_tag_operation(11)],
            [_tag_operation(11, 'unbind')],
            history_complete=True,
        )
        self.assertFalse(same_binding['mergeable'])
        self.assertEqual(same_binding['conflictEntities'], ['tag-binding:a:11'])

        deleted_node = analyze_concurrent_operations(
            [{'type': 'node.delete', 'nodeUid': 'a'}],
            [_tag_operation(11)],
            history_complete=True,
        )
        self.assertFalse(deleted_node['mergeable'])
        self.assertIn('a', deleted_node['conflictNodeUids'])

    def test_tag_bind_preserves_other_server_binding_and_text_update_preserves_tags(self) -> None:
        server = _node('root', 'root', [_node('a', 'server')])
        server['children'][0]['data']['tag'] = [{'tagId': 11, 'text': 'server tag'}]
        client = _node('root', 'root', [_node('a', 'client')])
        client['children'][0]['data']['tag'] = [{'tagId': 12, 'text': 'client tag'}]

        merged = merge_node_operations(server, client, [
            {
                'type': 'node.update',
                'nodeUid': 'a',
                'payload': {
                    'dataChanged': True,
                    'childrenChanged': False,
                    'tagBindingsSeparated': True,
                },
            },
            _tag_operation(12),
        ])

        self.assertEqual(merged['children'][0]['data']['text'], 'client')
        self.assertEqual(
            [tag['tagId'] for tag in merged['children'][0]['data']['tag']],
            [11, 12],
        )
        self.assertEqual(merged['children'][0]['data']['tag'][1]['text'], 'client tag')

    def test_tag_unbind_and_reorder_materialize_independently(self) -> None:
        tree = _node('root', 'root', [_node('a', 'a')])
        tree['children'][0]['data']['tag'] = [
            {'tagId': 11, 'placement': 'top'},
            {'tagId': 12},
            {'tagId': 13},
        ]
        merged = merge_node_operations(tree, tree, [
            _tag_operation(13, 'unbind'),
            {
                'type': 'node.tag.reorder',
                'nodeUid': 'a',
                'payload': {'key': 'a', 'tagKeys': ['12', '11']},
            },
        ])
        self.assertEqual(
            [tag['tagId'] for tag in merged['children'][0]['data']['tag']],
            [12, 11],
        )

    def test_tag_reorder_conflicts_with_binding_change_on_same_node(self) -> None:
        result = analyze_concurrent_operations(
            [{
                'type': 'node.tag.reorder',
                'nodeUid': 'a',
                'payload': {'key': 'a', 'tagKeys': ['12', '11']},
            }],
            [_tag_operation(13)],
            history_complete=True,
        )
        self.assertFalse(result['mergeable'])
        self.assertEqual(result['conflictNodeUids'], ['a'])

    def test_different_relations_on_same_source_are_mergeable(self) -> None:
        result = analyze_concurrent_operations(
            [_relation_operation('a')],
            [_relation_operation('b')],
            history_complete=True,
        )
        self.assertTrue(result['mergeable'])
        self.assertEqual(result['conflictNodeUids'], [])

    def test_same_relation_conflicts_and_node_delete_protects_references(self) -> None:
        same_relation = analyze_concurrent_operations(
            [_relation_operation('a')],
            [_relation_operation('a', 'delete')],
            history_complete=True,
        )
        self.assertFalse(same_relation['mergeable'])
        self.assertEqual(same_relation['conflictEntities'], ['relation:assoc:root:a'])

        deleted_source = analyze_concurrent_operations(
            [{'type': 'node.delete', 'nodeUid': 'root'}],
            [_relation_operation('a')],
            history_complete=True,
        )
        self.assertFalse(deleted_source['mergeable'])
        self.assertIn('root', deleted_source['conflictNodeUids'])

    def test_relation_upsert_preserves_concurrent_server_relations(self) -> None:
        server = _node('root', 'root', [_node('a', 'a'), _node('b', 'b'), _node('c', 'c')])
        server['data']['associativeLineTargets'] = ['a', 'b']
        client = _node('root', 'root', [_node('a', 'a'), _node('b', 'b'), _node('c', 'c')])
        client['data']['associativeLineTargets'] = ['a', 'c']

        merged = merge_node_operations(server, client, [_relation_operation('c')])

        self.assertEqual(merged['data']['associativeLineTargets'], ['a', 'b', 'c'])

    def test_relation_uid_is_bounded_for_uuid_nodes(self) -> None:
        source_uid = '11111111-1111-4111-8111-111111111111'
        target_uid = '22222222-2222-4222-8222-222222222222'
        tree = _node(source_uid, 'root', [_node(target_uid, 'target')])
        relation_uid = f'assoc:{source_uid}:{target_uid}'

        merged = merge_node_operations(tree, tree, [{
            'type': 'relation.upsert',
            'payload': {
                'key': relation_uid,
                'relationUid': relation_uid,
                'relationType': 'associative_line',
                'sourceUid': source_uid,
                'targetUid': target_uid,
            },
        }])

        self.assertEqual(merged['data']['associativeLineTargets'], [target_uid])

    def test_separated_text_update_preserves_server_relation_state(self) -> None:
        server = _node('root', 'server text', [_node('a', 'a'), _node('b', 'b')])
        server['data']['associativeLineTargets'] = ['b']
        client = _node('root', 'client text', [_node('a', 'a'), _node('b', 'b')])
        client['data']['associativeLineTargets'] = ['a']

        merged = merge_node_operations(server, client, [{
            'type': 'node.update',
            'nodeUid': 'root',
            'payload': {
                'dataChanged': True,
                'childrenChanged': False,
                'oldChildUids': ['a', 'b'],
                'childUids': ['a', 'b'],
                'crossNodeDataSeparated': True,
            },
        }])

        self.assertEqual(merged['data']['text'], 'client text')
        self.assertEqual(merged['data']['associativeLineTargets'], ['b'])

    def test_relation_delete_only_removes_requested_entity(self) -> None:
        tree = _node('root', 'root', [_node('a', 'a'), _node('b', 'b')])
        tree['data']['associativeLineTargets'] = ['a', 'b']

        merged = merge_node_operations(tree, tree, [_relation_operation('a', 'delete')])

        self.assertEqual(merged['data']['associativeLineTargets'], ['b'])

    def test_relation_delete_accepts_legacy_key_only_payload(self) -> None:
        tree = _node('root', 'root', [_node('a', 'a'), _node('b', 'b')])
        tree['data']['associativeLineTargets'] = ['a', 'b']

        merged = merge_node_operations(tree, tree, [{
            'type': 'relation.delete',
            'payload': {'key': 'assoc:root:a'},
        }])

        self.assertEqual(merged['data']['associativeLineTargets'], ['b'])

    def test_relation_delete_normalizes_long_key_only_payload(self) -> None:
        source_uid = 'source-' + ('s' * 57)
        target_uid = 'target-' + ('t' * 57)
        tree = _node(source_uid, 'root', [_node(target_uid, 'target')])
        tree['data']['associativeLineTargets'] = [target_uid]

        merged = merge_node_operations(tree, tree, [{
            'type': 'relation.delete',
            'payload': {'key': f'assoc:{source_uid}:{target_uid}'},
        }])

        self.assertEqual(merged['data'].get('associativeLineTargets'), None)

    def test_summary_group_and_asset_operations_materialize_independently(self) -> None:
        tree = _node('root', 'root', [_node('a', 'a'), _node('b', 'b')])
        operations = [
            {
                'type': 'summary.upsert',
                'payload': {
                    'key': 'root:summary-1',
                    'summaryUid': 'summary-1',
                    'ownerUid': 'root',
                    'startChildUid': 'a',
                    'endChildUid': 'b',
                    'payload': {'text': '概要'},
                    'sortOrder': 0,
                },
            },
            {
                'type': 'group.upsert',
                'payload': {
                    'key': 'group-1',
                    'groupUid': 'group-1',
                    'groupType': 'outer_frame',
                    'memberUids': ['a', 'b'],
                    'payload': {'lineColor': '#f00'},
                },
            },
            {
                'type': 'asset.upsert',
                'payload': {
                    'key': 'image-1',
                    'assetKey': 'image-1',
                    'uri': 'data:image/png;base64,AA==',
                },
            },
        ]

        merged = merge_node_operations(tree, tree, operations)

        self.assertEqual(merged['data']['generalization'][0]['uid'], 'summary-1')
        self.assertEqual(merged['data']['generalization'][0]['range'], [0, 1])
        self.assertEqual(merged['children'][0]['data']['outerFrame']['groupId'], 'group-1')
        self.assertEqual(merged['children'][1]['data']['outerFrame']['lineColor'], '#f00')
        self.assertEqual(merged['data']['imgMap']['image-1'], 'data:image/png;base64,AA==')

    def test_non_contiguous_group_is_rejected(self) -> None:
        tree = _node('root', 'root', [_node('a', 'a'), _node('b', 'b'), _node('c', 'c')])
        with self.assertRaisesRegex(ValueError, '连续'):
            merge_node_operations(tree, tree, [{
                'type': 'group.upsert',
                'payload': {
                    'key': 'group-1',
                    'groupUid': 'group-1',
                    'memberUids': ['a', 'c'],
                    'payload': {},
                },
            }])

    def test_node_delete_conflicts_with_group_membership(self) -> None:
        result = analyze_concurrent_operations(
            [{'type': 'node.delete', 'nodeUid': 'a'}],
            [{
                'type': 'group.upsert',
                'payload': {
                    'key': 'group-1',
                    'groupUid': 'group-1',
                    'memberUids': ['a', 'b'],
                },
            }],
            history_complete=True,
        )
        self.assertFalse(result['mergeable'])
        self.assertIn('a', result['conflictNodeUids'])

    def test_merge_disjoint_node_updates_preserves_server_change(self) -> None:
        server = _node('root', 'root', [_node('a', 'old-a'), _node('b', 'server-b')])
        client = _node('root', 'root', [_node('a', 'client-a'), _node('b', 'old-b')])

        merged = merge_node_operations(server, client, [
            {'type': 'node.update', 'nodeUid': 'a', 'payload': {'childUids': []}},
        ])

        self.assertEqual(_texts_by_uid(merged), {'root': 'root', 'a': 'client-a', 'b': 'server-b'})

    def test_merge_node_create_uses_client_parent_and_order(self) -> None:
        server = _node('root', 'root', [_node('a', 'a')])
        client = _node('root', 'root', [_node('a', 'a'), _node('c', 'new')])

        merged = merge_node_operations(server, client, [
            {'type': 'node.create', 'nodeUid': 'c', 'payload': {'childUids': []}},
        ])

        self.assertEqual([child['data']['uid'] for child in merged['children']], ['a', 'c'])

    def test_replayed_node_create_is_idempotent(self) -> None:
        server = _node('root', 'root', [_node('a', 'a'), _node('c', 'already synced')])
        client = _node('root', 'root', [_node('a', 'a'), _node('c', 'already synced')])

        merged = merge_node_operations(server, client, [
            _update('root', old_children=['a'], children=['a', 'c']),
            {'type': 'node.create', 'nodeUid': 'c', 'payload': {'data': {'uid': 'c'}}},
        ])

        self.assertEqual([child['data']['uid'] for child in merged['children']], ['a', 'c'])

    def test_client_root_alias_is_canonicalized_to_server_root(self) -> None:
        server = _node('server-root', 'server', [_node('a', 'old')])
        client = _node('draft-root', 'client root', [_node('a', 'updated')])

        merged = merge_node_operations(server, client, [
            _update('a', data_changed=True),
        ])

        self.assertEqual(merged['data']['uid'], 'server-root')
        self.assertEqual(merged['data']['text'], 'server')
        self.assertEqual(merged['children'][0]['data']['text'], 'updated')

    def test_client_root_alias_cannot_overwrite_server_root(self) -> None:
        server = _node('server-root', 'server')
        client = _node('draft-root', 'stale draft')

        with self.assertRaisesRegex(ValueError, '根节点不一致'):
            merge_node_operations(server, client, [
                _update('draft-root', data_changed=True),
            ])

    def test_merge_node_delete_removes_subtree(self) -> None:
        server = _node('root', 'root', [_node('a', 'a', [_node('child', 'child')]), _node('b', 'b')])
        client = _node('root', 'root', [_node('b', 'b')])

        merged = merge_node_operations(server, client, [
            {'type': 'node.delete', 'nodeUid': 'a'},
        ])

        self.assertEqual([child['data']['uid'] for child in merged['children']], ['b'])

    def test_parent_edge_removal_without_delete_never_creates_a_second_root(self) -> None:
        server = _node('root', 'root', [_node('a', 'a'), _node('b', 'b')])
        client = _node('root', 'root', [_node('b', 'b')])

        merged = merge_node_operations(server, client, [
            _update('root', old_children=['a', 'b'], children=['b']),
        ])

        self.assertEqual(
            [child['data']['uid'] for child in merged['children']],
            ['a', 'b'],
        )

    def test_parent_edge_removal_and_explicit_delete_remove_the_node(self) -> None:
        server = _node('root', 'root', [_node('a', 'a'), _node('b', 'b')])
        client = _node('root', 'root', [_node('b', 'b')])

        merged = merge_node_operations(server, client, [
            _update('root', old_children=['a', 'b'], children=['b']),
            {'type': 'node.delete', 'nodeUid': 'a'},
        ])

        self.assertEqual([child['data']['uid'] for child in merged['children']], ['b'])

    def test_move_reparents_before_both_parent_updates_are_materialized(self) -> None:
        server = _node(
            'root', 'root',
            [_node('a', 'a', [_node('moved', 'moved')]), _node('b', 'b')],
        )
        client = _node(
            'root', 'root',
            [_node('a', 'a'), _node('b', 'b', [_node('moved', 'moved')])],
        )

        merged = merge_node_operations(server, client, [
            _update('a', old_children=['moved'], children=[]),
            _update('b', old_children=[], children=['moved']),
        ])

        self.assertEqual(merged['children'][0]['children'], [])
        self.assertEqual(
            [child['data']['uid'] for child in merged['children'][1]['children']],
            ['moved'],
        )

    def test_create_undo_redo_sequence_materializes_one_connected_tree(self) -> None:
        server = _node('root', 'root', [_node('a', 'a')])
        client = _node('root', 'root', [_node('a', 'a'), _node('c', 'final')])

        merged = merge_node_operations(server, client, [
            _update('root', old_children=['a'], children=['a', 'c']),
            {'type': 'node.create', 'nodeUid': 'c', 'payload': {'data': {'uid': 'c'}}},
            _update('root', old_children=['a', 'c'], children=['a']),
            {'type': 'node.delete', 'nodeUid': 'c'},
            _update('root', old_children=['a'], children=['a', 'c']),
            {'type': 'node.create', 'nodeUid': 'c', 'payload': {'data': {'uid': 'c'}}},
        ])

        self.assertEqual(
            [child['data']['uid'] for child in merged['children']],
            ['a', 'c'],
        )
        self.assertEqual(merged['children'][1]['data']['text'], 'final')

    def test_create_then_undo_skips_transient_node_missing_from_final_snapshot(self) -> None:
        server = _node('root', 'root', [_node('a', 'a')])
        client = _node('root', 'root', [_node('a', 'a'), _node('kept', 'kept')])

        merged = merge_node_operations(server, client, [
            _update('root', old_children=['a'], children=['a', 'temporary']),
            {
                'type': 'node.create',
                'nodeUid': 'temporary',
                'payload': {'data': {'uid': 'temporary'}},
            },
            _update('root', old_children=['a', 'temporary'], children=['a']),
            {'type': 'node.delete', 'nodeUid': 'temporary'},
            _update('root', old_children=['a'], children=['a', 'kept']),
            {
                'type': 'node.create',
                'nodeUid': 'kept',
                'payload': {'data': {'uid': 'kept'}},
            },
        ])

        self.assertEqual(
            [child['data']['uid'] for child in merged['children']],
            ['a', 'kept'],
        )

    def test_merge_rejects_document_level_operation(self) -> None:
        tree = _node('root', 'root')
        with self.assertRaisesRegex(ValueError, '不支持自动并发合并'):
            merge_node_operations(tree, tree, [{'type': 'document.update'}])

    def test_file_view_and_node_change_have_disjoint_conflict_domains(self) -> None:
        result = analyze_concurrent_operations(
            [{'type': 'file.view.update'}],
            [_update('a', data_changed=True)],
            history_complete=True,
        )
        self.assertTrue(result['mergeable'])
        self.assertEqual(result['conflictNodeUids'], [])
        self.assertEqual(result['conflictFields'], [])

    def test_concurrent_view_updates_use_last_writer_wins(self) -> None:
        result = analyze_concurrent_operations(
            [{'type': 'file.view.update'}],
            [{'type': 'file.view.update'}],
            history_complete=True,
        )

        self.assertTrue(result['mergeable'])
        self.assertEqual(result['conflictFields'], [])
        self.assertFalse(result['requiresSnapshot'])

    def test_same_file_field_conflicts(self) -> None:
        result = analyze_concurrent_operations(
            [{'type': 'file.theme.update'}],
            [{'type': 'file.theme.update'}],
            history_complete=True,
        )
        self.assertFalse(result['mergeable'])
        self.assertEqual(result['conflictFields'], ['theme'])
        self.assertFalse(result['requiresSnapshot'])

    def test_document_data_conflicts_only_with_the_same_file_field(self) -> None:
        disjoint = analyze_concurrent_operations(
            [{'type': 'file.document_data.update'}],
            [{'type': 'file.theme.update'}],
            history_complete=True,
        )
        same = analyze_concurrent_operations(
            [{'type': 'file.document_data.update'}],
            [{'type': 'file.document_data.update'}],
            history_complete=True,
        )

        self.assertTrue(disjoint['mergeable'])
        self.assertFalse(same['mergeable'])
        self.assertEqual(same['conflictFields'], ['document_data'])

    def test_unknown_operation_requires_snapshot(self) -> None:
        result = analyze_concurrent_operations(
            [{'type': 'document.update'}],
            [_update('a', data_changed=True)],
            history_complete=True,
        )
        self.assertFalse(result['mergeable'])
        self.assertTrue(result['requiresSnapshot'])
        self.assertIsNone(get_operation_conflict_key({'type': 'document.update'}))

    def test_disjoint_additions_under_same_parent_are_mergeable(self) -> None:
        result = analyze_concurrent_operations(
            [_update('root', old_children=['a'], children=['a', 'c']), {'type': 'node.create', 'nodeUid': 'c'}],
            [_update('root', old_children=['a'], children=['a', 'd']), {'type': 'node.create', 'nodeUid': 'd'}],
            history_complete=True,
        )
        self.assertTrue(result['mergeable'])
        self.assertEqual(result['conflictNodeUids'], [])

    def test_same_edge_and_same_parent_reorder_conflict(self) -> None:
        same_edge = analyze_concurrent_operations(
            [_update('root', old_children=['a'], children=['a', 'c'])],
            [_update('root', old_children=['a', 'c'], children=['a'])],
            history_complete=True,
        )
        self.assertFalse(same_edge['mergeable'])
        self.assertEqual(same_edge['conflictNodeUids'], ['root'])

        same_order = analyze_concurrent_operations(
            [_update('root', old_children=['a', 'b'], children=['b', 'a'])],
            [_update('root', old_children=['a', 'b'], children=['b', 'a'])],
            history_complete=True,
        )
        self.assertFalse(same_order['mergeable'])
        self.assertEqual(same_order['conflictNodeUids'], ['root'])

        reorder_vs_edge = analyze_concurrent_operations(
            [_update('root', old_children=['a', 'b'], children=['b', 'a'])],
            [_update('root', old_children=['a', 'b'], children=['a', 'c', 'b'])],
            history_complete=True,
        )
        self.assertFalse(reorder_vs_edge['mergeable'])
        self.assertEqual(reorder_vs_edge['conflictNodeUids'], ['root'])

    def test_parent_delete_conflicts_with_child_list_change(self) -> None:
        result = analyze_concurrent_operations(
            [{'type': 'node.delete', 'nodeUid': 'a'}],
            [_update('a', old_children=[], children=['new'])],
            history_complete=True,
        )
        self.assertFalse(result['mergeable'])
        self.assertEqual(result['conflictNodeUids'], ['a'])

    def test_legacy_node_update_is_not_automatically_merged(self) -> None:
        result = analyze_concurrent_operations(
            [{'type': 'node.update', 'nodeUid': 'a', 'payload': {'childUids': []}}],
            [_update('b', data_changed=True)],
            history_complete=True,
        )
        self.assertFalse(result['mergeable'])
        self.assertTrue(result['requiresSnapshot'])

    def test_merge_disjoint_concurrent_additions_preserves_both_children(self) -> None:
        server = _node('root', 'root', [_node('a', 'a'), _node('d', 'remote')])
        client = _node('root', 'root', [_node('a', 'a'), _node('c', 'local')])

        merged = merge_node_operations(server, client, [
            _update('root', old_children=['a'], children=['a', 'c']),
            {'type': 'node.create', 'nodeUid': 'c', 'payload': {'data': {'uid': 'c'}}},
        ])

        self.assertEqual(
            [child['data']['uid'] for child in merged['children']],
            ['a', 'c', 'd'],
        )

    def test_merge_does_not_persist_untracked_client_snapshot_nodes(self) -> None:
        server = _node('root', 'root', [_node('a', 'a')])
        client = _node(
            'root', 'root',
            [_node('a', 'a'), _node('ghost', 'untracked'), _node('c', 'tracked')],
        )

        merged = merge_node_operations(server, client, [
            _update('root', old_children=['a', 'ghost'], children=['a', 'ghost', 'c']),
            {'type': 'node.create', 'nodeUid': 'c', 'payload': {'data': {'uid': 'c'}}},
        ])

        self.assertEqual([child['data']['uid'] for child in merged['children']], ['a', 'c'])

    def test_concurrent_insertions_keep_their_distinct_anchor_gaps(self) -> None:
        server = _node('root', 'root', [_node('a', 'a'), _node('b', 'b'), _node('d', 'after-b')])
        client = _node('root', 'root', [_node('a', 'a'), _node('c', 'before-b'), _node('b', 'b')])

        merged = merge_node_operations(server, client, [
            _update('root', old_children=['a', 'b'], children=['a', 'c', 'b']),
            {'type': 'node.create', 'nodeUid': 'c', 'payload': {'data': {'uid': 'c'}}},
        ])
        self.assertEqual(
            [child['data']['uid'] for child in merged['children']],
            ['a', 'c', 'b', 'd'],
        )

        reverse_server = _node('root', 'root', [_node('a', 'a'), _node('c', 'before-b'), _node('b', 'b')])
        reverse_client = _node('root', 'root', [_node('a', 'a'), _node('b', 'b'), _node('d', 'after-b')])
        reverse_merged = merge_node_operations(reverse_server, reverse_client, [
            _update('root', old_children=['a', 'b'], children=['a', 'b', 'd']),
            {'type': 'node.create', 'nodeUid': 'd', 'payload': {'data': {'uid': 'd'}}},
        ])
        self.assertEqual(
            [child['data']['uid'] for child in reverse_merged['children']],
            ['a', 'c', 'b', 'd'],
        )

    def test_data_only_merge_preserves_remote_children(self) -> None:
        server = _node('root', 'root', [_node('a', 'server-a', [_node('remote', 'remote')])])
        client = _node('root', 'root', [_node('a', 'client-a')])

        merged = merge_node_operations(server, client, [_update('a', data_changed=True)])

        node_a = merged['children'][0]
        self.assertEqual(node_a['data']['text'], 'client-a')
        self.assertEqual([child['data']['uid'] for child in node_a['children']], ['remote'])

    def test_change_history_must_be_contiguous(self) -> None:
        self.assertTrue(is_change_history_complete(
            [SimpleNamespace(revision=4), SimpleNamespace(revision=5)],
            base_revision=3,
            current_revision=5,
        ))
        self.assertFalse(is_change_history_complete(
            [SimpleNamespace(revision=5)],
            base_revision=3,
            current_revision=5,
        ))


if __name__ == '__main__':
    unittest.main()
