"""脑图 WebSocket 消息协议边界测试。"""

import asyncio
import base64
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import WebSocketDisconnect

from exceptions.exception import ServiceException
from module_mindmap.service.mindmap_document_service import STRUCTURED_CONTENT_CORRUPT_MESSAGE
from module_mindmap.websocket.mindmap_ws import (
    MAX_AWARENESS_NODE_COUNT,
    MAX_YJS_PATCH_BYTES,
    WS_RETRY_LATER_CLOSE_CODE,
    WebSocketTrafficBudget,
    acquire_ws_seed_lease,
    are_yjs_state_replacements_authorized,
    build_ws_heartbeat_payload,
    build_yjs_sync_init_payload,
    can_forward_ws_authoritative_seed,
    decode_base64_payload,
    get_authorized_ws_heartbeat_revision,
    get_authorized_ws_revision_fence_payload,
    get_ws_access_error_message,
    get_ws_auth_error_payload,
    get_ws_auth_recheck_action,
    get_ws_client_message_type,
    get_ws_encoded_payload_size,
    get_ws_invalid_message_payload,
    get_ws_rate_limit_payload,
    get_ws_revision_fence_payload,
    get_yjs_update_payload_limit,
    mindmap_websocket_endpoint,
    normalize_awareness_editing_node_uid,
    normalize_awareness_node_uids,
    normalize_client_mutation_id,
    normalize_mutation_update_sequence,
    normalize_node_edit_lease_request_id,
    normalize_node_edit_lease_uid,
    normalize_ws_capabilities,
    normalize_yjs_lineage_id,
    normalize_yjs_patch,
    persist_authorized_yjs_state,
)
from module_mindmap.websocket.room_manager import (
    COLLABORATION_MUTATION_BARRIER_CAPABILITY,
    CONDITIONAL_NODE_PATCH_CAPABILITY,
    CROSS_NODE_CRDT_V2_CAPABILITY,
    NODE_EDIT_LEASE_CAPABILITY,
    NODE_EDIT_LEASE_RENEWAL_CAPABILITY,
    STRUCTURED_NODE_PATCH_CAPABILITY,
    YJS_CHECKPOINT_CAPABILITY,
    YJS_LINEAGE_CAPABILITY,
    YJS_MUTATION_SEQUENCE_CAPABILITY,
    YJS_SOURCE_CAS_CAPABILITY,
)
from module_mindmap.websocket.ws_auth import WsAuthenticationError
from module_mindmap.websocket.yjs_doc import get_yjs_state_digest

ROOM_JOIN_CAPABILITIES_ARGUMENT_INDEX = 3


class _AuthFailureWebSocket:
    def __init__(self) -> None:
        self.app = SimpleNamespace(state=SimpleNamespace(redis=object()))
        self.accepted = False
        self.sent: list[dict] = []
        self.close_codes: list[int] = []

    async def accept(self) -> None:
        self.accepted = True

    async def receive_json(self) -> dict:
        return {'type': 'auth', 'token': 'opaque-token'}

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def close(self, code: int) -> None:
        self.close_codes.append(code)


class _ScriptedWebSocket(_AuthFailureWebSocket):
    def __init__(self, messages: list[dict]) -> None:
        super().__init__()
        self.messages = list(messages)

    async def receive_json(self) -> dict:
        if self.messages:
            return self.messages.pop(0)
        raise WebSocketDisconnect


class _SessionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_args: object) -> None:
        return None


class _RollbackExpiringMindmap:
    """模拟 AsyncSession rollback 后 ORM 属性过期且不能隐式刷新。"""

    def __init__(self, content_revision: int) -> None:
        self._content_revision = content_revision
        self.session_closed = False

    @property
    def content_revision(self) -> int:
        if self.session_closed:
            raise RuntimeError('detached ORM entity attempted implicit IO')
        return self._content_revision


class _RollbackExpiringSessionContext:
    def __init__(self, mindmap: _RollbackExpiringMindmap) -> None:
        self.mindmap = mindmap

    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_args: object) -> None:
        self.mindmap.session_closed = True


def _create_endpoint_room_manager(
    websocket: _AuthFailureWebSocket,
    *,
    fail_message_type: str | None = None,
    required_write_capabilities: set[str] | None = None,
) -> SimpleNamespace:
    active = False
    content_revision = 1
    disconnect_persistence_blocked = False
    required_capabilities = set(required_write_capabilities or ())

    async def send_to(_websocket: object, payload: dict) -> bool:
        websocket.sent.append(payload)
        return payload.get('type') != fail_message_type

    async def join(*args: object, **kwargs: object) -> bool:
        nonlocal active
        active = True
        capabilities = (
            set(args[ROOM_JOIN_CAPABILITIES_ARGUMENT_INDEX])
            if len(args) > ROOM_JOIN_CAPABILITIES_ARGUMENT_INDEX
            else set()
        )
        return (
            kwargs.get('can_edit') is True
            and required_capabilities.issubset(capabilities)
        )

    async def leave(*_args: object, **_kwargs: object) -> None:
        nonlocal active
        active = False

    def set_content_revision(
        _mindmap_id: int,
        revision: int,
        **_kwargs: object,
    ) -> None:
        nonlocal content_revision
        content_revision = revision

    def block_disconnect_persistence(_websocket: object) -> None:
        nonlocal disconnect_persistence_blocked
        disconnect_persistence_blocked = True

    def consume_disconnect_persistence_permission(_websocket: object) -> bool:
        nonlocal disconnect_persistence_blocked
        allowed = not disconnect_persistence_blocked
        disconnect_persistence_blocked = False
        return allowed

    async def require_write_capability(
        _mindmap_id: int,
        capability: str,
    ) -> bool:
        required_capabilities.add(capability)
        return True

    async def get_required_write_capabilities(_mindmap_id: int) -> set[str]:
        return set(required_capabilities)

    async def get_missing_write_capabilities(
        _mindmap_id: int,
        capabilities: set[str],
    ) -> set[str]:
        return required_capabilities - capabilities

    return SimpleNamespace(
        send_to=AsyncMock(side_effect=send_to),
        join=AsyncMock(side_effect=join),
        leave=AsyncMock(side_effect=leave),
        set_content_revision=Mock(side_effect=set_content_revision),
        set_content_lineage=Mock(return_value=True),
        is_content_lineage_compatible=Mock(return_value=True),
        has_content_lineage=Mock(return_value=True),
        set_content_lineage_digest=Mock(return_value=True),
        clear_content_lineage=Mock(return_value=True),
        get_content_lineage_generation=Mock(return_value=0),
        is_content_lineage_generation_current=Mock(return_value=True),
        reconcile_persisted_content_lineage_digest=Mock(return_value=(True, False)),
        repair_content_lineage_fence_from_persisted=AsyncMock(
            side_effect=lambda _mindmap_id, _revision, digest, **_kwargs: (
                True,
                digest,
            ),
        ),
        verify_content_lineage_fence=AsyncMock(return_value=True),
        disconnect_stale_lineage_peers=AsyncMock(),
        get_content_revision=lambda _mindmap_id: content_revision,
        is_current_revision=lambda _mindmap_id, revision: revision == content_revision,
        get_room_users=AsyncMock(return_value=[]),
        broadcast=AsyncMock(),
        broadcast_with_lineage_fence=AsyncMock(return_value=True),
        broadcast_checkpoint=AsyncMock(return_value=True),
        acquire_seed_lease=AsyncMock(return_value=True),
        consume_seed_lease=AsyncMock(return_value=True),
        acquire_node_edit_lease=AsyncMock(return_value=True),
        renew_node_edit_lease=AsyncMock(return_value=True),
        release_node_edit_lease=AsyncMock(return_value=True),
        release_connection_node_edit_leases=AsyncMock(),
        owns_node_edit_lease=AsyncMock(return_value=True),
        is_collaboration_mutation_allowed=AsyncMock(return_value=True),
        record_collaboration_mutation_checkpoint=AsyncMock(return_value=True),
        acknowledge_collaboration_mutation_barrier=AsyncMock(return_value=True),
        require_write_capability=AsyncMock(side_effect=require_write_capability),
        get_required_write_capabilities=AsyncMock(
            side_effect=get_required_write_capabilities,
        ),
        get_missing_write_capabilities=AsyncMock(
            side_effect=get_missing_write_capabilities,
        ),
        block_disconnect_persistence=Mock(side_effect=block_disconnect_persistence),
        notify_and_disconnect_user=AsyncMock(),
        consume_disconnect_persistence_permission=Mock(
            side_effect=consume_disconnect_persistence_permission,
        ),
        is_connection_active=lambda _websocket: active,
        is_connection_write_enabled=lambda _mindmap_id, _websocket: active,
    )


async def _run_scripted_endpoint(
    websocket: _ScriptedWebSocket,
    manager: SimpleNamespace,
    *,
    load_snapshot: tuple[int | None, dict[str, bytes], dict[str, str]],
    save_state: AsyncMock | None = None,
) -> AsyncMock:
    mindmap = SimpleNamespace(content_revision=4, schema_version=2, status=0)
    save_state = save_state or AsyncMock(return_value=True)
    load_state = AsyncMock(return_value=load_snapshot)
    manager._test_load_state = load_state
    with (
        patch(
            'module_mindmap.websocket.mindmap_ws.AsyncSessionLocal',
            new=Mock(side_effect=_SessionContext),
        ),
        patch(
            'module_mindmap.websocket.mindmap_ws.validate_ws_token',
            new=AsyncMock(return_value={'id': 7, 'name': 'Editor'}),
        ),
        patch(
            'module_mindmap.websocket.mindmap_ws.MindmapService.resolve_mindmap_access',
            new=AsyncMock(return_value=(mindmap, 1, False)),
        ),
        patch(
            'module_mindmap.websocket.mindmap_ws.MindmapDao.get_migration_status',
            new=AsyncMock(return_value='completed'),
        ),
        patch(
            'module_mindmap.websocket.mindmap_ws.MindmapDocumentService.load_tree',
            new=AsyncMock(return_value={}),
        ),
        patch(
            'module_mindmap.websocket.mindmap_ws.YjsDocManager.load_state_snapshot_with_lineages',
            new=load_state,
        ),
        patch(
            'module_mindmap.websocket.mindmap_ws.YjsDocManager.save_state',
            new=save_state,
        ),
        patch(
            'module_mindmap.websocket.mindmap_ws.MindmapService.check_mindmap_access',
            new=AsyncMock(return_value=mindmap),
        ),
        patch(
            'module_mindmap.websocket.mindmap_ws.reconcile_persisted_lineage_fence',
            new=AsyncMock(return_value=True),
        ),
        patch('module_mindmap.websocket.mindmap_ws.room_manager', new=manager),
    ):
        await mindmap_websocket_endpoint(websocket, 7)
    return save_state


