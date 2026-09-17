"""新 Agent Adapter 的确定性准入检查。"""
from __future__ import annotations

import re
from typing import Any

from module_mindmap.ai.adapters.base import (
    AgentAdapter,
    AgentManifest,
    agent_message_result,
    agent_needs_input_result,
)
from module_mindmap.ai.document import validate_smm_artifact
from module_mindmap.ai.tool_contract import MindmapToolService

AGENT_KEY_PATTERN = re.compile(r'^[a-z][a-z0-9_]{1,63}$')
REQUIRED_INPUT_TYPES = frozenset({'none'})
SMM_V2 = 2
MAX_NODES = 2_000
MAX_DEPTH = 32
FIXTURE_NODE_COUNT = 2
FIXTURE_OPERATION_COUNT = 1
REQUIRED_LIFECYCLE_METHODS = (
    'get_manifest',
    'healthcheck',
    'start',
    'send_message',
    'cancel',
    'resume',
    'collect_usage',
    'purge_session',
    'cleanup_expired_sessions',
    'close',
)
REQUIRED_SESSION_LIFECYCLE_METHODS = (
    'purge_session',
    'cleanup_expired_sessions',
)


def validate_agent_manifest(manifest: AgentManifest) -> None:
    if not AGENT_KEY_PATTERN.fullmatch(manifest.agent_key):
        raise ValueError('Agent Adapter 的 agentKey 无效')
    if not manifest.display_name.strip() or not manifest.adapter_version.strip():
        raise ValueError('Agent Adapter 缺少名称或版本')
    if not manifest.sdk_name.strip() or not manifest.intents:
        raise ValueError('Agent Adapter 缺少 SDK 或意图能力声明')
    if not REQUIRED_INPUT_TYPES.issubset(manifest.input_types):
        raise ValueError('Agent Adapter 至少必须支持无来源创建')
    if SMM_V2 not in manifest.smm_versions or manifest.tool_contract_version != '1.0':
        raise ValueError('Agent Adapter 与当前 Tool Contract 或 SMM v2 不兼容')
    if manifest.error_contract_version != '1.0' or not manifest.supports_structured_output:
        raise ValueError('Agent Adapter 与当前结构化输出或错误合同不兼容')
    if not manifest.supports_cancellation:
        raise ValueError('Agent Adapter 必须支持取消合同')
    if not manifest.supports_needs_input:
        raise ValueError('Agent Adapter 必须支持 needs_input 终结合同')
    if (
        not manifest.result_types
        or not set(manifest.result_types).issubset({'artifact', 'message'})
        or ('discuss' in manifest.intents and 'message' not in manifest.result_types)
    ):
        raise ValueError('Agent Adapter 的结果能力声明无效')
    if not 1 <= manifest.max_nodes <= MAX_NODES or not 1 <= manifest.max_depth <= MAX_DEPTH:
        raise ValueError('Agent Adapter 声明的结构上限无效')


def validate_agent_adapter(adapter: AgentAdapter) -> None:
    for method_name in REQUIRED_LIFECYCLE_METHODS:
        if not callable(getattr(adapter, method_name, None)):
            raise ValueError(f'Agent Adapter 缺少生命周期方法: {method_name}')
    if adapter.__class__.cancel is AgentAdapter.cancel:
        raise ValueError('Agent Adapter 必须实现可终止或可确认取消的 cancel 方法')
    manifest = adapter.get_manifest()
    validate_agent_manifest(manifest)
    if manifest.supports_sessions:
        for method_name in REQUIRED_SESSION_LIFECYCLE_METHODS:
            implementation = getattr(adapter.__class__, method_name, None)
            if implementation is getattr(AgentAdapter, method_name):
                raise ValueError(
                    '声明支持会话的 Agent Adapter 必须实现会话生命周期方法: '
                    f'{method_name}'
                )


def build_agent_conformance_report(adapter: AgentAdapter) -> dict[str, Any]:
    """运行不访问供应商、数据库或文件系统的确定性准入样例。"""
    validate_agent_adapter(adapter)
    manifest = adapter.get_manifest()
    tools = MindmapToolService()
    root_uid = tools.start_document('Agent conformance fixture')['rootUid']
    tools.add_nodes([{
        'clientRef': 'fixture-child',
        'parentUid': root_uid,
        'text': 'Valid child',
    }])
    draft_summary = tools.validate_draft()
    artifact, artifact_summary, operations = tools.complete_artifact(
        title='Agent conformance fixture',
        agent_key=manifest.agent_key,
        adapter_version=manifest.adapter_version,
        prompt_version='conformance-1',
        artifact_id=f'conformance-{manifest.agent_key}',
    )
    _normalized, validated_summary = validate_smm_artifact(artifact)
    needs_input = agent_needs_input_result({
        'completionState': 'needs_input',
        'questions': [{
            'questionId': 'scope',
            'prompt': '希望脑图覆盖哪些业务范围？',
        }],
    })
    discussion = agent_message_result({
        'completionState': 'message_completed',
        'title': '讨论样例',
        'content': '这是不修改脑图的文字答复。',
        'contentType': 'text/plain',
    })
    if (
        draft_summary['nodeCount'] != FIXTURE_NODE_COUNT
        or artifact_summary['nodeCount'] != FIXTURE_NODE_COUNT
    ):
        raise ValueError('Agent Tool Contract 固定样例节点统计不一致')
    if (
        validated_summary['nodeCount'] != FIXTURE_NODE_COUNT
        or len(operations) != FIXTURE_OPERATION_COUNT
    ):
        raise ValueError('Agent Tool Contract 固定样例产物不一致')
    return {
        # This endpoint intentionally performs no provider call.  Keep that
        # limitation machine-readable so a green deterministic fixture cannot
        # be presented as the release conformance required by the PRD.
        'assessmentScope': 'deterministic_contract_fixture',
        'providerExecution': 'not_run',
        'securityFaultInjection': 'not_run',
        'releaseEligible': False,
        'contractVersion': manifest.tool_contract_version,
        'errorContractVersion': manifest.error_contract_version,
        'smmVersions': list(manifest.smm_versions),
        'adapterVersion': manifest.adapter_version,
        'sdkVersion': manifest.sdk_version,
        'runtimeVersion': manifest.runtime_version,
        'checks': [
            {'name': 'manifest', 'status': 'passed'},
            {'name': 'lifecycle', 'status': 'passed'},
            {'name': 'structuredOutput', 'status': 'passed'},
            {'name': 'cancellation', 'status': 'passed'},
            {'name': 'sessionLifecycle', 'status': 'passed'},
            {'name': 'needsInput', 'status': 'passed'},
            {'name': 'messageResult', 'status': 'passed'},
            {'name': 'limits', 'status': 'passed'},
            {'name': 'toolContractFixture', 'status': 'passed'},
            {'name': 'smmV2HashRoundtrip', 'status': 'passed'},
        ],
        'fixture': {
            'nodeCount': validated_summary['nodeCount'],
            'treeDepth': validated_summary['treeDepth'],
            'operationCount': len(operations),
            'needsInputQuestionCount': len(needs_input.questions),
            'messageBytes': len(discussion.content.encode('utf-8')),
        },
    }
