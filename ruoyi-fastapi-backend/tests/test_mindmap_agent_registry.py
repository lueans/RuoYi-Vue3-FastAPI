import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from module_mindmap.ai.adapters.base import AgentAdapter, AgentManifest, AgentRunResult
from module_mindmap.ai.adapters.conformance import (
    build_agent_conformance_report,
    validate_agent_adapter,
)
from module_mindmap.ai.adapters.factory import (
    AGENT_ADAPTER_ENTRY_POINT,
    build_mindmap_agent_registry,
    get_mindmap_agent_registry,
)
from module_mindmap.ai.adapters.registry import MindmapAgentRegistry
from module_mindmap.service.mindmap_ai_service import MindmapAiService

EXPECTED_MAX_NODES = 2_000
EXPECTED_MAX_DEPTH = 32
EXPECTED_TOTAL_TOKENS = 20
EXPECTED_COST_USD = 0.01
EXPECTED_FIXTURE_NODES = 2
EXPECTED_FIXTURE_OPERATIONS = 1
EXPECTED_NEEDS_INPUT_QUESTIONS = 1
SMM_V2 = 2


def test_default_registry_exposes_three_product_agents() -> None:
    manifests = get_mindmap_agent_registry().manifests(intent='create', input_type='none')
    assert {manifest.agent_key for manifest in manifests} == {'native_mindmap', 'codex', 'claude'}


def test_default_registry_exposes_all_three_tool_free_discussion_agents() -> None:
    manifests = get_mindmap_agent_registry().manifests(
        intent='discuss',
        input_type='none',
        result_type='message',
    )

    assert {manifest.agent_key for manifest in manifests} == {
        'native_mindmap', 'codex', 'claude',
    }
    assert all('message' in manifest.result_types for manifest in manifests)


def test_registry_does_not_silently_replace_unknown_agent() -> None:
    registry = get_mindmap_agent_registry()
    try:
        registry.get('not-exists')
    except KeyError as exc:
        assert 'not-exists' in str(exc)
    else:
        raise AssertionError('unknown adapter must be rejected')


def test_all_launch_adapters_pass_the_same_registration_contract() -> None:
    registry = get_mindmap_agent_registry()
    for manifest in registry.manifests():
        assert manifest.supports_cancellation is True
        assert manifest.supports_needs_input is True
        assert manifest.supports_structured_output is True
        assert manifest.max_nodes == EXPECTED_MAX_NODES
        assert manifest.max_depth == EXPECTED_MAX_DEPTH
        assert manifest.tool_contract_version == '1.0'
        assert SMM_V2 in manifest.smm_versions

    native_manifest = registry.get('native_mindmap').get_manifest()
    assert native_manifest.supports_sessions is False
    assert native_manifest.network_allowed is True


def test_all_launch_adapters_pass_deterministic_tool_and_artifact_fixtures() -> None:
    registry = get_mindmap_agent_registry()
    for manifest in registry.manifests():
        report = build_agent_conformance_report(registry.get(manifest.agent_key))
        assert report['assessmentScope'] == 'deterministic_contract_fixture'
        assert report['providerExecution'] == 'not_run'
        assert report['securityFaultInjection'] == 'not_run'
        assert report['releaseEligible'] is False
        assert report['fixture']['nodeCount'] == EXPECTED_FIXTURE_NODES
        assert report['fixture']['operationCount'] == EXPECTED_FIXTURE_OPERATIONS
        assert (
            report['fixture']['needsInputQuestionCount']
            == EXPECTED_NEEDS_INPUT_QUESTIONS
        )
        assert {'needsInput', 'structuredOutput'}.issubset({
            check['name'] for check in report['checks']
        })
        assert {check['status'] for check in report['checks']} == {'passed'}


def test_future_adapter_cannot_register_without_manifest_contract() -> None:
    class InvalidAdapter:
        def get_manifest(self) -> object:
            return type('Manifest', (), {'agent_key': 'invalid'})()

    try:
        MindmapAgentRegistry().register(InvalidAdapter())
    except ValueError as exc:
        assert '生命周期方法' in str(exc)
    else:
        raise AssertionError('non-conformant adapter must be rejected')


def test_future_adapter_must_implement_explicit_cancellation() -> None:
    class NoCancelAdapter(AgentAdapter):
        def get_manifest(self) -> AgentManifest:
            return AgentManifest(
                agent_key='no_cancel',
                display_name='No Cancel',
                adapter_version='1.0.0',
                sdk_name='future-sdk',
                sdk_version='1.0.0',
                runtime_version='1.0.0',
                intents=('create',),
                input_types=('none',),
                supports_sessions=False,
                supports_streaming=False,
                supports_usage=False,
                status='enabled',
            )

        async def run(self, context: object, emit: object) -> AgentRunResult:
            raise NotImplementedError

    try:
        MindmapAgentRegistry().register(NoCancelAdapter())
    except ValueError as exc:
        assert 'cancel' in str(exc)
    else:
        raise AssertionError('adapter without explicit cancellation must be rejected')