class MindmapWebsocketProtocolTest(unittest.TestCase):
    def test_connection_traffic_budget_uses_exact_sliding_windows(self) -> None:
        now = 100.0
        budget = WebSocketTrafficBudget(
            message_limit=3,
            awareness_limit=2,
            payload_limit=10,
            window_seconds=5,
            clock=lambda: now,
        )

        self.assertTrue(budget.allow_message('update'))
        self.assertTrue(budget.allow_message('awareness'))
        self.assertTrue(budget.allow_message('awareness'))
        self.assertFalse(budget.allow_message('update'))
        self.assertTrue(budget.allow_payload(6))
        self.assertFalse(budget.allow_payload(5))

        now += 5
        self.assertTrue(budget.allow_message('update'))
        self.assertTrue(budget.allow_payload(10))

    def test_awareness_budget_is_independent_from_normal_message_burst(self) -> None:
        budget = WebSocketTrafficBudget(
            message_limit=10,
            awareness_limit=1,
            payload_limit=100,
            clock=lambda: 1,
        )

        self.assertTrue(budget.allow_message('awareness'))
        self.assertFalse(budget.allow_message('awareness'))
        self.assertTrue(budget.allow_message('update'))

    def test_encoded_payload_size_and_rate_error_are_stable(self) -> None:
        self.assertEqual(get_ws_encoded_payload_size({
            'update': '1234',
            'state': '12345678',
        }, 'update'), 12)
        self.assertEqual(get_ws_encoded_payload_size({
            'update': 'ignored',
            'state': '12345678',
        }, 'checkpoint'), 8)
        self.assertEqual(get_ws_rate_limit_payload(), {
            'type': 'protocol_error',
            'code': 'rate_limited',
            'message': '协作消息发送过于频繁，请稍后重试',
        })

    def test_client_mutation_id_correlation_is_bounded(self) -> None:
        self.assertEqual(normalize_client_mutation_id(' mutation-1 '), 'mutation-1')
        self.assertIsNone(normalize_client_mutation_id(''))
        self.assertIsNone(normalize_client_mutation_id('x' * 101))
        self.assertIsNone(normalize_client_mutation_id(7))

    def test_yjs_lineage_uses_utf8_byte_limit(self) -> None:
        self.assertEqual(normalize_yjs_lineage_id(' lineage-1 '), 'lineage-1')
        self.assertEqual(normalize_yjs_lineage_id('界' * 42), '界' * 42)
        self.assertIsNone(normalize_yjs_lineage_id('界' * 43))

    def test_mutation_update_sequence_requires_a_bounded_strict_integer(self) -> None:
        self.assertEqual(normalize_mutation_update_sequence(1), 1)
        self.assertEqual(normalize_mutation_update_sequence(10000), 10000)
        for invalid in (0, 10001, True, '1', None):
            self.assertIsNone(normalize_mutation_update_sequence(invalid))

    def test_only_declared_json_object_messages_enter_protocol_handlers(self) -> None:
        for payload in (None, [], 'update', 1, {'type': None}, {'type': 'future'}):
            with self.subTest(payload=payload):
                self.assertIsNone(get_ws_client_message_type(payload))

        self.assertEqual(
            get_ws_client_message_type({'type': 'update', 'update': 'YWJj'}),
            'update',
        )
        self.assertEqual(
            get_ws_client_message_type({'type': 'node_edit_lease_acquire'}),
            'node_edit_lease_acquire',
        )
        self.assertEqual(
            get_ws_client_message_type({'type': 'node_edit_lease_release'}),
            'node_edit_lease_release',
        )
        self.assertIsNone(
            get_ws_client_message_type({'type': 'discard_source', 'contentRevision': 3})
        )
        self.assertEqual(get_ws_invalid_message_payload(), {
            'type': 'protocol_error',
            'code': 'invalid_message',
            'message': '协作消息格式或类型无效',
        })

    def test_all_shared_document_messages_use_the_same_revision_fence(self) -> None:
        current_revision = 9
        manager = SimpleNamespace(
            is_current_revision=lambda _mindmap_id, revision: revision == current_revision,
            get_content_revision=lambda _mindmap_id: current_revision,
        )

        self.assertIsNone(get_ws_revision_fence_payload(manager, 7, 9))
        self.assertEqual(get_ws_revision_fence_payload(manager, 7, 8), {
            'type': 'stale_state',
            'message': '协作状态已落后，正在合并服务器最新内容',
            'currentRevision': 9,
        })

    def test_heartbeat_exposes_the_database_revision_to_detect_lost_broadcasts(self) -> None:
        self.assertEqual(build_ws_heartbeat_payload(12), {
            'type': 'ping',
            'contentRevision': 12,
        })

    def test_heartbeat_freezes_revision_before_read_session_rolls_back(self) -> None:
        mindmap = _RollbackExpiringMindmap(12)
        with (
            patch(
                'module_mindmap.websocket.mindmap_ws.AsyncSessionLocal',
                return_value=_RollbackExpiringSessionContext(mindmap),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapService.resolve_mindmap_access',
                new=AsyncMock(return_value=(mindmap, True, None)),
            ) as resolve_access,
        ):
            revision = asyncio.run(
                get_authorized_ws_heartbeat_revision(
                    7,
                    9,
                    require_edit=True,
                )
            )

        self.assertTrue(mindmap.session_closed)
        self.assertEqual(revision, 12)
        resolve_access.assert_awaited_once_with(
            unittest.mock.ANY,
            7,
            9,
            require_edit=True,
            lock_for_session=False,
        )

    def test_sync_init_keeps_persisted_sources_aligned_with_states(self) -> None:
        payload = build_yjs_sync_init_payload(
            {
                'source-a': b'state-a',
                'source-b': b'state-b',
            },
            content_revision=12,
        )

        self.assertEqual(payload['type'], 'sync_init')
        self.assertEqual(payload['contentRevision'], 12)
        self.assertEqual(payload['stateSources'], ['source-a', 'source-b'])
        self.assertEqual(
            [base64.b64decode(state) for state in payload['states']],
            [b'state-a', b'state-b'],
        )
        self.assertEqual(payload['state'], payload['states'][-1])
        modern_payload = build_yjs_sync_init_payload(
            {'source-a': b'state-a', 'source-b': b'state-b'},
            content_revision=12,
            include_legacy_state=False,
        )
        self.assertNotIn('state', modern_payload)
        self.assertEqual(modern_payload['states'], payload['states'])
        self.assertIsNone(build_yjs_sync_init_payload({}, content_revision=12))

    def test_awareness_uids_are_deduplicated_bounded_and_sanitized(self) -> None:
        values = [' a ', 'a', '', None, True, 'x' * 65]
        values.extend(f'node-{index}' for index in range(MAX_AWARENESS_NODE_COUNT + 5))

        result = normalize_awareness_node_uids({'nodeUids': values})

        self.assertEqual(result[0], 'a')
        self.assertEqual(len(result), MAX_AWARENESS_NODE_COUNT)
        self.assertNotIn('x' * 65, result)

    def test_legacy_awareness_envelope_is_supported_without_trusting_user(self) -> None:
        result = normalize_awareness_node_uids({
            'update': {
                'nodeUids': ['root', 7],
                'user': {'id': 999, 'name': '伪造身份'},
            },
        })

        self.assertEqual(result, ['root', '7'])

    def test_invalid_awareness_payload_becomes_empty_selection(self) -> None:
        self.assertEqual(normalize_awareness_node_uids({'nodeUids': 'root'}), [])

    def test_awareness_editing_uid_is_a_strict_bounded_string(self) -> None:
        self.assertEqual(
            normalize_awareness_editing_node_uid({'editingNodeUid': ' child '}),
            'child',
        )
        self.assertEqual(
            normalize_awareness_editing_node_uid({
                'update': {'editingNodeUid': 'legacy-child'},
            }),
            'legacy-child',
        )
        for value in (7, True, '', 'x' * 65, None):
            self.assertEqual(
                normalize_awareness_editing_node_uid({'editingNodeUid': value}),
                '',
            )

    def test_node_edit_lease_identifiers_are_strict_and_bounded(self) -> None:
        self.assertEqual(normalize_node_edit_lease_uid(' child '), 'child')
        self.assertEqual(
            normalize_node_edit_lease_request_id(' request-1 '),
            'request-1',
        )
        for value in ('', 'x' * 65, 7, True, None):
            self.assertIsNone(normalize_node_edit_lease_uid(value))
        for value in ('', 'x' * 101, 7, True, None):
            self.assertIsNone(normalize_node_edit_lease_request_id(value))

    def test_only_supported_websocket_capabilities_are_negotiated(self) -> None:
        self.assertEqual(
            normalize_ws_capabilities([
                STRUCTURED_NODE_PATCH_CAPABILITY,
                CONDITIONAL_NODE_PATCH_CAPABILITY,
                YJS_CHECKPOINT_CAPABILITY,
                YJS_MUTATION_SEQUENCE_CAPABILITY,
                CROSS_NODE_CRDT_V2_CAPABILITY,
                NODE_EDIT_LEASE_CAPABILITY,
                NODE_EDIT_LEASE_RENEWAL_CAPABILITY,
                'future-unknown-capability',
                7,
            ]),
            {
                STRUCTURED_NODE_PATCH_CAPABILITY,
                CONDITIONAL_NODE_PATCH_CAPABILITY,
                YJS_CHECKPOINT_CAPABILITY,
                YJS_MUTATION_SEQUENCE_CAPABILITY,
                CROSS_NODE_CRDT_V2_CAPABILITY,
                NODE_EDIT_LEASE_CAPABILITY,
                NODE_EDIT_LEASE_RENEWAL_CAPABILITY,
            },
        )
        self.assertEqual(normalize_ws_capabilities('structured-node-patch-v1'), set())

    def test_websocket_access_error_distinguishes_corrupt_content_from_permission_denial(self) -> None:
        self.assertIn(
            '完整性校验失败',
            get_ws_access_error_message(ServiceException(message=STRUCTURED_CONTENT_CORRUPT_MESSAGE)),
        )
        self.assertEqual(
            get_ws_access_error_message(ServiceException(message='无编辑权限')),
            '无访问权限',
        )

    def test_auth_error_payload_classifies_retryable_failures_without_leaking_unknown_errors(self) -> None:
        retryable = get_ws_auth_error_payload(WsAuthenticationError(
            '认证服务暂时不可用，请稍后重试',
            code='auth_unavailable',
            retryable=True,
        ))
        unknown = get_ws_auth_error_payload(RuntimeError('database password=secret'))

        self.assertEqual(retryable['code'], 'auth_unavailable')
        self.assertTrue(retryable['retryable'])
        self.assertEqual(unknown['code'], 'auth_unavailable')
        self.assertTrue(unknown['retryable'])
        self.assertNotIn('password', unknown['message'])

    def test_auth_recheck_reconnects_temporary_failures_and_only_ends_revoked_sessions(self) -> None:
        temporary = WsAuthenticationError(
            '认证服务暂时不可用，请稍后重试',
            code='auth_unavailable',
            retryable=True,
        )
        revoked = WsAuthenticationError(
            '登录会话已失效，请重新登录',
            code='session_revoked',
        )

        self.assertIsNone(get_ws_auth_recheck_action(temporary, 7, 2))
        retry_payload, retry_close_code = get_ws_auth_recheck_action(temporary, 7, 3)
        self.assertEqual(retry_payload['type'], 'auth_error')
        self.assertTrue(retry_payload['retryable'])
        self.assertEqual(retry_close_code, WS_RETRY_LATER_CLOSE_CODE)

        access_payload, access_close_code = get_ws_auth_recheck_action(
            WsAuthenticationError(
                '权限校验服务暂时不可用，请稍后重试',
                code='access_check_unavailable',
                retryable=True,
            ),
            7,
            3,
        )
        self.assertEqual(access_payload['code'], 'access_check_unavailable')
        self.assertTrue(access_payload['retryable'])
        self.assertEqual(access_close_code, WS_RETRY_LATER_CLOSE_CODE)

        end_payload, end_close_code = get_ws_auth_recheck_action(revoked, 7, 0)
        self.assertEqual(end_payload, {
            'type': 'session_ended',
            'mindmapId': 7,
            'reason': 'session_revoked',
            'message': '登录会话已失效，请重新登录',
        })
        self.assertEqual(end_close_code, 4001)

    def test_unknown_recheck_failure_is_bounded_and_does_not_leak_details(self) -> None:
        action = get_ws_auth_recheck_action(
            RuntimeError('database password=secret'),
            7,
            3,
        )

        payload, close_code = action
        self.assertEqual(payload['code'], 'auth_unavailable')
        self.assertTrue(payload['retryable'])
        self.assertNotIn('password', payload['message'])
        self.assertEqual(close_code, WS_RETRY_LATER_CLOSE_CODE)

    def test_binary_payload_requires_strict_base64_within_decoded_limit(self) -> None:
        self.assertEqual(decode_base64_payload('YWJj', 3), b'abc')
        self.assertIsNone(decode_base64_payload('not-base64!', 100))
        self.assertIsNone(decode_base64_payload('YWJj', 2))
        self.assertIsNone(decode_base64_payload('', 10))

    def test_structured_patch_is_normalized_to_protocol_fields(self) -> None:
        patch = normalize_yjs_patch({
            'schemaVersion': 1,
            'nodes': [{
                'uid': ' child ',
                'data': {'text': '<p>协作修复</p>', 'richText': True},
                'children': [' grandchild '],
                'previousData': {'text': '协作前'},
                'previousChildren': [' old-child '],
                'ignored': '不会被广播',
            }],
            'deletedNodeUids': [' old-node '],
            'ignored': '不会被广播',
        })

        self.assertEqual(patch, {
            'schemaVersion': 1,
            'nodes': [{
                'uid': 'child',
                'data': {'text': '<p>协作修复</p>', 'richText': True},
                'children': ['grandchild'],
                'previousData': {'text': '协作前'},
                'previousChildren': ['old-child'],
            }],
            'deletedNodeUids': ['old-node'],
            'applyMeta': False,
        })

    def test_structured_patch_only_accepts_boolean_apply_meta(self) -> None:
        patch = normalize_yjs_patch({
            'schemaVersion': 1,
            'nodes': [],
            'deletedNodeUids': [],
            'applyMeta': 'true',
        })

        self.assertIs(patch['applyMeta'], False)

    def test_structured_patch_rejects_invalid_shape_and_oversized_content(self) -> None:
        self.assertIsNone(normalize_yjs_patch({'schemaVersion': 1, 'nodes': 'bad'}))
        self.assertIsNone(normalize_yjs_patch({
            'schemaVersion': 1,
            'nodes': [{'uid': 'node', 'data': {}, 'children': [True]}],
            'deletedNodeUids': [],
        }))
        self.assertIsNone(normalize_yjs_patch({
            'schemaVersion': 1,
            'nodes': [{
                'uid': 'node',
                'data': {},
                'children': [],
                'previousData': [],
            }],
            'deletedNodeUids': [],
        }))
        self.assertIsNone(normalize_yjs_patch({
            'schemaVersion': 1,
            'nodes': [{
                'uid': 'node',
                'data': {},
                'children': [],
                'previousChildren': [False],
            }],
            'deletedNodeUids': [],
        }))

    def test_structured_patch_rejects_excessive_json_depth_and_cycles(self) -> None:
        deep_value = {'value': 'leaf'}
        for _ in range(70):
            deep_value = {'child': deep_value}
        self.assertIsNone(normalize_yjs_patch({
            'schemaVersion': 1,
            'nodes': [{
                'uid': 'node',
                'data': {'extension': deep_value},
                'children': [],
            }],
            'deletedNodeUids': [],
        }))

        cyclic_value = {}
        cyclic_value['self'] = cyclic_value
        self.assertIsNone(normalize_yjs_patch({
            'schemaVersion': 1,
            'nodes': [{
                'uid': 'node',
                'data': {'extension': cyclic_value},
                'children': [],
            }],
            'deletedNodeUids': [],
        }))
        self.assertIsNone(normalize_yjs_patch({
            'schemaVersion': 1,
            'nodes': [{
                'uid': 'node',
                'data': {'text': 'x' * MAX_YJS_PATCH_BYTES},
                'children': [],
            }],
            'deletedNodeUids': [],
        }))


