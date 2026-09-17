from __future__ import annotations

import copy
import json
import unittest

from mindmap_agent_kit import (
    MAX_AGENT_MESSAGE_LENGTH,
    MAX_AGENT_MESSAGE_TITLE_LENGTH,
    AgentContractError,
    ArtifactValidationError,
    MindmapBuilder,
    build_agent_message_result,
    normalize_agent_manifest,
    normalize_agent_message_result,
    resolve_result_types,
    validate_agent_request,
)
from mindmap_agent_kit.mcp_server import TOOLS, MindmapMcpServer


class AgentContractTests(unittest.TestCase):
    def test_mindmap_tool_contract_exposes_only_supported_node_fields(self) -> None:
        start_document = next(item for item in TOOLS if item['name'] == 'mindmap.start_document')
        update_nodes = next(item for item in TOOLS if item['name'] == 'mindmap.update_nodes')
        move_nodes = next(item for item in TOOLS if item['name'] == 'mindmap.move_nodes')
        add_nodes = next(item for item in TOOLS if item['name'] == 'mindmap.add_nodes')

        self.assertEqual(
            set(start_document['inputSchema']['properties']),
            {'title', 'layout'},
        )
        self.assertEqual(
            set(add_nodes['inputSchema']['properties']['nodes']['items']['properties']),
            {
                'parentUid',
                'clientRef',
                'text',
                'note',
                'hyperlink',
                'tag',
            },
        )
        update_item = update_nodes['inputSchema']['properties']['updates']['items']
        self.assertEqual(set(update_item['required']), {'nodeUid', 'patch'})
        self.assertFalse(update_item['additionalProperties'])
        self.assertEqual(
            set(update_item['properties']['patch']['properties']),
            {
                'text',
                'note',
                'hyperlink',
                'tag',
            },
        )
        move_item = move_nodes['inputSchema']['properties']['moves']['items']
        self.assertEqual(set(move_item['required']), {'nodeUid', 'parentUid'})
        self.assertEqual(
            move_item['properties']['index'],
            {
                'type': 'integer',
                'minimum': 0,
            },
        )
        self.assertFalse(move_item['additionalProperties'])

        builder = MindmapBuilder('Payment tests')
        with self.assertRaisesRegex(ArtifactValidationError, 'unknown field'):
            builder.add_nodes(
                [
                    {
                        'parentUid': builder.root_uid,
                        'text': 'Successful payment',
                        'unsupported': True,
                    }
                ]
            )

    def test_mcp_server_returns_tool_errors_for_nested_schema_violations(self) -> None:
        server = MindmapMcpServer()
        draft_id = server.call_tool('mindmap.start_document', {'title': 'Root'})['draftId']
        response = server.handle({
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'tools/call',
            'params': {
                'name': 'mindmap.add_nodes',
                'arguments': {'draftId': draft_id, 'nodes': [[]]},
            },
        })

        self.assertTrue(response['result']['isError'])
        self.assertIn('nodes[0] must be an object', response['result']['content'][0]['text'])

    def test_builder_mutations_roll_back_the_whole_call_on_error(self) -> None:
        builder = MindmapBuilder('Payment tests')
        initial_document = builder.read_projection()

        with self.assertRaisesRegex(ArtifactValidationError, 'parent node does not exist'):
            builder.add_nodes(
                [
                    {'parentUid': builder.root_uid, 'text': 'Successful payment'},
                    {'parentUid': 'missing-parent', 'text': 'Invalid branch'},
                ]
            )
        self.assertEqual(builder.document, initial_document)
        self.assertEqual(builder.operations, [])

        created = builder.add_nodes(
            [
                {'parentUid': builder.root_uid, 'text': 'Successful payment'},
                {'parentUid': builder.root_uid, 'text': 'Failed payment'},
            ]
        )['created']
        first_uid, second_uid = (item['nodeUid'] for item in created)

        before_document = builder.read_projection()
        before_operations = copy.deepcopy(builder.operations)
        with self.assertRaisesRegex(ArtifactValidationError, 'invalid update'):
            builder.update_nodes(
                [
                    {'nodeUid': first_uid, 'patch': {'text': 'Updated payment'}},
                    {'nodeUid': 'missing-node', 'patch': {'text': 'Invalid update'}},
                ]
            )
        self.assertEqual(builder.document, before_document)
        self.assertEqual(builder.operations, before_operations)

        with self.assertRaisesRegex(ArtifactValidationError, 'index is out of range'):
            builder.move_nodes(
                [
                    {'nodeUid': first_uid, 'parentUid': second_uid},
                    {'nodeUid': second_uid, 'parentUid': builder.root_uid, 'index': 999},
                ]
            )
        self.assertEqual(builder.document, before_document)
        self.assertEqual(builder.operations, before_operations)

        with self.assertRaisesRegex(ArtifactValidationError, 'unsupported layout'):
            builder.set_document_meta(title='Changed title', layout='unsupported')
        self.assertEqual(builder.document, before_document)
        self.assertEqual(builder.operations, before_operations)

    def test_legacy_manifest_defaults_to_artifact_only(self) -> None:
        manifest = {'intents': ['create']}

        self.assertEqual(resolve_result_types(manifest), ('artifact',))
        self.assertEqual(normalize_agent_manifest(manifest)['resultTypes'], ['artifact'])
        self.assertEqual(
            validate_agent_request('create', 'file', manifest=manifest)['resultType'],
            'artifact',
        )

    def test_discussion_manifest_must_opt_in_to_message(self) -> None:
        with self.assertRaisesRegex(AgentContractError, 'resultTypes message'):
            normalize_agent_manifest({'intents': ['create', 'discuss']})

        manifest = {
            'intents': ['create', 'discuss'],
            'resultTypes': ['artifact', 'message'],
        }
        self.assertEqual(
            validate_agent_request('discuss', 'message', manifest=manifest),
            {'intent': 'discuss', 'target': 'message', 'resultType': 'message'},
        )

    def test_message_target_is_reserved_for_discussion(self) -> None:
        with self.assertRaisesRegex(AgentContractError, 'must target message'):
            validate_agent_request('discuss', 'proposal')
        with self.assertRaisesRegex(AgentContractError, 'only discuss'):
            validate_agent_request('create', 'message')

    def test_message_completion_is_closed_and_normalized(self) -> None:
        result = normalize_agent_message_result(
            {
                'completionState': 'message_completed',
                'title': '  支付\n 用例  ',
                'content': '\n可先梳理支付失败分支。\n',
                'contentType': 'text/plain',
            }
        )

        self.assertEqual(result['title'], '支付 用例')
        self.assertEqual(result['content'], '可先梳理支付失败分支。')
        self.assertEqual(
            build_agent_message_result('允许\n多行和\t制表符'),
            {
                'completionState': 'message_completed',
                'title': None,
                'content': '允许\n多行和\t制表符',
                'contentType': 'text/plain',
            },
        )
        self.assertEqual(
            normalize_agent_message_result(json.dumps(result, ensure_ascii=False)),
            result,
        )
        with self.assertRaisesRegex(AgentContractError, 'structured contract'):
            normalize_agent_message_result({**result, 'unexpected': True})

    def test_message_completion_rejects_control_character_and_both_limits(self) -> None:
        with self.assertRaisesRegex(AgentContractError, 'unsafe or overlong'):
            build_agent_message_result('unsafe\x00value')
        with self.assertRaisesRegex(AgentContractError, 'unsafe or overlong'):
            build_agent_message_result('a' * (MAX_AGENT_MESSAGE_LENGTH + 1))
        with self.assertRaisesRegex(AgentContractError, 'unsafe or overlong'):
            build_agent_message_result('content', title='t' * (MAX_AGENT_MESSAGE_TITLE_LENGTH + 1))
        # 17,000 emoji are below the 20,000-character limit but above 64 KiB.
        with self.assertRaisesRegex(AgentContractError, 'unsafe or overlong'):
            build_agent_message_result('\U0001f642' * 17_000)


if __name__ == '__main__':
    unittest.main()