def test_session_capable_adapter_must_implement_both_cleanup_methods() -> None:
    class SessionAdapterWithoutCleanup(AgentAdapter):
        def get_manifest(self) -> AgentManifest:
            return AgentManifest(
                agent_key='incomplete_session',
                display_name='Incomplete Session',
                adapter_version='1.0.0',
                sdk_name='future-sdk',
                sdk_version='1.0.0',
                runtime_version='1.0.0',
                intents=('create',),
                input_types=('none',),
                supports_sessions=True,
                supports_streaming=False,
                supports_usage=False,
                status='enabled',
            )

        async def run(self, context: object, emit: object) -> AgentRunResult:
            raise NotImplementedError

        async def cancel(self, job_id: str) -> bool:
            return True

    class SessionAdapterWithOnlyExactPurge(SessionAdapterWithoutCleanup):
        async def purge_session(self, external_session_id: str) -> bool:
            return bool(external_session_id)

    def assert_rejected(adapter: AgentAdapter, missing_method: str) -> None:
        try:
            validate_agent_adapter(adapter)
        except ValueError as exc:
            assert missing_method in str(exc)
        else:
            raise AssertionError(
                f'session adapter without {missing_method} must be rejected'
            )

    assert_rejected(SessionAdapterWithoutCleanup(), 'purge_session')
    assert_rejected(SessionAdapterWithOnlyExactPurge(), 'cleanup_expired_sessions')


def test_server_installed_future_adapter_is_discovered_without_editing_product_registry() -> None:
    class FutureAdapter(AgentAdapter):
        def get_manifest(self) -> AgentManifest:
            return AgentManifest(
                agent_key='future_agent',
                display_name='Future Agent',
                adapter_version='1.0.0',
                sdk_name='future-sdk',
                sdk_version='1.0.0',
                runtime_version='1.0.0',
                intents=('create',),
                input_types=('none',),
                supports_sessions=True,
                supports_streaming=True,
                supports_usage=True,
                status='enabled',
            )

        async def run(self, context: object, emit: object) -> AgentRunResult:
            raise NotImplementedError

        async def cancel(self, job_id: str) -> bool:
            return True

        async def purge_session(self, external_session_id: str) -> bool:
            return bool(external_session_id)

        async def cleanup_expired_sessions(self) -> int:
            return 0

    entry_point = SimpleNamespace(name='future-agent', load=lambda: FutureAdapter)
    discovered = SimpleNamespace(select=lambda *, group: [entry_point] if group == AGENT_ADAPTER_ENTRY_POINT else [])

    with patch(
        'module_mindmap.ai.adapters.factory.metadata.entry_points',
        return_value=discovered,
    ):
        registry = build_mindmap_agent_registry()

    assert registry.get('future_agent').get_manifest().sdk_name == 'future-sdk'


def test_common_usage_contract_normalizes_tokens_and_cost() -> None:
    adapter = get_mindmap_agent_registry().get('native_mindmap')
    usage = adapter.collect_usage(AgentRunResult(
        title='x',
        artifact={},
        summary={},
        operations=[],
        usage={'input_tokens': 12, 'output_tokens': 8, 'cost': 0.01},
    ))

    assert usage['total_tokens'] == EXPECTED_TOTAL_TOKENS
    assert usage['totalCostUsd'] == EXPECTED_COST_USD


@pytest.mark.asyncio
async def test_failed_deterministic_conformance_cannot_claim_provider_execution() -> None:
    adapter = get_mindmap_agent_registry().get('codex')
    connector = SimpleNamespace()
    database = SimpleNamespace(commit=AsyncMock())
    update_connector = AsyncMock()

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.get_mindmap_agent_registry',
            return_value=SimpleNamespace(get=lambda _agent_key: adapter),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.build_agent_conformance_report',
            side_effect=RuntimeError('private adapter detail'),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_connector',
            new=AsyncMock(side_effect=[connector, connector]),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_connector',
            new=update_connector,
        ),
        patch.object(
            MindmapAiService,
            '_connector_model',
            return_value=SimpleNamespace(conformance_status='failed'),
        ),
    ):
        result = await MindmapAiService.conformance_connector(
            database,
            'codex',
            'admin',
        )

    assert result.conformance_status == 'failed'
    values = update_connector.await_args.args[2]
    report = json.loads(values['conformance_report_json'])
    assert report['assessmentScope'] == 'deterministic_contract_fixture'
    assert report['providerExecution'] == 'not_run'
    assert report['securityFaultInjection'] == 'not_run'
    assert report['releaseEligible'] is False
    assert 'private adapter detail' not in values['conformance_report_json']