class MindmapWebsocketAuthenticationBoundaryTest(unittest.IsolatedAsyncioTestCase):
    async def test_each_shared_write_rechecks_database_permission_and_revision(self) -> None:
        current_revision = None

        def set_revision(_mindmap_id: int, revision: int) -> None:
            nonlocal current_revision
            current_revision = revision

        manager = SimpleNamespace(
            set_content_revision=set_revision,
            is_current_revision=lambda _mindmap_id, revision: revision == current_revision,
            get_content_revision=lambda _mindmap_id: current_revision,
        )
        access_mock = AsyncMock(return_value=SimpleNamespace(content_revision=12))
        with patch(
            'module_mindmap.websocket.mindmap_ws.MindmapService.check_mindmap_access',
            new=access_mock,
        ):
            self.assertIsNone(await get_authorized_ws_revision_fence_payload(
                object(), manager, 7, 42, 12,
            ))
            stale = await get_authorized_ws_revision_fence_payload(
                object(), manager, 7, 42, 11,
            )

        self.assertEqual(stale['currentRevision'], 12)
        self.assertEqual(stale['type'], 'stale_state')
        self.assertEqual(access_mock.await_count, 2)
        self.assertEqual(access_mock.await_args_list[0].args[1:], (7, 42))
        self.assertEqual(
            access_mock.await_args_list[0].kwargs,
            {'require_edit': True},
        )

    async def test_owned_lease_renewal_rechecks_permission_without_old_revision_rejection(
        self,
    ) -> None:
        current_revision = None

        def set_revision(_mindmap_id: int, revision: int) -> None:
            nonlocal current_revision
            current_revision = revision

        manager = SimpleNamespace(
            set_content_revision=set_revision,
            is_current_revision=lambda _mindmap_id, revision: revision == current_revision,
            get_content_revision=lambda _mindmap_id: current_revision,
        )
        access_mock = AsyncMock(return_value=SimpleNamespace(content_revision=13))
        with patch(
            'module_mindmap.websocket.mindmap_ws.MindmapService.check_mindmap_access',
            new=access_mock,
        ):
            result = await get_authorized_ws_revision_fence_payload(
                object(),
                manager,
                7,
                42,
                12,
                require_current_revision=False,
            )

        self.assertIsNone(result)
        self.assertEqual(current_revision, 13)
        access_mock.assert_awaited_once()

    async def test_revoked_shared_write_cannot_reach_revision_fence(self) -> None:
        manager = SimpleNamespace(
            set_content_revision=Mock(),
            is_current_revision=Mock(return_value=True),
            get_content_revision=Mock(return_value=8),
        )
        with (
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapService.check_mindmap_access',
                new=AsyncMock(side_effect=ServiceException(message='无编辑权限')),
            ),
            self.assertRaises(ServiceException),
        ):
            await get_authorized_ws_revision_fence_payload(
                object(), manager, 7, 42, 8,
            )

        manager.set_content_revision.assert_not_called()
        manager.is_current_revision.assert_not_called()

    def test_checkpoint_can_only_replace_sources_sent_in_this_connection_snapshot(self) -> None:
        replaceable = {
            'source-a': 'a' * 64,
            'source-b': 'b' * 64,
        }

        self.assertTrue(are_yjs_state_replacements_authorized(
            replaceable,
            ['source-a', 'source-b'],
            replaceable,
        ))
        self.assertTrue(are_yjs_state_replacements_authorized(replaceable, [], {}))
        self.assertFalse(are_yjs_state_replacements_authorized(
            replaceable,
            ['source-a', 'other-session-source'],
            {
                'source-a': 'a' * 64,
                'other-session-source': 'c' * 64,
            },
        ))

    async def test_yjs_checkpoint_rechecks_edit_permission_before_persisting(self) -> None:
        db = object()
        events = []

        async def check_access(*args, **kwargs) -> None:
            events.append(('access', args, kwargs))

        async def save_state(*args, **kwargs) -> bool:
            events.append(('save', args, kwargs))
            return True

        with (
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapService.check_mindmap_access',
                new=AsyncMock(side_effect=check_access),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.YjsDocManager.save_state',
                new=AsyncMock(side_effect=save_state),
            ),
        ):
            saved = await persist_authorized_yjs_state(
                db,
                7,
                42,
                b'complete-state',
                11,
                source_id='connection-a',
                replace_source_ids=['old-source'],
            )

        self.assertTrue(saved)
        self.assertEqual([event[0] for event in events], ['access', 'save'])
        self.assertEqual(events[0][1], (db, 7, 42))
        self.assertEqual(events[0][2], {'require_edit': True})

    async def test_checkpoint_lineage_fence_is_checked_while_db_lock_is_held(self) -> None:
        db = object()
        timeline: list[str] = []
        manager = SimpleNamespace(
            verify_content_lineage_fence=AsyncMock(return_value=False),
        )

        async def check_access(*_args: object, **_kwargs: object) -> None:
            timeline.append('access-lock')

        save_state = AsyncMock(return_value=True)
        with (
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapService.check_mindmap_access',
                new=AsyncMock(side_effect=check_access),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.YjsDocManager.save_state',
                new=save_state,
            ),
        ):
            saved = await persist_authorized_yjs_state(
                db,
                7,
                42,
                b'complete-state',
                11,
                source_id='connection-a',
                replace_source_ids=[],
                lineage_id='stale-lineage',
                manager=manager,
                enforce_lineage_fence=True,
            )

        self.assertFalse(saved)
        self.assertEqual(timeline, ['access-lock'])
        manager.verify_content_lineage_fence.assert_awaited_once_with(
            7,
            11,
            'stale-lineage',
        )
        save_state.assert_not_awaited()

    async def test_revoked_session_cannot_persist_its_last_yjs_checkpoint(self) -> None:
        db = SimpleNamespace()
        save_mock = AsyncMock(return_value=True)
        with (
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapService.check_mindmap_access',
                new=AsyncMock(side_effect=ServiceException(message='无编辑权限')),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.YjsDocManager.save_state',
                new=save_mock,
            ),
            self.assertRaises(ServiceException),
        ):
            await persist_authorized_yjs_state(
                db,
                7,
                42,
                b'complete-state',
                11,
                source_id='connection-a',
                replace_source_ids=[],
            )

        save_mock.assert_not_awaited()

    async def test_readonly_session_cannot_acquire_seed_lease(self) -> None:
        manager = SimpleNamespace(acquire_seed_lease=AsyncMock(return_value=True))
        websocket = object()

        granted = await acquire_ws_seed_lease(
            manager,
            7,
            11,
            websocket,
            can_edit_session=False,
        )

        self.assertFalse(granted)
        manager.acquire_seed_lease.assert_not_awaited()

        self.assertTrue(await acquire_ws_seed_lease(
            manager,
            7,
            11,
            websocket,
            can_edit_session=True,
        ))
        manager.acquire_seed_lease.assert_awaited_once_with(7, 11, websocket)

    async def test_only_seed_lease_owner_can_mark_authoritative_seed_state(self) -> None:
        manager = SimpleNamespace(consume_seed_lease=AsyncMock(return_value=True))
        websocket = object()
        valid = {
            'msg_type': 'update',
            'data': {'seedState': True, 'contentRevision': 11},
            'mutation_id': None,
            'update_bytes': b'complete-state',
            'state_bytes': b'complete-state',
            'patch': None,
        }

        self.assertTrue(await can_forward_ws_authoritative_seed(
            manager,
            7,
            websocket,
            **valid,
        ))
        manager.consume_seed_lease.assert_awaited_once_with(7, 11, websocket)

        for invalid in (
            {**valid, 'msg_type': 'checkpoint'},
            {**valid, 'mutation_id': 'local-edit'},
            {**valid, 'update_bytes': None},
            {**valid, 'state_bytes': None},
            {**valid, 'update_bytes': b'different-state'},
            {**valid, 'patch': {'nodes': []}},
            {**valid, 'data': {'seedState': True, 'contentRevision': '11'}},
        ):
            manager.consume_seed_lease.reset_mock()
            self.assertFalse(await can_forward_ws_authoritative_seed(
                manager,
                7,
                websocket,
                **invalid,
            ))
            manager.consume_seed_lease.assert_not_awaited()

    def test_only_authoritative_seed_hint_uses_the_full_state_update_limit(self) -> None:
        from module_mindmap.websocket.mindmap_ws import (  # noqa: PLC0415
            MAX_YJS_STATE_BYTES,
            MAX_YJS_UPDATE_BYTES,
        )

        seed_hint = {
            'seedState': True,
            'update': 'eA==',
            'state': 'eA==',
            'contentRevision': 11,
        }
        self.assertEqual(get_yjs_update_payload_limit(seed_hint), MAX_YJS_STATE_BYTES)
        for payload in (
            {},
            {'seedState': False},
            {'seedState': 1},
            {'seedState': True},
            {**seed_hint, 'state': 'different'},
            {**seed_hint, 'clientMutationId': 'local-edit'},
            {**seed_hint, 'contentRevision': '11'},
        ):
            self.assertEqual(
                get_yjs_update_payload_limit(payload),
                MAX_YJS_UPDATE_BYTES,
            )

        # 5 MiB 以上、15 MiB 以内的完整 Y.Doc 是合法权威种子；普通
        # realtime update 仍应在较小边界被拒绝，避免扩大常规消息成本。
        large_state = b'x' * (MAX_YJS_UPDATE_BYTES + 1)
        encoded_state = base64.b64encode(large_state).decode()
        self.assertEqual(
            decode_base64_payload(
                encoded_state,
                get_yjs_update_payload_limit({
                    **seed_hint,
                    'update': encoded_state,
                    'state': encoded_state,
                }),
            ),
            large_state,
        )
        self.assertIsNone(decode_base64_payload(
            encoded_state,
            get_yjs_update_payload_limit({}),
        ))

    async def test_empty_room_request_seed_reaches_the_lease_branch(self) -> None:
        websocket = _ScriptedWebSocket([
            {
                'type': 'auth',
                'token': 'opaque-token',
                'capabilities': [YJS_CHECKPOINT_CAPABILITY],
            },
            {'type': 'request_seed', 'contentRevision': 4},
        ])
        manager = _create_endpoint_room_manager(websocket)
        mindmap = SimpleNamespace(
            content_revision=4,
            schema_version=2,
            status=0,
        )
        with (
            patch(
                'module_mindmap.websocket.mindmap_ws.AsyncSessionLocal',
                new=Mock(side_effect=_SessionContext),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.validate_ws_token',
                new=AsyncMock(return_value={'id': 7, 'name': 'Editor'}),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapService.resolve_mindmap_access',
                new=AsyncMock(return_value=(mindmap, 1, False)),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapDao.get_migration_status',
                new=AsyncMock(return_value='completed'),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapDocumentService.load_tree',
                new=AsyncMock(return_value={}),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.YjsDocManager.load_state_snapshot_with_lineages',
                new=AsyncMock(return_value=(4, {}, {})),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapService.check_mindmap_access',
                new=AsyncMock(return_value=mindmap),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.reconcile_persisted_lineage_fence',
                new=AsyncMock(return_value=True),
            ),
            patch('module_mindmap.websocket.mindmap_ws.room_manager', new=manager),
        ):
            await mindmap_websocket_endpoint(websocket, 7)

        self.assertEqual(
            [payload['type'] for payload in websocket.sent],
            ['auth_ok', 'seed_pending', 'seed_granted'],
        )
        manager.acquire_seed_lease.assert_awaited_once_with(7, 4, websocket)

    async def test_v2_writer_establishes_the_room_write_capability_gate(self) -> None:
        websocket = _ScriptedWebSocket([{
            'type': 'auth',
            'token': 'opaque-token',
            'capabilities': [CROSS_NODE_CRDT_V2_CAPABILITY],
        }])
        manager = _create_endpoint_room_manager(websocket)

        await _run_scripted_endpoint(
            websocket,
            manager,
            load_snapshot=(4, {'source': b'complete-state'}, {}),
        )

        manager.require_write_capability.assert_not_awaited()
        auth_ok = websocket.sent[0]
        self.assertFalse(auth_ok['readonly'])
        self.assertIn(CROSS_NODE_CRDT_V2_CAPABILITY, auth_ok['capabilities'])
        self.assertNotIn('writeRestrictedReason', auth_ok)

    async def test_node_edit_lease_messages_use_server_arbitration(self) -> None:
        websocket = _ScriptedWebSocket([
            {
                'type': 'auth',
                'token': 'opaque-token',
                'capabilities': [NODE_EDIT_LEASE_CAPABILITY],
            },
            {
                'type': 'node_edit_lease_acquire',
                'requestId': 'request-1',
                'nodeUid': 'child',
                'contentRevision': 4,
            },
            {
                'type': 'node_edit_lease_release',
                'nodeUid': 'child',
            },
        ])
        manager = _create_endpoint_room_manager(websocket)

        await _run_scripted_endpoint(
            websocket,
            manager,
            load_snapshot=(4, {'source': b'complete-state'}, {}),
        )

        manager.require_write_capability.assert_not_awaited()
        manager.acquire_node_edit_lease.assert_awaited_once_with(
            7,
            4,
            'child',
            websocket,
        )
        manager.release_node_edit_lease.assert_awaited_once_with(
            7,
            'child',
            websocket,
        )
        lease_result = next(
            payload
            for payload in websocket.sent
            if payload.get('type') == 'node_edit_lease_result'
        )
        self.assertEqual(lease_result, {
            'type': 'node_edit_lease_result',
            'requestId': 'request-1',
            'nodeUid': 'child',
            'granted': True,
        })

    async def test_node_edit_lease_renewal_uses_owner_fence_across_revision_advance(
        self,
    ) -> None:
        websocket = _ScriptedWebSocket([
            {
                'type': 'auth',
                'token': 'opaque-token',
                'capabilities': [
                    NODE_EDIT_LEASE_CAPABILITY,
                    NODE_EDIT_LEASE_RENEWAL_CAPABILITY,
                ],
            },
            {
                'type': 'node_edit_lease_acquire',
                'requestId': 'renew-request',
                'nodeUid': 'child',
                'contentRevision': 3,
                'renewal': True,
            },
        ])
        manager = _create_endpoint_room_manager(websocket)

        await _run_scripted_endpoint(
            websocket,
            manager,
            load_snapshot=(4, {'source': b'complete-state'}, {}),
        )

        manager.acquire_node_edit_lease.assert_not_awaited()
        manager.renew_node_edit_lease.assert_awaited_once_with(
            7,
            'child',
            websocket,
        )
        self.assertFalse(any(
            payload.get('type') == 'stale_state'
            for payload in websocket.sent
        ))
        lease_result = next(
            payload
            for payload in websocket.sent
            if payload.get('type') == 'node_edit_lease_result'
        )
        self.assertTrue(lease_result['granted'])

    async def test_unnegotiated_node_edit_renewal_keeps_legacy_revision_fence(
        self,
    ) -> None:
        websocket = _ScriptedWebSocket([
            {
                'type': 'auth',
                'token': 'opaque-token',
                'capabilities': [NODE_EDIT_LEASE_CAPABILITY],
            },
            {
                'type': 'node_edit_lease_acquire',
                'requestId': 'legacy-renew-request',
                'nodeUid': 'child',
                'contentRevision': 3,
                'renewal': True,
            },
        ])
        manager = _create_endpoint_room_manager(websocket)

        await _run_scripted_endpoint(
            websocket,
            manager,
            load_snapshot=(4, {'source': b'complete-state'}, {}),
        )

        manager.renew_node_edit_lease.assert_not_awaited()
        manager.acquire_node_edit_lease.assert_not_awaited()
        self.assertTrue(any(
            payload.get('type') == 'stale_state'
            for payload in websocket.sent
        ))

    async def test_node_edit_lease_denial_distinguishes_occupancy_from_outage(
        self,
    ) -> None:
        websocket = _ScriptedWebSocket([
            {
                'type': 'auth',
                'token': 'opaque-token',
                'capabilities': [NODE_EDIT_LEASE_CAPABILITY],
            },
            {
                'type': 'node_edit_lease_acquire',
                'requestId': 'occupied-request',
                'nodeUid': 'child',
                'contentRevision': 4,
            },
            {
                'type': 'node_edit_lease_acquire',
                'requestId': 'unavailable-request',
                'nodeUid': 'root',
                'contentRevision': 4,
            },
        ])
        manager = _create_endpoint_room_manager(websocket)
        manager.acquire_node_edit_lease.side_effect = [False, None]

        await _run_scripted_endpoint(
            websocket,
            manager,
            load_snapshot=(4, {'source': b'complete-state'}, {}),
        )

        lease_results = [
            payload
            for payload in websocket.sent
            if payload.get('type') == 'node_edit_lease_result'
        ]
        self.assertEqual(lease_results, [
            {
                'type': 'node_edit_lease_result',
                'requestId': 'occupied-request',
                'nodeUid': 'child',
                'granted': False,
                'reason': 'occupied',
            },
            {
                'type': 'node_edit_lease_result',
                'requestId': 'unavailable-request',
                'nodeUid': 'root',
                'granted': False,
                'reason': 'unavailable',
            },
        ])

    async def test_node_edit_lease_requires_current_client_revision(self) -> None:
        for revision, expected_type in ((None, 'protocol_error'), (3, 'stale_state')):
            with self.subTest(revision=revision):
                message = {
                    'type': 'node_edit_lease_acquire',
                    'requestId': 'revision-fenced-request',
                    'nodeUid': 'child',
                }
                if revision is not None:
                    message['contentRevision'] = revision
                websocket = _ScriptedWebSocket([
                    {
                        'type': 'auth',
                        'token': 'opaque-token',
                        'capabilities': [NODE_EDIT_LEASE_CAPABILITY],
                    },
                    message,
                ])
                manager = _create_endpoint_room_manager(websocket)

                await _run_scripted_endpoint(
                    websocket,
                    manager,
                    load_snapshot=(4, {'source': b'complete-state'}, {}),
                )

                self.assertTrue(any(
                    payload.get('type') == expected_type
                    for payload in websocket.sent
                ))
                manager.acquire_node_edit_lease.assert_not_awaited()

    async def test_legacy_writer_in_v2_room_is_kept_readonly_and_cannot_update(self) -> None:
        websocket = _ScriptedWebSocket([
            {'type': 'auth', 'token': 'opaque-token'},
            {
                'type': 'update',
                'update': base64.b64encode(b'legacy-update').decode(),
                'contentRevision': 4,
            },
        ])
        manager = _create_endpoint_room_manager(
            websocket,
            required_write_capabilities={CROSS_NODE_CRDT_V2_CAPABILITY},
        )

        save_state = await _run_scripted_endpoint(
            websocket,
            manager,
            load_snapshot=(4, {'source': b'complete-state'}, {}),
        )

        auth_ok = websocket.sent[0]
        self.assertTrue(auth_ok['readonly'])
        self.assertEqual(
            auth_ok['requiredWriteCapabilities'],
            [CROSS_NODE_CRDT_V2_CAPABILITY],
        )
        self.assertEqual(auth_ok['writeRestrictedReason'], 'write_capability_required')
        self.assertEqual(websocket.sent[-1]['code'], 'write_capability_required')
        self.assertEqual(websocket.close_codes, [])
        self.assertFalse(any(
            call.args[1].get('type') == 'update'
            for call in manager.broadcast.await_args_list
        ))
        save_state.assert_not_awaited()

    async def test_awareness_uses_server_session_identity_for_same_user_browsers(self) -> None:
        websocket = _ScriptedWebSocket([
            {'type': 'auth', 'token': 'opaque-token'},
            {
                'type': 'awareness',
                'nodeUids': ['child'],
                'editingNodeUid': 'child',
            },
        ])
        manager = _create_endpoint_room_manager(websocket)
        mindmap = SimpleNamespace(
            content_revision=4,
            schema_version=2,
            status=0,
        )
        with (
            patch(
                'module_mindmap.websocket.mindmap_ws.AsyncSessionLocal',
                new=Mock(side_effect=_SessionContext),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.validate_ws_token',
                new=AsyncMock(return_value={'id': 7, 'name': 'Editor'}),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapService.resolve_mindmap_access',
                new=AsyncMock(return_value=(mindmap, 1, False)),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapDao.get_migration_status',
                new=AsyncMock(return_value='completed'),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapDocumentService.load_tree',
                new=AsyncMock(return_value={}),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.YjsDocManager.load_state_snapshot_with_lineages',
                new=AsyncMock(return_value=(4, {}, {})),
            ),
            patch('module_mindmap.websocket.mindmap_ws.room_manager', new=manager),
        ):
            await mindmap_websocket_endpoint(websocket, 7)

        session_id = websocket.sent[0]['sessionId']
        self.assertEqual(len(session_id), 32)
        awareness_messages = [
            call.args[1]
            for call in manager.broadcast.await_args_list
            if call.args[1].get('type') == 'awareness'
        ]
        self.assertEqual(
            [message['nodeUids'] for message in awareness_messages],
            [['child'], []],
        )
        self.assertEqual(
            [message['editingNodeUid'] for message in awareness_messages],
            ['child', ''],
        )
        self.assertTrue(all(
            message['sessionId'] == session_id
            for message in awareness_messages
        ))
        self.assertIs(manager.join.await_args.kwargs['can_edit'], True)

    async def test_readonly_session_cannot_publish_node_occupancy_awareness(self) -> None:
        websocket = _ScriptedWebSocket([
            {'type': 'auth', 'token': 'opaque-token', 'readonly': True},
            {
                'type': 'awareness',
                'nodeUids': ['child'],
                'editingNodeUid': 'child',
            },
        ])
        manager = _create_endpoint_room_manager(websocket)
        mindmap = SimpleNamespace(
            content_revision=4,
            schema_version=2,
            status=0,
        )
        with (
            patch(
                'module_mindmap.websocket.mindmap_ws.AsyncSessionLocal',
                new=Mock(side_effect=_SessionContext),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.validate_ws_token',
                new=AsyncMock(return_value={'id': 7, 'name': 'Viewer'}),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapService.resolve_mindmap_access',
                new=AsyncMock(return_value=(mindmap, 1, False)),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapDao.get_migration_status',
                new=AsyncMock(return_value='completed'),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapDocumentService.load_tree',
                new=AsyncMock(return_value={}),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.YjsDocManager.load_state_snapshot_with_lineages',
                new=AsyncMock(return_value=(4, {}, {})),
            ),
            patch('module_mindmap.websocket.mindmap_ws.room_manager', new=manager),
        ):
            await mindmap_websocket_endpoint(websocket, 7)

        awareness_messages = [
            call.args[1]
            for call in manager.broadcast.await_args_list
            if call.args[1].get('type') == 'awareness'
        ]
        self.assertEqual(
            [message['nodeUids'] for message in awareness_messages],
            [[], []],
        )
        self.assertEqual(
            [message['editingNodeUid'] for message in awareness_messages],
            ['', ''],
        )
        self.assertTrue(websocket.sent[0]['readonly'])
        self.assertIs(manager.join.await_args.kwargs['can_edit'], False)

    async def test_transient_write_authorization_failure_keeps_yjs_session_retryable(self) -> None:
        websocket = _ScriptedWebSocket([
            {
                'type': 'auth',
                'token': 'opaque-token',
                'capabilities': [YJS_CHECKPOINT_CAPABILITY],
            },
            {
                'type': 'update',
                'update': base64.b64encode(b'increment').decode(),
                'contentRevision': 4,
            },
        ])
        manager = _create_endpoint_room_manager(websocket)
        mindmap = SimpleNamespace(
            content_revision=4,
            schema_version=2,
            status=0,
        )
        with (
            patch(
                'module_mindmap.websocket.mindmap_ws.AsyncSessionLocal',
                new=Mock(side_effect=_SessionContext),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.validate_ws_token',
                new=AsyncMock(return_value={'id': 7, 'name': 'Editor'}),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapService.resolve_mindmap_access',
                new=AsyncMock(return_value=(mindmap, 1, False)),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapDao.get_migration_status',
                new=AsyncMock(return_value='completed'),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapDocumentService.load_tree',
                new=AsyncMock(return_value={}),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.YjsDocManager.load_state_snapshot_with_lineages',
                new=AsyncMock(return_value=(
                    4,
                    {'source-a': b'complete-state'},
                    {},
                )),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapService.check_mindmap_access',
                new=AsyncMock(side_effect=ConnectionError('database unavailable')),
            ),
            patch('module_mindmap.websocket.mindmap_ws.room_manager', new=manager),
        ):
            await mindmap_websocket_endpoint(websocket, 7)

        failure = websocket.sent[-1]
        self.assertEqual(failure['type'], 'auth_error')
        self.assertEqual(failure['code'], 'access_check_unavailable')
        self.assertTrue(failure['retryable'])
        self.assertNotIn('database', failure['message'])
        self.assertEqual(websocket.close_codes, [WS_RETRY_LATER_CLOSE_CODE])
        manager.block_disconnect_persistence.assert_called_once_with(websocket)

    async def test_sequenced_updates_require_valid_id_and_sequence_before_broadcast(self) -> None:
        encoded_update = base64.b64encode(b'increment').decode()
        websocket = _ScriptedWebSocket([
            {
                'type': 'auth',
                'token': 'opaque-token',
                'capabilities': [
                    YJS_MUTATION_SEQUENCE_CAPABILITY,
                    YJS_LINEAGE_CAPABILITY,
                ],
            },
            {
                'type': 'update',
                'update': encoded_update,
                'contentRevision': 4,
                'clientMutationId': ' mutation-valid ',
                'mutationUpdateSeq': 2,
                'lineageId': 'shared-lineage',
            },
            {
                'type': 'update',
                'update': encoded_update,
                'contentRevision': 4,
                'clientMutationId': 'missing-sequence',
                'lineageId': 'shared-lineage',
            },
            {
                'type': 'update',
                'update': encoded_update,
                'contentRevision': 4,
                'mutationUpdateSeq': 1,
                'lineageId': 'shared-lineage',
            },
            {
                'type': 'update',
                'update': encoded_update,
                'contentRevision': 4,
                'clientMutationId': '   ',
                'mutationUpdateSeq': 1,
                'lineageId': 'shared-lineage',
            },
        ])
        manager = _create_endpoint_room_manager(websocket)
        mindmap = SimpleNamespace(content_revision=4, schema_version=2, status=0)
        with (
            patch(
                'module_mindmap.websocket.mindmap_ws.AsyncSessionLocal',
                new=Mock(side_effect=_SessionContext),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.validate_ws_token',
                new=AsyncMock(return_value={'id': 7, 'name': 'Editor'}),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapService.resolve_mindmap_access',
                new=AsyncMock(return_value=(mindmap, 1, False)),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapDao.get_migration_status',
                new=AsyncMock(return_value='completed'),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapDocumentService.load_tree',
                new=AsyncMock(return_value={}),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.YjsDocManager.load_state_snapshot_with_lineages',
                new=AsyncMock(return_value=(
                    4,
                    {'source-a': b'complete-state'},
                    {},
                )),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapService.check_mindmap_access',
                new=AsyncMock(return_value=mindmap),
            ),
            patch('module_mindmap.websocket.mindmap_ws.room_manager', new=manager),
        ):
            await mindmap_websocket_endpoint(websocket, 7)

        self.assertIn(YJS_MUTATION_SEQUENCE_CAPABILITY, websocket.sent[0]['capabilities'])
        update_broadcasts = [
            call.args[1]
            for call in manager.broadcast_with_lineage_fence.await_args_list
            if call.args[1].get('type') == 'update'
        ]
        self.assertEqual(len(update_broadcasts), 1)
        self.assertEqual(update_broadcasts[0]['clientMutationId'], 'mutation-valid')
        self.assertEqual(update_broadcasts[0]['mutationUpdateSeq'], 2)
        error_codes = [
            payload.get('code')
            for payload in websocket.sent
            if payload.get('type') == 'protocol_error'
        ]
        self.assertEqual(error_codes, [
            'invalid_mutation_sequence',
            'invalid_mutation_sequence',
            'invalid_client_mutation_id',
        ])

    async def test_plain_update_full_state_is_never_persisted_as_current_revision(self) -> None:
        encoded_update = base64.b64encode(b'increment').decode()
        encoded_state = base64.b64encode(b'uncommitted-complete-state').decode()
        websocket = _ScriptedWebSocket([
            {
                'type': 'auth',
                'token': 'opaque-token',
                'capabilities': [
                    YJS_CHECKPOINT_CAPABILITY,
                    YJS_LINEAGE_CAPABILITY,
                ],
            },
            {
                'type': 'update',
                'update': encoded_update,
                'state': encoded_state,
                'contentRevision': 4,
                'lineageId': 'shared-lineage',
            },
        ])
        manager = _create_endpoint_room_manager(websocket)
        mindmap = SimpleNamespace(content_revision=4, schema_version=2, status=0)
        save_state = AsyncMock(return_value=True)
        with (
            patch(
                'module_mindmap.websocket.mindmap_ws.AsyncSessionLocal',
                new=Mock(side_effect=_SessionContext),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.validate_ws_token',
                new=AsyncMock(return_value={'id': 7, 'name': 'Editor'}),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapService.resolve_mindmap_access',
                new=AsyncMock(return_value=(mindmap, 1, False)),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapDao.get_migration_status',
                new=AsyncMock(return_value='completed'),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapDocumentService.load_tree',
                new=AsyncMock(return_value={}),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.YjsDocManager.load_state_snapshot_with_lineages',
                new=AsyncMock(return_value=(
                    4,
                    {'source-a': b'complete-state'},
                    {},
                )),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.YjsDocManager.save_state',
                new=save_state,
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapService.check_mindmap_access',
                new=AsyncMock(return_value=mindmap),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.reconcile_persisted_lineage_fence',
                new=AsyncMock(return_value=True),
            ),
            patch('module_mindmap.websocket.mindmap_ws.room_manager', new=manager),
        ):
            await mindmap_websocket_endpoint(websocket, 7)

        save_state.assert_not_awaited()
        update_broadcasts = [
            call.args[1]
            for call in manager.broadcast_with_lineage_fence.await_args_list
            if call.args[1].get('type') == 'update'
        ]
        self.assertEqual(len(update_broadcasts), 1)
        self.assertEqual(update_broadcasts[0]['state'], encoded_state)

    async def test_failed_initial_state_delivery_retires_joined_connection_cleanly(self) -> None:
        websocket = _AuthFailureWebSocket()
        manager = _create_endpoint_room_manager(
            websocket,
            fail_message_type='sync_init',
        )
        mindmap = SimpleNamespace(
            content_revision=4,
            schema_version=2,
            status=0,
        )
        with (
            patch(
                'module_mindmap.websocket.mindmap_ws.AsyncSessionLocal',
                new=Mock(side_effect=_SessionContext),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.validate_ws_token',
                new=AsyncMock(return_value={'id': 7, 'name': 'Editor'}),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapService.resolve_mindmap_access',
                new=AsyncMock(return_value=(mindmap, 1, False)),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapDao.get_migration_status',
                new=AsyncMock(return_value='completed'),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapDocumentService.load_tree',
                new=AsyncMock(return_value={}),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.YjsDocManager.load_state_snapshot_with_lineages',
                new=AsyncMock(return_value=(
                    5,
                    {'source-a': b'complete-state'},
                    {},
                )),
            ),
            patch('module_mindmap.websocket.mindmap_ws.room_manager', new=manager),
        ):
            await mindmap_websocket_endpoint(websocket, 7)

        self.assertEqual(
            [payload['type'] for payload in websocket.sent],
            ['auth_ok', 'sync_init'],
        )
        self.assertEqual(websocket.sent[-1]['contentRevision'], 5)
        manager.leave.assert_awaited_once_with(7, websocket)

    async def test_initial_state_infrastructure_failure_closes_retryably_and_leaves(self) -> None:
        websocket = _AuthFailureWebSocket()
        manager = _create_endpoint_room_manager(websocket)
        mindmap = SimpleNamespace(
            content_revision=4,
            schema_version=2,
            status=0,
        )
        with (
            patch(
                'module_mindmap.websocket.mindmap_ws.AsyncSessionLocal',
                new=Mock(side_effect=_SessionContext),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.validate_ws_token',
                new=AsyncMock(return_value={'id': 7, 'name': 'Editor'}),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapService.resolve_mindmap_access',
                new=AsyncMock(return_value=(mindmap, 1, False)),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapDao.get_migration_status',
                new=AsyncMock(return_value='completed'),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapDocumentService.load_tree',
                new=AsyncMock(return_value={}),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.YjsDocManager.load_state_snapshot_with_lineages',
                new=AsyncMock(side_effect=ConnectionError('database unavailable')),
            ),
            patch('module_mindmap.websocket.mindmap_ws.room_manager', new=manager),
        ):
            await mindmap_websocket_endpoint(websocket, 7)

        self.assertEqual(websocket.sent[-1]['code'], 'collaboration_state_unavailable')
        self.assertTrue(websocket.sent[-1]['retryable'])
        self.assertEqual(websocket.close_codes, [WS_RETRY_LATER_CLOSE_CODE])
        manager.leave.assert_awaited_once_with(7, websocket)

    async def test_mismatched_live_lineage_is_closed_before_broadcast_or_persist(self) -> None:
        encoded_update = base64.b64encode(b'increment').decode()
        websocket = _ScriptedWebSocket([
            {
                'type': 'auth',
                'token': 'opaque-token',
                'capabilities': [YJS_LINEAGE_CAPABILITY],
            },
            {
                'type': 'update',
                'update': encoded_update,
                'contentRevision': 4,
                'lineageId': 'forked-lineage',
            },
        ])
        manager = _create_endpoint_room_manager(websocket)
        manager.set_content_lineage.return_value = False
        mindmap = SimpleNamespace(content_revision=4, schema_version=2, status=0)
        save_state = AsyncMock(return_value=True)
        with (
            patch(
                'module_mindmap.websocket.mindmap_ws.AsyncSessionLocal',
                new=Mock(side_effect=_SessionContext),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.validate_ws_token',
                new=AsyncMock(return_value={'id': 7, 'name': 'Editor'}),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapService.resolve_mindmap_access',
                new=AsyncMock(return_value=(mindmap, 1, False)),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapDao.get_migration_status',
                new=AsyncMock(return_value='completed'),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapDocumentService.load_tree',
                new=AsyncMock(return_value={}),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.YjsDocManager.load_state_snapshot_with_lineages',
                new=AsyncMock(return_value=(4, {}, {})),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.YjsDocManager.save_state',
                new=save_state,
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapService.check_mindmap_access',
                new=AsyncMock(return_value=mindmap),
            ),
            patch('module_mindmap.websocket.mindmap_ws.room_manager', new=manager),
        ):
            await mindmap_websocket_endpoint(websocket, 7)

        self.assertEqual(websocket.sent[-1]['type'], 'stale_state')
        self.assertEqual(websocket.sent[-1]['reason'], 'yjs_lineage_changed')
        self.assertEqual(websocket.close_codes, [WS_RETRY_LATER_CLOSE_CODE])
        manager.block_disconnect_persistence.assert_called_once_with(websocket)
        self.assertFalse(any(
            call.args[1].get('type') == 'update'
            for call in manager.broadcast.await_args_list
        ))
        save_state.assert_not_awaited()

    async def test_ordinary_update_cannot_elect_lineage_in_an_empty_room(self) -> None:
        websocket = _ScriptedWebSocket([
            {
                'type': 'auth',
                'token': 'opaque-token',
                'capabilities': [YJS_LINEAGE_CAPABILITY],
            },
            {
                'type': 'update',
                'update': base64.b64encode(b'uncommitted-fork').decode(),
                'contentRevision': 4,
                'lineageId': 'worker-local-lineage',
            },
        ])
        manager = _create_endpoint_room_manager(websocket)
        manager.has_content_lineage.return_value = False
        manager.verify_content_lineage_fence.return_value = False

        save_state = await _run_scripted_endpoint(
            websocket,
            manager,
            load_snapshot=(4, {}, {}),
        )

        self.assertEqual(websocket.sent[-1]['type'], 'stale_state')
        self.assertEqual(websocket.sent[-1]['reason'], 'yjs_lineage_changed')
        self.assertEqual(websocket.close_codes, [WS_RETRY_LATER_CLOSE_CODE])
        manager.set_content_lineage.assert_not_called()
        manager.block_disconnect_persistence.assert_called_once_with(websocket)
        self.assertFalse(any(
            call.args[1].get('type') == 'update'
            for call in manager.broadcast.await_args_list
        ))
        save_state.assert_not_awaited()

    async def test_authoritative_seed_cas_replaces_snapshot_before_lineage_switch(self) -> None:
        previous_state = b'previous-complete-state'
        seed_state = b'new-authoritative-state'
        websocket = _ScriptedWebSocket([
            {
                'type': 'auth',
                'token': 'opaque-token',
                'capabilities': [
                    YJS_CHECKPOINT_CAPABILITY,
                    YJS_LINEAGE_CAPABILITY,
                    YJS_SOURCE_CAS_CAPABILITY,
                ],
            },
            {'type': 'request_seed', 'contentRevision': 4},
            {
                'type': 'update',
                'update': base64.b64encode(seed_state).decode(),
                'state': base64.b64encode(seed_state).decode(),
                'contentRevision': 4,
                'lineageId': 'new-lineage',
                'seedState': True,
            },
        ])
        manager = _create_endpoint_room_manager(websocket)
        mindmap = SimpleNamespace(content_revision=4, schema_version=2, status=0)
        save_state = AsyncMock(return_value=True)
        with (
            patch(
                'module_mindmap.websocket.mindmap_ws.AsyncSessionLocal',
                new=Mock(side_effect=_SessionContext),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.validate_ws_token',
                new=AsyncMock(return_value={'id': 7, 'name': 'Editor'}),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapService.resolve_mindmap_access',
                new=AsyncMock(return_value=(mindmap, 1, False)),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapDao.get_migration_status',
                new=AsyncMock(return_value='completed'),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapDocumentService.load_tree',
                new=AsyncMock(return_value={}),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.YjsDocManager.load_state_snapshot_with_lineages',
                new=AsyncMock(return_value=(
                    4,
                    {'old-source': previous_state},
                    {'old-source': 'a' * 64},
                )),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.YjsDocManager.save_state',
                new=save_state,
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.MindmapService.check_mindmap_access',
                new=AsyncMock(return_value=mindmap),
            ),
            patch(
                'module_mindmap.websocket.mindmap_ws.reconcile_persisted_lineage_fence',
                new=AsyncMock(return_value=True),
            ),
            patch('module_mindmap.websocket.mindmap_ws.room_manager', new=manager),
        ):
            await mindmap_websocket_endpoint(websocket, 7)

        first_save = save_state.await_args_list[0]
        self.assertEqual(first_save.args[2], seed_state)
        self.assertEqual(first_save.kwargs['replace_source_ids'], ['old-source'])
        self.assertEqual(first_save.kwargs['replace_source_digests'], {
            'old-source': get_yjs_state_digest(previous_state),
        })
        self.assertEqual(first_save.kwargs['lineage_id'], 'new-lineage')
        manager.set_content_lineage.assert_any_call(
            7,
            4,
            'new-lineage',
            replace=True,
        )
        seed_broadcast = next(
            call.args[1]
            for call in manager.broadcast_with_lineage_fence.await_args_list
            if call.args[1].get('seedState') is True
        )
        self.assertEqual(seed_broadcast['lineageId'], 'new-lineage')

    async def test_failed_checkpoint_never_establishes_lineage_or_broadcasts_and_is_not_retried(
        self,
    ) -> None:
        websocket = _ScriptedWebSocket([
            {
                'type': 'auth',
                'token': 'opaque-token',
                'capabilities': [YJS_CHECKPOINT_CAPABILITY, YJS_LINEAGE_CAPABILITY],
            },
            {
                'type': 'checkpoint',
                'state': base64.b64encode(b'forked-checkpoint').decode(),
                'contentRevision': 4,
                'lineageId': 'forked-lineage',
            },
        ])
        manager = _create_endpoint_room_manager(websocket)
        save_state = AsyncMock(return_value=False)

        await _run_scripted_endpoint(
            websocket,
            manager,
            load_snapshot=(
                4,
                {'db-source': b'database-state'},
                {'db-source': 'a' * 64},
            ),
            save_state=save_state,
        )

        save_state.assert_awaited_once()
        manager.set_content_lineage.assert_called_once_with(
            7,
            4,
            'forked-lineage',
            replace=False,
        )
        manager.broadcast_checkpoint.assert_not_awaited()
        manager.block_disconnect_persistence.assert_called_once_with(websocket)
        self.assertEqual(websocket.sent[-1]['code'], 'checkpoint_persist_failed')

    async def test_throttled_checkpoint_can_broadcast_on_an_already_committed_lineage(
        self,
    ) -> None:
        websocket = _ScriptedWebSocket([
            {
                'type': 'auth',
                'token': 'opaque-token',
                'capabilities': [YJS_CHECKPOINT_CAPABILITY, YJS_LINEAGE_CAPABILITY],
            },
            {
                'type': 'checkpoint',
                'state': base64.b64encode(b'same-lineage-checkpoint').decode(),
                'contentRevision': 4,
                'lineageId': 'committed-lineage',
            },
        ])
        manager = _create_endpoint_room_manager(websocket)
        manager.consume_disconnect_persistence_permission.side_effect = None
        manager.consume_disconnect_persistence_permission.return_value = False
        save_state = AsyncMock(return_value=True)

        with patch(
            'module_mindmap.websocket.mindmap_ws.time.monotonic',
            return_value=1.0,
        ):
            await _run_scripted_endpoint(
                websocket,
                manager,
                load_snapshot=(
                    4,
                    {'db-source': b'database-state'},
                    {'db-source': 'a' * 64},
                ),
                save_state=save_state,
            )

        save_state.assert_not_awaited()
        manager.set_content_lineage.assert_called_once_with(
            7,
            4,
            'committed-lineage',
            replace=False,
        )
        manager.broadcast_checkpoint.assert_awaited_once()
        self.assertFalse(any(
            payload.get('code') == 'checkpoint_persist_failed'
            for payload in websocket.sent
        ))

    async def test_disconnect_releases_node_edit_leases_before_final_persistence(
        self,
    ) -> None:
        websocket = _ScriptedWebSocket([
            {
                'type': 'auth',
                'token': 'opaque-token',
                'capabilities': [YJS_CHECKPOINT_CAPABILITY, YJS_LINEAGE_CAPABILITY],
            },
            {
                'type': 'checkpoint',
                'state': base64.b64encode(b'latest-checkpoint').decode(),
                'contentRevision': 4,
                'lineageId': 'committed-lineage',
            },
        ])
        manager = _create_endpoint_room_manager(websocket)
        save_state = AsyncMock(return_value=True)
        timeline = Mock()
        timeline.attach_mock(
            manager.release_connection_node_edit_leases,
            'release_leases',
        )
        timeline.attach_mock(save_state, 'persist')
        timeline.attach_mock(manager.leave, 'leave')

        # checkpoint 分支先被节流，因此唯一一次 save_state 是 finally
        # 中的强制持久化，可直接检验释放 -> 持久化 -> leave 顺序。
        with patch(
            'module_mindmap.websocket.mindmap_ws.time.monotonic',
            return_value=1.0,
        ):
            await _run_scripted_endpoint(
                websocket,
                manager,
                load_snapshot=(
                    4,
                    {'db-source': b'database-state'},
                    {'db-source': 'a' * 64},
                ),
                save_state=save_state,
            )

        save_state.assert_awaited_once()
        ordered_calls = [call[0] for call in timeline.mock_calls]
        self.assertLess(
            ordered_calls.index('release_leases'),
            ordered_calls.index('persist'),
        )
        self.assertLess(
            ordered_calls.index('persist'),
            ordered_calls.index('leave'),
        )

    async def test_failed_authoritative_seed_cannot_be_persisted_from_finally(self) -> None:
        websocket = _ScriptedWebSocket([
            {
                'type': 'auth',
                'token': 'opaque-token',
                'capabilities': [
                    YJS_CHECKPOINT_CAPABILITY,
                    YJS_LINEAGE_CAPABILITY,
                    YJS_SOURCE_CAS_CAPABILITY,
                ],
            },
            {'type': 'request_seed', 'contentRevision': 4},
            {
                'type': 'update',
                'update': base64.b64encode(b'new-seed-state').decode(),
                'state': base64.b64encode(b'new-seed-state').decode(),
                'contentRevision': 4,
                'lineageId': 'new-seed-lineage',
                'seedState': True,
            },
        ])
        manager = _create_endpoint_room_manager(websocket)
        # 旧逻辑会在 seed 失败后进入 finally，导致第二次调用成功
        # 写入 DB，但没有同步切换房间 lineage 或广播 seed。
        save_state = AsyncMock(side_effect=[False, True])

        await _run_scripted_endpoint(
            websocket,
            manager,
            load_snapshot=(4, {}, {}),
            save_state=save_state,
        )

        save_state.assert_awaited_once()
        manager.block_disconnect_persistence.assert_called_once_with(websocket)
        manager.set_content_lineage.assert_not_called()
        self.assertFalse(any(
            call.args[1].get('seedState') is True
            for call in manager.broadcast.await_args_list
        ))
        self.assertEqual(websocket.sent[-1]['code'], 'seed_persist_failed')

    async def test_db_lineage_reconciliation_retires_peers_before_sync_init(self) -> None:
        websocket = _ScriptedWebSocket([{
            'type': 'auth',
            'token': 'opaque-token',
            'capabilities': [YJS_CHECKPOINT_CAPABILITY, YJS_LINEAGE_CAPABILITY],
        }])
        manager = _create_endpoint_room_manager(websocket)
        manager.get_content_lineage_generation.return_value = 7
        manager.reconcile_persisted_content_lineage_digest.return_value = (True, True)

        await _run_scripted_endpoint(
            websocket,
            manager,
            load_snapshot=(
                4,
                {'db-source': b'database-authoritative-state'},
                {'db-source': 'b' * 64},
            ),
        )

        manager.reconcile_persisted_content_lineage_digest.assert_called_once_with(
            7,
            4,
            'b' * 64,
            expected_generation=7,
        )
        manager.repair_content_lineage_fence_from_persisted.assert_awaited_once_with(
            7,
            4,
            'b' * 64,
            preserve_matching_active=False,
        )
        manager._test_load_state.assert_awaited_once_with(
            unittest.mock.ANY,
            7,
            lock_for_update=True,
        )
        manager.disconnect_stale_lineage_peers.assert_awaited_once_with(
            7,
            websocket,
            4,
        )
        self.assertEqual(
            [payload['type'] for payload in websocket.sent],
            ['auth_ok', 'sync_init'],
        )

    async def test_db_lineage_reconciliation_race_reconnects_without_sending_stale_snapshot(
        self,
    ) -> None:
        websocket = _ScriptedWebSocket([{
            'type': 'auth',
            'token': 'opaque-token',
            'capabilities': [YJS_CHECKPOINT_CAPABILITY, YJS_LINEAGE_CAPABILITY],
        }])
        manager = _create_endpoint_room_manager(websocket)
        manager.get_content_lineage_generation.return_value = 7
        manager.reconcile_persisted_content_lineage_digest.return_value = (False, False)

        await _run_scripted_endpoint(
            websocket,
            manager,
            load_snapshot=(
                4,
                {'db-source': b'snapshot-that-lost-the-race'},
                {'db-source': 'c' * 64},
            ),
        )

        self.assertEqual([payload['type'] for payload in websocket.sent], [
            'auth_ok',
            'stale_state',
        ])
        self.assertEqual(websocket.sent[-1]['reason'], 'yjs_lineage_changed')
        manager.disconnect_stale_lineage_peers.assert_not_awaited()
        manager.leave.assert_awaited_once_with(7, websocket)

    async def test_db_snapshot_older_than_room_revision_never_reaches_sync_init(self) -> None:
        websocket = _ScriptedWebSocket([{
            'type': 'auth',
            'token': 'opaque-token',
            'capabilities': [YJS_CHECKPOINT_CAPABILITY, YJS_LINEAGE_CAPABILITY],
        }])
        manager = _create_endpoint_room_manager(websocket)
        current_revision = 5
        manager.get_content_revision = lambda _mindmap_id: current_revision
        manager.is_current_revision = (
            lambda _mindmap_id, revision: revision == current_revision
        )

        await _run_scripted_endpoint(
            websocket,
            manager,
            load_snapshot=(
                4,
                {'db-source': b'old-room-snapshot'},
                {},
            ),
        )

        self.assertEqual([payload['type'] for payload in websocket.sent], [
            'auth_ok',
            'stale_state',
        ])
        self.assertEqual(websocket.sent[-1]['currentRevision'], 5)
        self.assertEqual(websocket.sent[-1]['reason'], 'handshake_revision_advanced')
        self.assertFalse(any(
            payload['type'] in {'sync_init', 'seed_pending'}
            for payload in websocket.sent
        ))
        manager.reconcile_persisted_content_lineage_digest.assert_not_called()
        manager.leave.assert_awaited_once_with(7, websocket)

    async def test_barrier_ready_ack_is_processed_after_forced_checkpoint_persistence(
        self,
    ) -> None:
        token = '0123456789abcdef0123456789abcdef'
        websocket = _ScriptedWebSocket([
            {
                'type': 'auth',
                'token': 'opaque-token',
                'capabilities': [
                    COLLABORATION_MUTATION_BARRIER_CAPABILITY,
                    YJS_CHECKPOINT_CAPABILITY,
                    YJS_LINEAGE_CAPABILITY,
                ],
            },
            {
                'type': 'checkpoint',
                'state': base64.b64encode(b'drained-yjs-state').decode(),
                'contentRevision': 4,
                'lineageId': 'committed-lineage',
                'barrierToken': token,
            },
            {
                'type': 'collaboration_barrier_ack',
                'token': token,
                'ready': True,
                'contentRevision': 4,
            },
        ])
        manager = _create_endpoint_room_manager(websocket)
        manager.consume_disconnect_persistence_permission.side_effect = None
        manager.consume_disconnect_persistence_permission.return_value = False
        save_state = AsyncMock(return_value=True)
        timeline = Mock()
        timeline.attach_mock(save_state, 'persist')
        timeline.attach_mock(
            manager.record_collaboration_mutation_checkpoint,
            'checkpoint_recorded',
        )
        timeline.attach_mock(
            manager.acknowledge_collaboration_mutation_barrier,
            'acknowledged',
        )

        with patch(
            'module_mindmap.websocket.mindmap_ws.time.monotonic',
            return_value=1.0,
        ):
            await _run_scripted_endpoint(
                websocket,
                manager,
                load_snapshot=(
                    4,
                    {'db-source': b'database-state'},
                    {'db-source': 'a' * 64},
                ),
                save_state=save_state,
            )

        save_state.assert_awaited_once()
        manager.record_collaboration_mutation_checkpoint.assert_awaited_once_with(
            7,
            websocket,
            token,
        )
        manager.acknowledge_collaboration_mutation_barrier.assert_awaited_once_with(
            7,
            websocket,
            token,
            ready=True,
        )
        self.assertEqual(
            [call[0] for call in timeline.method_calls],
            ['persist', 'checkpoint_recorded', 'acknowledged'],
        )
        manager.broadcast_checkpoint.assert_not_awaited()

    async def test_unexpected_auth_failure_is_generic_and_retryable(self) -> None:
        websocket = _AuthFailureWebSocket()
        with patch(
            'module_mindmap.websocket.mindmap_ws.validate_ws_token',
            new=AsyncMock(side_effect=RuntimeError('database password=secret')),
        ):
            await mindmap_websocket_endpoint(websocket, 7)

        self.assertTrue(websocket.accepted)
        self.assertEqual(websocket.sent, [{
            'type': 'auth_error',
            'message': '认证服务暂时不可用，请稍后重试',
            'code': 'auth_unavailable',
            'retryable': True,
        }])
        self.assertEqual(websocket.close_codes, [WS_RETRY_LATER_CLOSE_CODE])

    async def test_revoked_session_remains_non_retryable(self) -> None:
        websocket = _AuthFailureWebSocket()
        with patch(
            'module_mindmap.websocket.mindmap_ws.validate_ws_token',
            new=AsyncMock(side_effect=WsAuthenticationError(
                '登录会话已失效，请重新登录',
                code='session_revoked',
            )),
        ):
            await mindmap_websocket_endpoint(websocket, 7)

        self.assertEqual(websocket.sent[0]['code'], 'session_revoked')
        self.assertFalse(websocket.sent[0]['retryable'])
        self.assertEqual(websocket.close_codes, [4001])


if __name__ == '__main__':
    unittest.main()
