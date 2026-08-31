"""脑图 WebSocket 消息协议边界测试。"""

import base64
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from exceptions.exception import ServiceException
from module_mindmap.service.mindmap_document_service import STRUCTURED_CONTENT_CORRUPT_MESSAGE
from module_mindmap.websocket.mindmap_ws import (
    MAX_AWARENESS_NODE_COUNT,
    MAX_YJS_PATCH_BYTES,
    WS_RETRY_LATER_CLOSE_CODE,
    WebSocketTrafficBudget,
    build_yjs_sync_init_payload,
    decode_base64_payload,
    get_ws_access_error_message,
    get_ws_auth_error_payload,
    get_ws_auth_recheck_action,
    get_ws_client_message_type,
    get_ws_encoded_payload_size,
    get_ws_invalid_message_payload,
    get_ws_rate_limit_payload,
    mindmap_websocket_endpoint,
    normalize_awareness_node_uids,
    normalize_client_mutation_id,
    normalize_ws_capabilities,
    normalize_yjs_patch,
)
from module_mindmap.websocket.room_manager import (
    STRUCTURED_NODE_PATCH_CAPABILITY,
    YJS_CHECKPOINT_CAPABILITY,
)
from module_mindmap.websocket.ws_auth import WsAuthenticationError


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

    def test_only_declared_json_object_messages_enter_protocol_handlers(self) -> None:
        for payload in (None, [], 'update', 1, {'type': None}, {'type': 'future'}):
            with self.subTest(payload=payload):
                self.assertIsNone(get_ws_client_message_type(payload))

        self.assertEqual(
            get_ws_client_message_type({'type': 'update', 'update': 'YWJj'}),
            'update',
        )
        self.assertIsNone(
            get_ws_client_message_type({'type': 'discard_source', 'contentRevision': 3})
        )
        self.assertEqual(get_ws_invalid_message_payload(), {
            'type': 'protocol_error',
            'code': 'invalid_message',
            'message': '协作消息格式或类型无效',
        })

    def test_sync_init_keeps_persisted_sources_aligned_with_states(self) -> None:
        payload = build_yjs_sync_init_payload({
            'source-a': b'state-a',
            'source-b': b'state-b',
        })

        self.assertEqual(payload['type'], 'sync_init')
        self.assertEqual(payload['stateSources'], ['source-a', 'source-b'])
        self.assertEqual(
            [base64.b64decode(state) for state in payload['states']],
            [b'state-a', b'state-b'],
        )
        self.assertEqual(payload['state'], payload['states'][-1])
        modern_payload = build_yjs_sync_init_payload(
            {'source-a': b'state-a', 'source-b': b'state-b'},
            include_legacy_state=False,
        )
        self.assertNotIn('state', modern_payload)
        self.assertEqual(modern_payload['states'], payload['states'])
        self.assertIsNone(build_yjs_sync_init_payload({}))

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

    def test_only_supported_websocket_capabilities_are_negotiated(self) -> None:
        self.assertEqual(
            normalize_ws_capabilities([
                STRUCTURED_NODE_PATCH_CAPABILITY,
                YJS_CHECKPOINT_CAPABILITY,
                'future-unknown-capability',
                7,
            ]),
            {STRUCTURED_NODE_PATCH_CAPABILITY, YJS_CHECKPOINT_CAPABILITY},
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
