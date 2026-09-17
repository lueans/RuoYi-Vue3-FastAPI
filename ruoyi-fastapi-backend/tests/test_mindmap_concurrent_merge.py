"""脑图节点级并发合并测试。"""
import copy
import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from exceptions.exception import ServiceWarning
from module_mindmap.entity.vo.mindmap_vo import MindmapContentBatchModel
from module_mindmap.service.mindmap_service import (
    MindmapService,
    _canonicalize_node_delete_scopes,
    _content_batch_request_fingerprint,
    analyze_concurrent_operations,
    concurrent_merge_requires_authoritative_reload,
    get_operation_conflict_key,
    get_operation_conflict_keys,
    is_change_history_complete,
    merge_node_operations,
)
from module_mindmap.service.simple_mind_document_codec import clone_json_value


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


def _verified_update(
    uid: str,
    *,
    previous_data: dict | None = None,
    data: dict | None = None,
    old_children: list[str] | None = None,
    children: list[str] | None = None,
) -> dict:
    data_changed = previous_data is not None or data is not None
    children_changed = old_children is not None or children is not None
    return {
        'type': 'node.update',
        'nodeUid': uid,
        'payload': {
            'data': data or {'uid': uid, 'text': uid},
            **({'previousData': previous_data} if data_changed else {}),
            'dataChanged': data_changed,
            'childrenChanged': children_changed,
            'oldChildUids': old_children or [],
            'childUids': children or [],
            'crossNodeDataSeparated': True,
            'tagBindingsSeparated': True,
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


def _cross_delta_operation(
    prefix: str,
    key: str,
    before: dict | None,
    after: dict | None,
) -> dict:
    action = 'delete' if after is None else 'upsert'
    visible_record = after if after is not None else before
    return {
        'type': f'{prefix}.{action}',
        'payload': {
            'key': key,
            **clone_json_value(visible_record or {}),
            'before': clone_json_value(before),
            'after': clone_json_value(after),
        },
    }


def _relation_record(
    target_uid: str,
    *,
    style_data: dict | None = None,
) -> dict:
    relation_uid = f'assoc:root:{target_uid}'
    return {
        'relationUid': relation_uid,
        'relationType': 'associative_line',
        'sourceUid': 'root',
        'targetUid': target_uid,
        'text': None,
        'controlData': {},
        'styleData': copy.deepcopy(style_data),
        'sortOrder': 0,
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
    def test_collaboration_bookkeeping_is_neutral_to_concurrent_content(self) -> None:
        local = _update('a', data_changed=True)
        for remote_type in (
            'collaboration.sync.confirm',
            'collaboration.authoritative_reset',
        ):
            with self.subTest(remote_type=remote_type):
                remote = {'type': remote_type}
                self.assertEqual(get_operation_conflict_keys(remote), set())
                self.assertTrue(
                    analyze_concurrent_operations([local], [remote], True)['mergeable'],
                )

    def test_server_canonicalizes_incomplete_delete_scope_before_conflict_analysis(self) -> None:
        server = _node(
            'root',
            'root',
            [_node('parent', 'parent', [_node('child', 'child')])],
        )
        delete_branch = {
            'type': 'node.delete',
            'nodeUid': 'parent',
            # 模拟旧/异常客户端只声明了子树根。
            'payload': {'deletedNodeUids': ['parent']},
        }

        _canonicalize_node_delete_scopes(server, [delete_branch])
        result = analyze_concurrent_operations(
            [delete_branch],
            [_update('child', data_changed=True)],
            history_complete=True,
        )

        self.assertEqual(
            delete_branch['payload']['deletedNodeUids'],
            ['parent', 'child'],
        )
        self.assertFalse(result['mergeable'])
        self.assertEqual(result['conflictNodeUids'], ['child'])

    def test_data_field_merge_does_not_require_authoritative_canvas_reload(self) -> None:
        operation = {
            'type': 'node.update',
            'nodeUid': 'a',
            'payload': {
                'data': {'uid': 'a', 'text': 'changed'},
                'previousData': {'uid': 'a', 'text': 'old'},
                'dataChanged': True,
                'childrenChanged': False,
            },
        }

        self.assertFalse(concurrent_merge_requires_authoritative_reload([operation]))
        self.assertTrue(concurrent_merge_requires_authoritative_reload([
            _update('root', old_children=['a'], children=['a', 'b']),
        ]))

    def test_different_tag_bindings_on_same_node_are_mergeable(self) -> None:
        result = analyze_concurrent_operations(
            [_tag_operation(11)],
            [_tag_operation(12)],
            history_complete=True,
        )
        self.assertTrue(result['mergeable'])
        self.assertEqual(result['conflictEntities'], [])

    def test_realtime_update_of_unpersisted_create_is_a_mergeable_causal_pair(self) -> None:
        create = {
            'type': 'node.create',
            'nodeUid': 'new-node',
            'payload': {'data': {'uid': 'new-node', 'text': 'initial'}},
        }
        update = {
            'type': 'node.update',
            'nodeUid': 'new-node',
            'payload': {
                'data': {'uid': 'new-node', 'text': 'edited elsewhere'},
                'dataChanged': True,
                'childrenChanged': False,
            },
        }

        self.assertTrue(analyze_concurrent_operations([create], [update], True)['mergeable'])
        self.assertTrue(analyze_concurrent_operations([update], [create], True)['mergeable'])

        update['targetRevision'] = 1
        self.assertFalse(analyze_concurrent_operations([create], [update], True)['mergeable'])

    def test_same_tag_binding_conflicts_and_node_delete_protects_binding(self) -> None:
        same_binding = analyze_concurrent_operations(
            [_tag_operation(11)],
            [_tag_operation(11, 'unbind')],
            history_complete=True,
        )
        self.assertFalse(same_binding['mergeable'])
        self.assertEqual(same_binding['conflictEntities'], ['tag-binding:a:11'])

        deleted_node = analyze_concurrent_operations(
            [{
                'type': 'node.delete',
                'nodeUid': 'a',
                'payload': {'deletedNodeUids': ['a']},
            }],
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

    def test_updating_existing_tag_binding_preserves_its_original_position(self) -> None:
        server = _node('root', 'root', [_node('a', 'a')])
        server['children'][0]['data']['tag'] = [
            {'tagId': 11, 'placement': 'top'},
            {'tagId': 12},
        ]
        client = copy.deepcopy(server)
        client['children'][0]['data']['tag'][0]['placement'] = 'bottom'

        merged = merge_node_operations(server, client, [{
            'type': 'node.tag.bind',
            'nodeUid': 'a',
            'payload': {
                'key': 'a:11',
                'tagKey': '11',
                'tag': {'tagId': 11, 'placement': 'bottom'},
            },
        }])

        self.assertEqual(
            [tag['tagId'] for tag in merged['children'][0]['data']['tag']],
            [11, 12],
        )
        self.assertEqual(
            merged['children'][0]['data']['tag'][0]['placement'],
            'bottom',
        )

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
            [{
                'type': 'node.delete',
                'nodeUid': 'root',
                'payload': {'deletedNodeUids': ['root']},
            }],
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

    def test_relation_deep_style_siblings_merge_on_same_record(self) -> None:
        before = _relation_record(
            'a',
            style_data={'line': {'color': '#111111', 'width': 1}},
        )
        color_after = copy.deepcopy(before)
        color_after['styleData']['line']['color'] = '#ff0000'
        width_after = copy.deepcopy(before)
        width_after['styleData']['line']['width'] = 3
        color_operation = _cross_delta_operation(
            'relation', before['relationUid'], before, color_after,
        )
        width_operation = _cross_delta_operation(
            'relation', before['relationUid'], before, width_after,
        )

        self.assertTrue(analyze_concurrent_operations(
            [color_operation], [width_operation], history_complete=True,
        )['mergeable'])

        server = _node('root', 'root', [_node('a', 'a')])
        server['data']['associativeLineTargets'] = ['a']
        server['data']['associativeLineStyle'] = {
            'a': {'line': {'color': '#111111', 'width': 3}},
        }
        merged = merge_node_operations(server, server, [color_operation])

        self.assertEqual(merged['data']['associativeLineStyle']['a'], {
            'line': {'color': '#ff0000', 'width': 3},
        })

    def test_relation_cumulative_local_delta_preserves_remote_only_text(self) -> None:
        before = _relation_record(
            'a',
            style_data={'line': {'color': 'red', 'width': 1}},
        )
        before['text'] = 'old'
        local_after = copy.deepcopy(before)
        local_after['styleData']['line'] = {'color': 'blue', 'width': 2}
        remote_after = copy.deepcopy(before)
        remote_after['text'] = 'remote'
        local_operation = _cross_delta_operation(
            'relation', before['relationUid'], before, local_after,
        )
        remote_operation = _cross_delta_operation(
            'relation', before['relationUid'], before, remote_after,
        )

        self.assertTrue(analyze_concurrent_operations(
            [local_operation], [remote_operation], history_complete=True,
        )['mergeable'])

        server = _node('root', 'root', [_node('a', 'a')])
        server['data']['associativeLineTargets'] = ['a']
        server['data']['associativeLineText'] = {'a': 'remote'}
        server['data']['associativeLineStyle'] = {
            'a': {'line': {'color': 'red', 'width': 1}},
        }
        merged = merge_node_operations(server, server, [local_operation])

        self.assertEqual(merged['data']['associativeLineText']['a'], 'remote')
        self.assertEqual(merged['data']['associativeLineStyle']['a'], {
            'line': {'color': 'blue', 'width': 2},
        })

    def test_deep_relation_delta_is_stack_safe_through_fingerprint_and_merge(self) -> None:
        depth = 1200

        def nested_style(leaf: str) -> dict:
            value: dict = {'leaf': leaf}
            for _ in range(depth):
                value = {'nested': value}
            return value

        before = _relation_record('a')
        before['styleData'] = nested_style('old')
        after = _relation_record('a')
        after['styleData'] = nested_style('changed')
        operation = _cross_delta_operation(
            'relation', before['relationUid'], before, after,
        )
        server = _node('root', 'root', [_node('a', 'a')])
        server['data']['associativeLineTargets'] = ['a']
        server['data']['associativeLineStyle'] = {'a': nested_style('old')}
        batch = MindmapContentBatchModel(
            baseRevision=1,
            clientMutationId='deep-relation-delta',
            operations=[operation],
            nodeTree=server,
        )

        self.assertEqual(len(_content_batch_request_fingerprint(batch)), 64)
        self.assertTrue(analyze_concurrent_operations(
            [operation],
            [clone_json_value(operation)],
            history_complete=True,
        )['mergeable'])
        self.assertTrue(any(
            ':v2:path:' in key
            for key in get_operation_conflict_keys(operation) or set()
        ))
        merged = merge_node_operations(server, server, [operation])

        value = merged['data']['associativeLineStyle']['a']
        for _ in range(depth):
            value = value['nested']
        self.assertEqual(value, {'leaf': 'changed'})

    def test_iterative_batch_fingerprint_preserves_legacy_digest(self) -> None:
        operation = _cross_delta_operation(
            'relation',
            'assoc:root:a',
            _relation_record('a', style_data={'color': 'red'}),
            _relation_record('a', style_data={'color': 'blue'}),
        )
        batch = MindmapContentBatchModel(
            baseRevision=3,
            clientMutationId='fingerprint-compatibility',
            yjsUpdateCount=2,
            yjsDeliveryMode='sequenced',
            operations=[operation],
            nodeTree=_node('root', 'root', [_node('a', 'a')]),
            viewData={'scale': 1.0},
            layout='logicalStructure',
            theme={'template': 'classic'},
            documentData={'extension': {'enabled': False}},
        )
        legacy_payload = batch.model_dump(by_alias=True, exclude_none=False)
        legacy_digest = hashlib.sha256(json.dumps(
            legacy_payload,
            sort_keys=True,
            separators=(',', ':'),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()).hexdigest()

        self.assertEqual(_content_batch_request_fingerprint(batch), legacy_digest)

    def test_summary_endpoint_and_payload_changes_merge_on_same_record(self) -> None:
        before = {
            'summaryUid': 'summary-1',
            'ownerUid': 'root',
            'startChildUid': 'a',
            'endChildUid': 'b',
            'payload': {'text': 'old', 'style': {'color': '#111111'}},
            'sortOrder': 0,
        }
        endpoint_after = copy.deepcopy(before)
        endpoint_after['endChildUid'] = 'c'
        payload_after = copy.deepcopy(before)
        payload_after['payload']['text'] = 'remote'
        endpoint_operation = _cross_delta_operation(
            'summary', 'root:summary-1', before, endpoint_after,
        )
        payload_operation = _cross_delta_operation(
            'summary', 'root:summary-1', before, payload_after,
        )

        self.assertTrue(analyze_concurrent_operations(
            [endpoint_operation], [payload_operation], history_complete=True,
        )['mergeable'])

        server = _node(
            'root',
            'root',
            [_node('a', 'a'), _node('b', 'b'), _node('c', 'c')],
        )
        server['data']['generalization'] = [{
            'uid': 'summary-1',
            'range': [0, 1],
            'text': 'remote',
            'style': {'color': '#111111'},
        }]
        merged = merge_node_operations(server, server, [endpoint_operation])

        self.assertEqual(merged['data']['generalization'][0]['range'], [0, 2])
        self.assertEqual(merged['data']['generalization'][0]['text'], 'remote')

    def test_summary_json_boolean_to_number_is_a_real_delta(self) -> None:
        before = {
            'summaryUid': 'summary-1',
            'ownerUid': 'root',
            'startChildUid': 'a',
            'endChildUid': 'a',
            'payload': {'enabled': False},
            'sortOrder': 0,
        }
        after = copy.deepcopy(before)
        after['payload']['enabled'] = 0
        operation = _cross_delta_operation(
            'summary', 'root:summary-1', before, after,
        )

        self.assertTrue(any(
            ':v2:path:' in key
            for key in get_operation_conflict_keys(operation) or set()
        ))

        server = _node('root', 'root', [_node('a', 'a')])
        server['data']['generalization'] = [{
            'uid': 'summary-1',
            'range': [0, 0],
            'enabled': False,
        }]
        merged = merge_node_operations(server, server, [operation])

        enabled = merged['data']['generalization'][0]['enabled']
        self.assertEqual(enabled, 0)
        self.assertIs(type(enabled), int)

    def test_group_different_member_additions_merge_as_a_set(self) -> None:
        before = {
            'groupUid': 'group-1',
            'groupType': 'outer_frame',
            'payload': {'lineColor': '#111111'},
            'memberUids': ['b', 'c'],
        }
        add_left = {**copy.deepcopy(before), 'memberUids': ['a', 'b', 'c']}
        add_right = {**copy.deepcopy(before), 'memberUids': ['b', 'c', 'd']}
        left_operation = _cross_delta_operation(
            'group', 'group-1', before, add_left,
        )
        right_operation = _cross_delta_operation(
            'group', 'group-1', before, add_right,
        )

        self.assertTrue(analyze_concurrent_operations(
            [left_operation], [right_operation], history_complete=True,
        )['mergeable'])

        server = _node(
            'root',
            'root',
            [_node('a', 'a'), _node('b', 'b'), _node('c', 'c'), _node('d', 'd')],
        )
        for child in server['children'][1:]:
            child['data']['outerFrame'] = {
                'groupId': 'group-1',
                'lineColor': '#111111',
            }
        merged = merge_node_operations(server, server, [left_operation])

        self.assertEqual(
            [child['data']['outerFrame']['groupId'] for child in merged['children']],
            ['group-1'] * 4,
        )

    def test_group_same_member_cannot_be_claimed_by_different_groups(self) -> None:
        first_before = {
            'groupUid': 'group-1',
            'groupType': 'outer_frame',
            'payload': {},
            'memberUids': ['a'],
        }
        second_before = {
            'groupUid': 'group-2',
            'groupType': 'outer_frame',
            'payload': {},
            'memberUids': ['c'],
        }
        first_after = {**copy.deepcopy(first_before), 'memberUids': ['a', 'b']}
        second_after = {**copy.deepcopy(second_before), 'memberUids': ['b', 'c']}

        result = analyze_concurrent_operations(
            [_cross_delta_operation('group', 'group-1', first_before, first_after)],
            [_cross_delta_operation('group', 'group-2', second_before, second_after)],
            history_complete=True,
        )

        self.assertFalse(result['mergeable'])

    def test_group_last_local_removal_merges_with_remote_member_addition(self) -> None:
        before = {
            'groupUid': 'group-1',
            'groupType': 'outer_frame',
            'payload': {'lineColor': '#111111'},
            'memberUids': ['a'],
        }
        remove_last = {**copy.deepcopy(before), 'memberUids': []}
        add_remote = {**copy.deepcopy(before), 'memberUids': ['a', 'b']}
        remove_operation = _cross_delta_operation(
            'group', 'group-1', before, remove_last,
        )
        add_operation = _cross_delta_operation(
            'group', 'group-1', before, add_remote,
        )

        remove_keys = get_operation_conflict_keys(remove_operation) or set()
        add_keys = get_operation_conflict_keys(add_operation) or set()
        self.assertFalse(any(':v2:entity:' in key for key in remove_keys | add_keys))
        self.assertFalse(any('member_uids' in key for key in remove_keys | add_keys))
        self.assertTrue(analyze_concurrent_operations(
            [remove_operation], [add_operation], history_complete=True,
        )['mergeable'])

        server = _node('root', 'root', [_node('a', 'a'), _node('b', 'b')])
        for child in server['children']:
            child['data']['outerFrame'] = {
                'groupId': 'group-1',
                'lineColor': '#111111',
            }
        merged = merge_node_operations(server, server, [remove_operation])

        self.assertNotIn('outerFrame', merged['children'][0]['data'])
        self.assertEqual(
            merged['children'][1]['data']['outerFrame']['groupId'],
            'group-1',
        )

    def test_group_last_member_removal_materializes_as_entity_removal(self) -> None:
        before = {
            'groupUid': 'group-1',
            'groupType': 'outer_frame',
            'payload': {'lineColor': '#111111'},
            'memberUids': ['a'],
        }
        remove_last = {**copy.deepcopy(before), 'memberUids': []}
        operation = _cross_delta_operation(
            'group', 'group-1', before, remove_last,
        )
        server = _node('root', 'root', [_node('a', 'a')])
        server['children'][0]['data']['outerFrame'] = {
            'groupId': 'group-1',
            'lineColor': '#111111',
        }

        merged = merge_node_operations(server, server, [operation])

        self.assertNotIn('outerFrame', merged['children'][0]['data'])

    def test_group_remove_and_add_converge_in_both_arrival_orders(self) -> None:
        before = {
            'groupUid': 'group-1',
            'groupType': 'outer_frame',
            'payload': {'lineColor': '#111111'},
            'memberUids': ['a'],
        }
        remove_operation = _cross_delta_operation(
            'group',
            'group-1',
            before,
            {**copy.deepcopy(before), 'memberUids': []},
        )
        add_operation = _cross_delta_operation(
            'group',
            'group-1',
            before,
            {**copy.deepcopy(before), 'memberUids': ['a', 'b']},
        )
        base = _node('root', 'root', [_node('a', 'a'), _node('b', 'b')])
        base['children'][0]['data']['outerFrame'] = {
            'groupId': 'group-1',
            'lineColor': '#111111',
        }

        remove_first = merge_node_operations(base, base, [remove_operation])
        remove_then_add = merge_node_operations(
            remove_first, remove_first, [add_operation],
        )
        add_first = merge_node_operations(base, base, [add_operation])
        add_then_remove = merge_node_operations(
            add_first, add_first, [remove_operation],
        )

        self.assertEqual(remove_then_add, add_then_remove)
        self.assertNotIn('outerFrame', remove_then_add['children'][0]['data'])
        self.assertEqual(
            remove_then_add['children'][1]['data']['outerFrame']['groupId'],
            'group-1',
        )

    def test_cross_record_delete_conflicts_with_path_update(self) -> None:
        before = _relation_record(
            'a', style_data={'line': {'color': '#111111'}},
        )
        after = copy.deepcopy(before)
        after['styleData']['line']['color'] = '#ff0000'

        result = analyze_concurrent_operations(
            [_cross_delta_operation('relation', before['relationUid'], before, None)],
            [_cross_delta_operation('relation', before['relationUid'], before, after)],
            history_complete=True,
        )

        self.assertFalse(result['mergeable'])
        self.assertTrue(result['conflictEntities'])

    def test_equivalent_cross_deltas_are_idempotent_in_both_directions(self) -> None:
        relation_before = _relation_record(
            'a', style_data={'line': {'color': 'red', 'width': 1}},
        )
        relation_after = clone_json_value(relation_before)
        relation_after['styleData']['line']['color'] = 'blue'
        relation = _cross_delta_operation(
            'relation', relation_before['relationUid'], relation_before, relation_after,
        )
        group_before = {
            'groupUid': 'group-1',
            'groupType': 'outer_frame',
            'payload': {},
            'memberUids': ['a'],
        }
        group_add_left = _cross_delta_operation(
            'group',
            'group-1',
            group_before,
            {**clone_json_value(group_before), 'memberUids': ['a', 'b']},
        )
        group_add_right = _cross_delta_operation(
            'group',
            'group-1',
            group_before,
            {**clone_json_value(group_before), 'memberUids': ['b', 'a']},
        )
        group_remove_before = {
            **clone_json_value(group_before),
            'memberUids': ['a', 'b'],
        }
        group_remove_left = _cross_delta_operation(
            'group',
            'group-1',
            group_remove_before,
            {**clone_json_value(group_before), 'memberUids': ['a']},
        )
        group_remove_right = _cross_delta_operation(
            'group',
            'group-1',
            {**clone_json_value(group_remove_before), 'memberUids': ['b', 'a']},
            {**clone_json_value(group_before), 'memberUids': ['a']},
        )

        pairs = [
            (relation, clone_json_value(relation)),
            (group_add_left, group_add_right),
            (group_remove_left, group_remove_right),
        ]
        for left, right in pairs:
            for local, remote in ((left, right), (right, left)):
                with self.subTest(
                    operation=local['type'],
                    direction=(local is left),
                ):
                    self.assertTrue(analyze_concurrent_operations(
                        [local], [remote], history_complete=True,
                    )['mergeable'])

    def test_equivalent_cross_deletes_are_idempotent_in_all_domains(self) -> None:
        snapshots = {
            'relation': (
                'assoc:root:a',
                _relation_record('a'),
            ),
            'summary': (
                'root:summary-1',
                {
                    'summaryUid': 'summary-1',
                    'ownerUid': 'root',
                    'startChildUid': 'a',
                    'endChildUid': 'a',
                    'payload': {'text': 'summary'},
                    'sortOrder': 0,
                },
            ),
            'asset': (
                'image-1',
                {'assetKey': 'image-1', 'uri': 'https://example.test/image.png'},
            ),
        }
        for prefix, (key, before) in snapshots.items():
            delete = _cross_delta_operation(prefix, key, before, None)
            for local, remote in (
                (delete, clone_json_value(delete)),
                (clone_json_value(delete), delete),
            ):
                with self.subTest(prefix=prefix, direction=(local is delete)):
                    self.assertTrue(analyze_concurrent_operations(
                        [local], [remote], history_complete=True,
                    )['mergeable'])

    def test_same_cross_path_with_a_different_base_remains_a_conflict(self) -> None:
        first_before = _relation_record(
            'a', style_data={'line': {'color': 'red'}},
        )
        second_before = _relation_record(
            'a', style_data={'line': {'color': 'green'}},
        )
        after = _relation_record(
            'a', style_data={'line': {'color': 'blue'}},
        )

        result = analyze_concurrent_operations(
            [_cross_delta_operation(
                'relation', first_before['relationUid'], first_before, after,
            )],
            [_cross_delta_operation(
                'relation', second_before['relationUid'], second_before, after,
            )],
            history_complete=True,
        )

        self.assertFalse(result['mergeable'])

    def test_same_batch_relation_delete_then_recreate_keeps_generation_order(self) -> None:
        before = _relation_record(
            'a', style_data={'line': {'color': 'red'}},
        )
        before['text'] = 'old'
        recreated = copy.deepcopy(before)
        recreated['text'] = 'recreated'
        recreated['styleData']['line']['color'] = 'blue'
        operations = [
            _cross_delta_operation(
                'relation', before['relationUid'], before, None,
            ),
            _cross_delta_operation(
                'relation', before['relationUid'], None, recreated,
            ),
        ]
        remote_after = copy.deepcopy(before)
        remote_after['text'] = 'remote'
        remote_operation = _cross_delta_operation(
            'relation', before['relationUid'], before, remote_after,
        )

        self.assertFalse(analyze_concurrent_operations(
            operations, [remote_operation], history_complete=True,
        )['mergeable'])

        server = _node('root', 'root', [_node('a', 'a')])
        server['data']['associativeLineTargets'] = ['a']
        server['data']['associativeLineText'] = {'a': 'old'}
        server['data']['associativeLineStyle'] = {'a': {'line': {'color': 'red'}}}
        merged = merge_node_operations(server, server, operations)

        self.assertEqual(merged['data']['associativeLineText']['a'], 'recreated')
        self.assertEqual(
            merged['data']['associativeLineStyle']['a']['line']['color'],
            'blue',
        )

    def test_same_batch_asset_generation_sequences_are_applied_in_order(self) -> None:
        old_asset = {'assetKey': 'image-1', 'uri': 'https://example.test/old.png'}
        new_asset = {'assetKey': 'image-1', 'uri': 'https://example.test/new.png'}
        delete_then_recreate = [
            _cross_delta_operation('asset', 'image-1', old_asset, None),
            _cross_delta_operation('asset', 'image-1', None, new_asset),
        ]
        create_then_delete = [
            _cross_delta_operation('asset', 'image-2', None, {
                'assetKey': 'image-2',
                'uri': 'https://example.test/transient.png',
            }),
            _cross_delta_operation('asset', 'image-2', {
                'assetKey': 'image-2',
                'uri': 'https://example.test/transient.png',
            }, None),
        ]
        remote_create = _cross_delta_operation(
            'asset',
            'image-2',
            None,
            {'assetKey': 'image-2', 'uri': 'https://example.test/remote.png'},
        )

        self.assertFalse(analyze_concurrent_operations(
            create_then_delete, [remote_create], history_complete=True,
        )['mergeable'])

        server = _node('root', 'root')
        server['data']['imgMap'] = {'image-1': old_asset['uri']}
        merged = merge_node_operations(
            server,
            server,
            [*delete_then_recreate, *create_then_delete],
        )

        self.assertEqual(merged['data']['imgMap'], {'image-1': new_asset['uri']})

    def test_legacy_cross_payload_remains_a_wide_entity_update(self) -> None:
        before = _relation_record(
            'a', style_data={'line': {'color': '#111111', 'width': 1}},
        )
        after = copy.deepcopy(before)
        after['styleData']['line']['width'] = 3
        delta_operation = _cross_delta_operation(
            'relation', before['relationUid'], before, after,
        )
        legacy_operation = _relation_operation('a')

        self.assertFalse(analyze_concurrent_operations(
            [legacy_operation], [delta_operation], history_complete=True,
        )['mergeable'])

        server = _node('root', 'root', [_node('a', 'a')])
        server['data']['associativeLineTargets'] = ['a']
        server['data']['associativeLineStyle'] = {
            'a': {'line': {'color': '#111111', 'width': 3}},
        }
        legacy_operation['payload']['styleData'] = {'line': {'color': '#ff0000'}}
        merged = merge_node_operations(server, server, [legacy_operation])

        self.assertEqual(
            merged['data']['associativeLineStyle']['a'],
            {'line': {'color': '#ff0000'}},
        )

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
            [{
                'type': 'node.delete',
                'nodeUid': 'a',
                'payload': {'deletedNodeUids': ['a']},
            }],
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

    def test_different_data_fields_on_same_node_are_mergeable(self) -> None:
        local = {
            'type': 'node.update',
            'nodeUid': 'a',
            'payload': {
                'data': {'uid': 'a', 'text': 'local title', 'note': 'old note'},
                'previousData': {'uid': 'a', 'text': 'old title', 'note': 'old note'},
                'dataChanged': True,
                'childrenChanged': False,
            },
        }
        remote = {
            'type': 'node.update',
            'nodeUid': 'a',
            'payload': {
                'data': {'uid': 'a', 'text': 'old title', 'note': 'remote note'},
                'previousData': {'uid': 'a', 'text': 'old title', 'note': 'old note'},
                'dataChanged': True,
                'childrenChanged': False,
            },
        }

        result = analyze_concurrent_operations([local], [remote], history_complete=True)

        self.assertTrue(result['mergeable'])

    def test_node_json_boolean_to_number_is_a_real_field_delta(self) -> None:
        operation = _verified_update(
            'a',
            previous_data={'uid': 'a', 'text': 'a', 'enabled': False},
            data={'uid': 'a', 'text': 'a', 'enabled': 0},
        )

        self.assertIn('node:a:data:enabled', get_operation_conflict_keys(operation) or set())

        server = _node('root', 'root', [_node('a', 'a')])
        server['children'][0]['data']['enabled'] = False
        client = copy.deepcopy(server)
        client['children'][0]['data']['enabled'] = 0
        merged = merge_node_operations(server, client, [operation])

        enabled = merged['children'][0]['data']['enabled']
        self.assertEqual(enabled, 0)
        self.assertIs(type(enabled), int)

    def test_same_data_field_on_same_node_still_conflicts(self) -> None:
        operation = {
            'type': 'node.update',
            'nodeUid': 'a',
            'payload': {
                'data': {'uid': 'a', 'text': 'changed'},
                'previousData': {'uid': 'a', 'text': 'old'},
                'dataChanged': True,
                'childrenChanged': False,
            },
        }

        result = analyze_concurrent_operations([operation], [operation], history_complete=True)

        self.assertFalse(result['mergeable'])
        self.assertEqual(result['conflictNodeUids'], ['a'])

    def test_field_delta_merge_preserves_concurrent_server_field(self) -> None:
        server = _node('root', 'root', [_node('a', 'old title')])
        server['children'][0]['data']['note'] = 'remote note'
        client = _node('root', 'root', [_node('a', 'local title')])
        client['children'][0]['data']['note'] = 'old note'

        merged = merge_node_operations(server, client, [{
            'type': 'node.update',
            'nodeUid': 'a',
            'payload': {
                'data': {'uid': 'a', 'text': 'local title', 'note': 'old note'},
                'previousData': {'uid': 'a', 'text': 'old title', 'note': 'old note'},
                'dataChanged': True,
                'childrenChanged': False,
            },
        }])

        self.assertEqual(merged['children'][0]['data']['text'], 'local title')
        self.assertEqual(merged['children'][0]['data']['note'], 'remote note')

    def test_node_update_uses_operation_data_when_materialized_snapshot_is_stale(self) -> None:
        server = _node('root', 'root', [_node('a', 'old')])
        client = _node('root', 'root', [_node('a', '')])

        merged = merge_node_operations(server, client, [{
            'type': 'node.update',
            'nodeUid': 'a',
            'payload': {
                'data': {'uid': 'a', 'text': 'typed title'},
                'dataChanged': True,
                'childrenChanged': False,
            },
        }])

        self.assertEqual(merged['children'][0]['data']['text'], 'typed title')

    def test_realtime_update_materializes_unpersisted_node_when_parent_exists(self) -> None:
        server = _node('root', 'root')
        client = _node('root', 'root', [_node('remote-created', '')])

        merged = merge_node_operations(server, client, [{
            'type': 'node.update',
            'nodeUid': 'remote-created',
            'payload': {
                'data': {'uid': 'remote-created', 'text': 'edited in browser B'},
                'dataChanged': True,
                'childrenChanged': False,
            },
        }])

        self.assertEqual(merged['children'][0]['data']['text'], 'edited in browser B')

    def test_realtime_descendant_update_materializes_only_verified_ancestor_chain(self) -> None:
        server = _node('root', 'root', [_node('persisted', 'server value')])
        new_parent = _node('new-parent', 'new parent', [
            _node('new-child', 'edited in browser B'),
            _node('untracked-sibling', 'must not be imported'),
        ])
        new_parent['data'].update({
            'tag': [{'tagId': 91}],
            'associativeLineTargets': ['persisted'],
        })
        client = _node('root', 'root', [
            _node('persisted', 'tampered snapshot', [
                new_parent,
            ]),
        ])
        operation = _verified_update(
            'new-child',
            previous_data={'uid': 'new-child', 'text': 'initial title'},
            data={'uid': 'new-child', 'text': 'edited in browser B'},
        )

        merged = merge_node_operations(server, client, [operation])

        self.assertEqual(merged['children'][0]['data']['text'], 'server value')
        materialized_parent_data = merged['children'][0]['children'][0]['data']
        self.assertNotIn('tag', materialized_parent_data)
        self.assertNotIn('associativeLineTargets', materialized_parent_data)
        self.assertEqual(
            _texts_by_uid(merged),
            {
                'root': 'root',
                'persisted': 'server value',
                'new-parent': 'new parent',
                'new-child': 'edited in browser B',
            },
        )

    def test_realtime_subtree_create_and_descendant_edit_commute_by_http_arrival_order(self) -> None:
        server = _node('root', 'root', [_node('existing', 'existing')])
        creator_child = _node('new-child', 'initial title')
        creator_child['data']['note'] = 'creator final note'
        editor_child = _node('new-child', 'edited in browser B')
        editor_child['data']['note'] = 'note before creator save'
        creator_tree = _node('root', 'root', [
            _node('existing', 'existing'),
            _node('new-parent', 'creator final parent', [creator_child]),
        ])
        editor_tree = _node('root', 'root', [
            _node('existing', 'existing'),
            _node('new-parent', 'parent before creator save', [editor_child]),
        ])
        create_operations = [
            _update('root', old_children=['existing'], children=['existing', 'new-parent']),
            {
                'type': 'node.create',
                'nodeUid': 'new-parent',
                'payload': {
                    'data': {'uid': 'new-parent', 'text': 'creator final parent'},
                },
            },
            {
                'type': 'node.create',
                'nodeUid': 'new-child',
                'payload': {
                    'data': {
                        'uid': 'new-child',
                        'text': 'initial title',
                        'note': 'creator final note',
                    },
                },
            },
        ]
        edit_operations = [_verified_update(
            'new-child',
            previous_data={
                'uid': 'new-child',
                'text': 'initial title',
                'note': 'note before creator save',
            },
            data={
                'uid': 'new-child',
                'text': 'edited in browser B',
                'note': 'note before creator save',
            },
        )]

        self.assertTrue(analyze_concurrent_operations(
            create_operations,
            edit_operations,
            history_complete=True,
        )['mergeable'])
        self.assertTrue(analyze_concurrent_operations(
            edit_operations,
            create_operations,
            history_complete=True,
        )['mergeable'])

        create_first = merge_node_operations(server, creator_tree, create_operations)
        create_then_edit = merge_node_operations(
            create_first,
            editor_tree,
            edit_operations,
            remote_operations=create_operations,
        )
        edit_first = merge_node_operations(server, editor_tree, edit_operations)
        self.assertEqual(
            edit_operations[0]['payload']['serverMaterializedNodeUids'],
            ['new-parent', 'new-child'],
        )
        edit_then_create = merge_node_operations(
            edit_first,
            creator_tree,
            create_operations,
            remote_operations=edit_operations,
        )

        self.assertEqual(create_then_edit, edit_then_create)
        self.assertEqual(create_then_edit['children'][1]['data']['text'], 'creator final parent')
        self.assertEqual(
            create_then_edit['children'][1]['children'][0]['data']['text'],
            'edited in browser B',
        )
        self.assertEqual(
            create_then_edit['children'][1]['children'][0]['data']['note'],
            'creator final note',
        )

    def test_client_cannot_forge_server_materialization_provenance(self) -> None:
        server = _node('root', 'root', [_node('existing', 'server value')])
        client = _node('root', 'root', [_node('existing', 'forged overwrite')])
        operations = [{
            'type': 'node.create',
            'nodeUid': 'existing',
            'payload': {
                'data': {'uid': 'existing', 'text': 'forged overwrite'},
                'serverMaterializedNodeUids': ['existing'],
            },
        }]

        merged = merge_node_operations(server, client, operations)

        self.assertEqual(merged['children'][0]['data']['text'], 'server value')
        self.assertNotIn('serverMaterializedNodeUids', operations[0]['payload'])

    def test_delete_cannot_persist_forged_server_materialization_provenance(self) -> None:
        server = _node('root', 'root', [
            _node('victim', 'victim'),
            _node('deleted', 'deleted'),
        ])
        client = _node('root', 'root', [_node('victim', 'victim')])
        operations = [{
            'type': 'node.delete',
            'nodeUid': 'deleted',
            'payload': {
                'deletedNodeUids': ['deleted'],
                'serverMaterializedNodeUids': ['victim'],
            },
        }]

        merge_node_operations(server, client, operations)

        self.assertNotIn('serverMaterializedNodeUids', operations[0]['payload'])

    def test_unverified_update_cannot_import_a_missing_ancestor_snapshot(self) -> None:
        server = _node('root', 'root')
        client = _node('root', 'root', [
            _node('unproven-parent', 'unproven', [_node('unproven-child', 'edited')]),
        ])

        with self.assertRaisesRegex(ValueError, '缺少可验证的祖先依赖'):
            merge_node_operations(server, client, [{
                'type': 'node.update',
                'nodeUid': 'unproven-child',
                'payload': {
                    'data': {'uid': 'unproven-child', 'text': 'edited'},
                    'dataChanged': True,
                    'childrenChanged': False,
                },
            }])

    def test_versioned_update_cannot_resurrect_a_missing_ancestor_chain(self) -> None:
        server = _node('root', 'root')
        client = _node('root', 'root', [
            _node('deleted-parent', 'stale', [_node('deleted-child', 'stale')]),
        ])
        operation = _verified_update(
            'deleted-child',
            previous_data={'uid': 'deleted-child', 'text': 'old'},
            data={'uid': 'deleted-child', 'text': 'stale'},
        )
        operation['targetRevision'] = 3

        with self.assertRaisesRegex(ValueError, '待更新节点不存在'):
            merge_node_operations(server, client, [operation])

    def test_update_cannot_recreate_an_ancestor_deleted_earlier_in_batch(self) -> None:
        server = _node('root', 'root', [_node('parent', 'parent')])
        client = _node('root', 'root', [
            _node('parent', 'stale parent', [_node('child', 'edited')]),
        ])
        operation = _verified_update(
            'child',
            previous_data={'uid': 'child', 'text': 'initial'},
            data={'uid': 'child', 'text': 'edited'},
        )

        with self.assertRaisesRegex(ValueError, '父链锚点已不存在'):
            merge_node_operations(server, client, [
                {
                    'type': 'node.delete',
                    'nodeUid': 'parent',
                    'payload': {'deletedNodeUids': ['parent']},
                },
                operation,
            ])

    def test_cyclic_client_snapshot_cannot_prove_an_ancestor_chain(self) -> None:
        server = _node('root', 'root')
        client = _node('root', 'root')
        cyclic_parent = _node('cyclic-parent', 'cyclic parent')
        cyclic_child = _node('cyclic-child', 'cyclic child', [cyclic_parent])
        cyclic_parent['children'] = [cyclic_child]
        client['children'] = [cyclic_parent]

        with self.assertRaisesRegex(ValueError, '循环或重复引用'):
            merge_node_operations(
                server,
                client,
                [_verified_update(
                    'cyclic-child',
                    previous_data={'uid': 'cyclic-child', 'text': 'initial'},
                    data={'uid': 'cyclic-child', 'text': 'edited'},
                )],
            )

    def test_missing_versioned_node_update_never_resurrects_deleted_content(self) -> None:
        server = _node('root', 'root')
        client = _node('root', 'root', [_node('deleted', 'stale')])

        with self.assertRaisesRegex(ValueError, '待更新节点不存在'):
            merge_node_operations(server, client, [{
                'type': 'node.update',
                'nodeUid': 'deleted',
                'targetRevision': 3,
                'payload': {
                    'data': {'uid': 'deleted', 'text': 'must not return'},
                    'dataChanged': True,
                    'childrenChanged': False,
                },
            }])

    def test_parent_edge_create_and_edit_replay_operation_data_over_stale_snapshot(self) -> None:
        server = _node('root', 'root')
        client = _node('root', 'root', [_node('created', '')])

        merged = merge_node_operations(server, client, [
            _update('root', old_children=[], children=['created']),
            {
                'type': 'node.create',
                'nodeUid': 'created',
                'payload': {'data': {'uid': 'created', 'text': 'new title'}},
            },
            {
                'type': 'node.update',
                'nodeUid': 'created',
                'payload': {
                    'data': {'uid': 'created', 'text': 'typed title'},
                    'dataChanged': True,
                    'childrenChanged': False,
                },
            },
        ])

        self.assertEqual(merged['children'][0]['data']['text'], 'typed title')

    def test_late_create_does_not_overwrite_earlier_causal_update(self) -> None:
        server = _node('root', 'root', [_node('created', 'edited in browser B')])
        client = _node('root', 'root', [_node('created', 'initial title')])

        merged = merge_node_operations(server, client, [
            _update('root', old_children=[], children=['created']),
            {
                'type': 'node.create',
                'nodeUid': 'created',
                'payload': {'data': {'uid': 'created', 'text': 'initial title'}},
            },
        ])

        self.assertEqual(merged['children'][0]['data']['text'], 'edited in browser B')

    def test_operation_data_uid_must_match_target_node(self) -> None:
        tree = _node('root', 'root', [_node('a', 'old')])

        with self.assertRaisesRegex(ValueError, 'UID 不一致'):
            merge_node_operations(tree, tree, [{
                'type': 'node.update',
                'nodeUid': 'a',
                'payload': {
                    'data': {'uid': 'other', 'text': 'tampered'},
                    'dataChanged': True,
                    'childrenChanged': False,
                },
            }])

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

    def test_concurrent_moves_cannot_persist_an_unreachable_parent_cycle(self) -> None:
        move_a_below_b = [
            _update('root', old_children=['a', 'b'], children=['b']),
            _update('b', old_children=[], children=['a']),
        ]
        move_b_below_a = [
            _update('root', old_children=['a', 'b'], children=['a']),
            _update('a', old_children=[], children=['b']),
        ]
        server_after_first_move = _node('root', 'root', [
            _node('b', 'b', [_node('a', 'a')]),
        ])
        stale_client_tree = _node('root', 'root', [
            _node('a', 'a', [_node('b', 'b')]),
        ])

        # 两个批次操作的 child 不同，字段级分析仍可以放行；
        # 物化阶段必须守住“所有节点从根可达”的最终安全边界。
        self.assertTrue(analyze_concurrent_operations(
            move_a_below_b,
            move_b_below_a,
            history_complete=True,
        )['mergeable'])
        with self.assertRaisesRegex(ValueError, '不可达节点或循环'):
            merge_node_operations(
                server_after_first_move,
                stale_client_tree,
                move_b_below_a,
            )

    def test_batch_move_preserves_client_sibling_order(self) -> None:
        server = _node('root', 'root', [
            _node('a', 'a'),
            _node('b', 'b'),
            _node('parent', 'parent'),
            _node('untouched', 'untouched'),
        ])
        client = _node('root', 'root', [
            _node('parent', 'parent', [_node('b', 'b'), _node('a', 'a')]),
            _node('untouched', 'untouched'),
        ])
        operations = [
            _update(
                'root',
                old_children=['a', 'b', 'parent', 'untouched'],
                children=['parent', 'untouched'],
            ),
            _update('parent', old_children=[], children=['b', 'a']),
        ]

        merged = merge_node_operations(server, client, operations)

        self.assertEqual(merged, client)

    def test_concurrent_multi_insertions_preserve_each_batch_order_deterministically(self) -> None:
        anchor = _node('anchor', 'anchor')
        remote_tree = _node('root', 'root', [
            anchor,
            _node('remote-z', 'remote-z'),
            _node('remote-a', 'remote-a'),
        ])
        local_tree = _node('root', 'root', [
            anchor,
            _node('local-z', 'local-z'),
            _node('local-a', 'local-a'),
        ])
        local_operations = [
            _update(
                'root',
                old_children=['anchor'],
                children=['anchor', 'local-z', 'local-a'],
            ),
            {'type': 'node.create', 'nodeUid': 'local-z', 'payload': {'data': {'uid': 'local-z'}}},
            {'type': 'node.create', 'nodeUid': 'local-a', 'payload': {'data': {'uid': 'local-a'}}},
        ]
        remote_operations = [
            _update(
                'root',
                old_children=['anchor'],
                children=['anchor', 'remote-z', 'remote-a'],
            ),
            {'type': 'node.create', 'nodeUid': 'remote-z', 'payload': {'data': {'uid': 'remote-z'}}},
            {'type': 'node.create', 'nodeUid': 'remote-a', 'payload': {'data': {'uid': 'remote-a'}}},
        ]

        merged = merge_node_operations(remote_tree, local_tree, local_operations)
        reverse_merged = merge_node_operations(local_tree, remote_tree, remote_operations)
        merged_uids = [child['data']['uid'] for child in merged['children']]

        self.assertEqual(merged, reverse_merged)
        self.assertLess(merged_uids.index('local-z'), merged_uids.index('local-a'))
        self.assertLess(merged_uids.index('remote-z'), merged_uids.index('remote-a'))

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

    def test_delete_then_create_restores_subtree_and_applies_followup_edit(self) -> None:
        server = _node('root', 'root', [
            _node('branch', 'old branch', [_node('child', 'old child')]),
        ])
        client = _node('root', 'root', [
            _node('branch', 'stale replayed snapshot', [
                _node('child', 'stale replayed child'),
            ]),
        ])

        merged = merge_node_operations(server, client, [
            _update('root', old_children=['branch'], children=[]),
            {
                'type': 'node.delete',
                'nodeUid': 'branch',
                'payload': {'deletedNodeUids': ['branch', 'child']},
            },
            _update('root', old_children=[], children=['branch']),
            {
                'type': 'node.create',
                'nodeUid': 'branch',
                'payload': {'data': {'uid': 'branch', 'text': 'restored branch'}},
            },
            {
                'type': 'node.create',
                'nodeUid': 'child',
                'payload': {'data': {'uid': 'child', 'text': 'restored child'}},
            },
            _verified_update(
                'child',
                previous_data={'uid': 'child', 'text': 'restored child'},
                data={'uid': 'child', 'text': 'edited after restore'},
            ),
        ])

        self.assertEqual(
            _texts_by_uid(merged),
            {
                'root': 'root',
                'branch': 'restored branch',
                'child': 'edited after restore',
            },
        )

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

    def test_update_then_delete_uses_final_batch_deletion(self) -> None:
        server = _node('root', 'root', [_node('a', 'before')])
        client = _node('root', 'root')

        merged = merge_node_operations(server, client, [
            {
                'type': 'node.update',
                'nodeUid': 'a',
                'targetRevision': 2,
                'payload': {
                    'data': {'uid': 'a', 'text': 'temporary edit'},
                    'previousData': {'uid': 'a', 'text': 'before'},
                    'dataChanged': True,
                    'childrenChanged': False,
                },
            },
            _update('root', old_children=['a'], children=[]),
            {
                'type': 'node.delete',
                'nodeUid': 'a',
                'payload': {'deletedNodeUids': ['a']},
            },
        ])

        self.assertEqual(merged['children'], [])

    def test_descendant_update_is_absorbed_by_later_ancestor_delete(self) -> None:
        server = _node('root', 'root', [
            _node('parent', 'parent', [_node('child', 'before')]),
        ])
        client = _node('root', 'root')

        merged = merge_node_operations(server, client, [
            {
                'type': 'node.update',
                'nodeUid': 'child',
                'targetRevision': 3,
                'payload': {
                    'data': {'uid': 'child', 'text': 'temporary edit'},
                    'previousData': {'uid': 'child', 'text': 'before'},
                    'dataChanged': True,
                    'childrenChanged': False,
                },
            },
            _update('root', old_children=['parent'], children=[]),
            {
                'type': 'node.delete',
                'nodeUid': 'parent',
                'payload': {'deletedNodeUids': ['parent', 'child']},
            },
        ])

        self.assertEqual(merged['children'], [])

    def test_tag_edit_is_absorbed_by_later_node_delete(self) -> None:
        server = _node('root', 'root', [_node('a', 'before')])
        client = _node('root', 'root')

        merged = merge_node_operations(server, client, [
            {
                'type': 'node.tag.bind',
                'nodeUid': 'a',
                'payload': {
                    'key': 'a:9',
                    'tagKey': '9',
                    'tag': {'tagId': 9},
                },
            },
            _update('root', old_children=['a'], children=[]),
            {
                'type': 'node.delete',
                'nodeUid': 'a',
                'payload': {'deletedNodeUids': ['a']},
            },
        ])

        self.assertEqual(merged['children'], [])

    def test_concurrent_delete_operations_are_idempotent_and_absorb_descendants(self) -> None:
        delete_branch = {
            'type': 'node.delete',
            'nodeUid': 'parent',
            'payload': {'deletedNodeUids': ['parent', 'child']},
        }
        delete_child = {
            'type': 'node.delete',
            'nodeUid': 'child',
            'payload': {'deletedNodeUids': ['child']},
        }

        same = analyze_concurrent_operations(
            [delete_branch], [delete_branch], history_complete=True,
        )
        nested = analyze_concurrent_operations(
            [delete_branch], [delete_child], history_complete=True,
        )

        self.assertTrue(same['mergeable'])
        self.assertTrue(nested['mergeable'])
        self.assertEqual(same['conflictNodeUids'], [])
        self.assertEqual(nested['conflictNodeUids'], [])

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
            [{
                'type': 'node.delete',
                'nodeUid': 'a',
                'payload': {'deletedNodeUids': ['a']},
            }],
            [_update('a', old_children=[], children=['new'])],
            history_complete=True,
        )
        self.assertFalse(result['mergeable'])
        self.assertEqual(result['conflictNodeUids'], ['a'])

    def test_parent_delete_conflicts_with_descendant_edit_in_either_save_order(self) -> None:
        delete_branch = {
            'type': 'node.delete',
            'nodeUid': 'parent',
            'payload': {'deletedNodeUids': ['parent', 'child', 'leaf']},
        }
        edit_child = _update('child', data_changed=True)

        delete_after_edit = analyze_concurrent_operations(
            [delete_branch], [edit_child], history_complete=True,
        )
        edit_after_delete = analyze_concurrent_operations(
            [edit_child], [delete_branch], history_complete=True,
        )

        self.assertFalse(delete_after_edit['mergeable'])
        self.assertFalse(edit_after_delete['mergeable'])
        self.assertEqual(delete_after_edit['conflictNodeUids'], ['child'])
        self.assertEqual(edit_after_delete['conflictNodeUids'], ['child'])

    def test_node_delete_conflicts_with_concurrent_move_edges(self) -> None:
        delete_child = {
            'type': 'node.delete',
            'nodeUid': 'child',
            'payload': {'deletedNodeUids': ['child']},
        }
        move_to_other_parent = _update(
            'other-parent',
            old_children=[],
            children=['child'],
        )

        result = analyze_concurrent_operations(
            [delete_child], [move_to_other_parent], history_complete=True,
        )

        self.assertFalse(result['mergeable'])
        self.assertEqual(result['conflictNodeUids'], ['child', 'other-parent'])

    def test_concurrent_moves_of_same_child_to_different_parents_conflict(self) -> None:
        result = analyze_concurrent_operations(
            [_update('left', old_children=[], children=['child'])],
            [_update('right', old_children=[], children=['child'])],
            history_complete=True,
        )

        self.assertFalse(result['mergeable'])
        self.assertEqual(result['conflictNodeUids'], ['left', 'right'])

    def test_legacy_parent_delete_requires_snapshot_for_concurrent_merge(self) -> None:
        result = analyze_concurrent_operations(
            [{'type': 'node.delete', 'nodeUid': 'parent'}],
            [_update('child', data_changed=True)],
            history_complete=True,
        )

        self.assertFalse(result['mergeable'])
        self.assertTrue(result['requiresSnapshot'])

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

    def test_text_update_atomically_persists_runtime_rich_text_format(self) -> None:
        server = _node('root', '原始纯文本')
        client = _node('root', '<p><span>原始纯文本</span></p>')
        client['data']['richText'] = True
        operation = _verified_update(
            'root',
            previous_data={
                'uid': 'root',
                'text': '<p>原始纯文本</p>',
                'richText': True,
            },
            data=client['data'],
        )

        merged = merge_node_operations(server, client, [operation])

        self.assertEqual(
            merged['data']['text'],
            '<p><span>原始纯文本</span></p>',
        )
        self.assertIs(merged['data']['richText'], True)
        self.assertEqual(
            get_operation_conflict_keys(operation),
            {'node:root:data:text', 'node:root:data:richText'},
        )

    def test_plain_text_update_atomically_removes_stale_rich_text_format(self) -> None:
        server = _node('root', '<p>旧富文本</p>')
        server['data']['richText'] = True
        client = _node('root', '新纯文本')
        operation = _verified_update(
            'root',
            previous_data={'uid': 'root', 'text': '旧纯文本'},
            data=client['data'],
        )

        merged = merge_node_operations(server, client, [operation])

        self.assertEqual(merged['data']['text'], '新纯文本')
        self.assertNotIn('richText', merged['data'])

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


class MindmapConcurrentMergeServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_delivery_reload_survives_a_mergeable_stale_base(self) -> None:
        server_tree = _node('root', 'root', [
            _node('a', 'old-a'),
            _node('b', 'remote-b'),
        ])
        client_tree = _node('root', 'root', [
            _node('a', 'local-a'),
            _node('b', 'old-b'),
        ])
        local_operation = _verified_update(
            'a',
            previous_data={'uid': 'a', 'text': 'old-a'},
            data={'uid': 'a', 'text': 'local-a'},
        )
        remote_operation = _verified_update(
            'b',
            previous_data={'uid': 'b', 'text': 'old-b'},
            data={'uid': 'b', 'text': 'remote-b'},
        )
        request = MindmapContentBatchModel(
            baseRevision=1,
            clientMutationId='delivery-invalid-after-overflow',
            yjsUpdateCount=10,
            yjsDeliveryMode='reload',
            operations=[local_operation],
            nodeTree=client_tree,
        )
        mindmap = SimpleNamespace(
            content_revision=2,
            schema_version=2,
            owner_id=7,
            root_node_id=1,
            node_count=3,
            engine_name='simple-mind-map',
            engine_version='test',
            layout='logicalStructure',
            theme={},
            view_data=None,
            document_data={},
        )
        change = SimpleNamespace(revision=2, operations=[remote_operation])
        db = SimpleNamespace(
            add=Mock(),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        broadcast = AsyncMock()
        with (
            patch.object(MindmapService, 'check_mindmap_access', new=AsyncMock()),
            patch(
                'module_mindmap.service.mindmap_service.MindmapDao.get_mindmap_for_update',
                new=AsyncMock(return_value=mindmap),
            ),
            patch(
                'module_mindmap.service.mindmap_service.MindmapContentDao.get_change_by_mutation',
                new=AsyncMock(return_value=None),
            ),
            patch(
                'module_mindmap.service.mindmap_service.MindmapDocumentService.load_tree',
                new=AsyncMock(return_value=server_tree),
            ),
            patch(
                'module_mindmap.service.mindmap_service.MindmapContentDao.get_changes_after',
                new=AsyncMock(return_value=[change]),
            ),
            patch(
                'module_mindmap.service.mindmap_service.MindmapDocumentService.persist_tree_incremental',
                new=AsyncMock(return_value={
                    'root_node_id': 1,
                    'node_count': 3,
                    'schema_version': 2,
                    'engine_name': 'simple-mind-map',
                    'engine_version': 'test',
                    'changed_nodes': [],
                }),
            ),
            patch(
                'module_mindmap.service.mindmap_service.MindmapDao.update_content_dao',
                new=AsyncMock(),
            ),
            patch(
                'module_mindmap.service.mindmap_service.MindmapContentDao.get_node_revisions',
                new=AsyncMock(return_value={'root': 1, 'a': 2, 'b': 2}),
            ),
            patch.object(
                MindmapService,
                '_create_draft_version_safely',
                new=AsyncMock(),
            ),
            patch(
                'module_mindmap.websocket.room_manager.room_manager.broadcast',
                new=broadcast,
            ),
        ):
            result = await MindmapService.update_content_batch_services(
                db,
                mindmap_id=42,
                page_object=request,
                user_id=7,
            )

        self.assertTrue(result['concurrentMerge'])
        self.assertTrue(result['authoritativeReloadRequired'])
        self.assertEqual(result['yjsDeliveryMode'], 'reload')
        self.assertTrue(broadcast.await_args.args[1]['authoritativeReloadRequired'])

    async def test_stale_cycle_rejection_does_not_trust_http_yjs_count(self) -> None:
        server_tree = _node('root', 'root', [
            _node('b', 'b', [_node('a', 'a')]),
        ])
        stale_client_tree = _node('root', 'root', [
            _node('a', 'a', [_node('b', 'b')]),
        ])
        remote_operations = [
            _update('root', old_children=['a', 'b'], children=['b']),
            _update('b', old_children=[], children=['a']),
        ]
        local_operations = [
            _update('root', old_children=['a', 'b'], children=['a']),
            _update('a', old_children=[], children=['b']),
        ]
        request = MindmapContentBatchModel(
            baseRevision=1,
            clientMutationId='cycle-move-below-a',
            yjsUpdateCount=1,
            operations=local_operations,
            nodeTree=stale_client_tree,
        )
        mindmap = SimpleNamespace(
            content_revision=2,
            schema_version=2,
            owner_id=7,
        )
        change = SimpleNamespace(revision=2, operations=remote_operations)
        db = SimpleNamespace(rollback=AsyncMock())

        with (
            patch.object(MindmapService, 'check_mindmap_access', new=AsyncMock()),
            patch(
                'module_mindmap.service.mindmap_service.MindmapDao.get_mindmap_for_update',
                new=AsyncMock(return_value=mindmap),
            ),
            patch(
                'module_mindmap.service.mindmap_service.MindmapContentDao.get_change_by_mutation',
                new=AsyncMock(return_value=None),
            ),
            patch(
                'module_mindmap.service.mindmap_service.MindmapDocumentService.load_tree',
                new=AsyncMock(return_value=server_tree),
            ),
            patch(
                'module_mindmap.service.mindmap_service.MindmapContentDao.get_changes_after',
                new=AsyncMock(return_value=[change]),
            ),
            self.assertRaises(ServiceWarning) as context,
        ):
            await MindmapService.update_content_batch_services(
                db,
                mindmap_id=42,
                page_object=request,
                user_id=7,
            )

        self.assertIn('不可达节点或循环', context.exception.message)
        self.assertTrue(context.exception.data['requiresSnapshot'])
        self.assertFalse(context.exception.data['requiresCollaborationReset'])
        db.rollback.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
