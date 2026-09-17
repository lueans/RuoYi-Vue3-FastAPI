"""Agent Connector 策略、权限与只写凭据引用测试。"""

import asyncio
import inspect
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pydantic import ValidationError

from exceptions.exception import ServiceException
from module_mindmap.ai.adapters.base import AgentManifest
from module_mindmap.ai.document import MindmapArtifactError
from module_mindmap.controller import mindmap_ai_controller
from module_mindmap.entity.vo.mindmap_ai_vo import (
    MindmapAiConnectorUpdateModel,
    MindmapAiJobCreateModel,
)
from module_mindmap.service.mindmap_ai_service import (
    AgentRuntimePolicy,
    MindmapAiService,
    MindmapAiTaskManager,
)
from server import create_app

EXPECTED_POLICY_BUDGET = 2.5
EXPECTED_CONNECTOR_CHECKS = 2


def _manifest(**overrides: object) -> SimpleNamespace:
    values = {
        'agent_key': 'codex',
        'status': 'enabled',
        'status_reason': None,
        'network_allowed': True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _listed_manifest(
    agent_key: str,
    *,
    status: str = 'enabled',
    status_reason: str | None = None,
) -> AgentManifest:
    return AgentManifest(
        agent_key=agent_key,
        display_name=f'{agent_key} Agent',
        adapter_version='1.0.0',
        sdk_name=f'{agent_key}-sdk',
        sdk_version='1.0.0',
        runtime_version='1.0.0',
        intents=('create',),
        input_types=('none',),
        supports_sessions=True,
        supports_streaming=True,
        supports_usage=True,
        status=status,
        status_reason=status_reason,
        network_allowed=True,
        default_model_ref='test-model',
    )


def _connector(**overrides: object) -> SimpleNamespace:
    values = {
        'enabled': 1,
        'rollout_percentage': 100,
        'health_status': 'healthy',
        'health_reason': None,
        'last_health_time': datetime.now(),
        'network_policy': 'adapter_default',
        'credential_ref': None,
        'data_region': None,
        'retention_policy': None,
        'model_allowlist_json': '[]',
        'conformance_status': 'unknown',
        'conformance_report_json': None,
        'last_conformance_time': None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_connector_conformance_evidence_becomes_stale_after_manifest_change() -> None:
    manifest = _listed_manifest('codex')
    old_report = {
        'adapterVersion': '0.9.0',
        'sdkVersion': manifest.sdk_version,
        'runtimeVersion': manifest.runtime_version,
        'contractVersion': manifest.tool_contract_version,
        'errorContractVersion': manifest.error_contract_version,
        'smmVersions': list(manifest.smm_versions),
        'releaseEligible': True,
    }
    connector = _connector(
        conformance_status='passed',
        conformance_report_json=json.dumps(old_report),
    )

    status, report = MindmapAiService._connector_conformance_state(connector, manifest)

    assert status == 'stale'
    assert report is not None
    assert report['stale'] is True
    assert report['staleReason'] == 'MANIFEST_VERSION_CHANGED'
    assert report['versionMismatches'] == ['adapterVersion']
    assert report['expectedVersions']['adapterVersion'] == '1.0.0'
    assert report['releaseEligible'] is False


def test_connector_conformance_keeps_current_failure_and_rejects_missing_evidence() -> None:
    manifest = _listed_manifest('claude')
    current_versions = {
        'adapterVersion': manifest.adapter_version,
        'sdkVersion': manifest.sdk_version,
        'runtimeVersion': manifest.runtime_version,
        'contractVersion': manifest.tool_contract_version,
        'errorContractVersion': manifest.error_contract_version,
        'smmVersions': list(manifest.smm_versions),
    }
    failed = _connector(
        conformance_status='failed',
        conformance_report_json=json.dumps({**current_versions, 'releaseEligible': False}),
    )
    invalid = _connector(
        conformance_status='passed',
        conformance_report_json='not-json',
    )

    failed_status, failed_report = MindmapAiService._connector_conformance_state(
        failed,
        manifest,
    )
    invalid_status, invalid_report = MindmapAiService._connector_conformance_state(
        invalid,
        manifest,
    )

    assert failed_status == 'failed'
    assert failed_report == {**current_versions, 'releaseEligible': False}
    assert invalid_status == 'stale'
    assert invalid_report is not None
    assert invalid_report['staleReason'] == 'MISSING_OR_INVALID_REPORT'
    assert invalid_report['releaseEligible'] is False


@pytest.mark.asyncio
async def test_connector_policy_blocks_disabled_unhealthy_and_network_denied() -> None:
    db = SimpleNamespace()
    connector = SimpleNamespace(
        enabled=0,
        rollout_percentage=100,
        health_status='healthy',
        health_reason=None,
        network_policy='adapter_default',
    )
    with patch(
        'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_connector',
        new=AsyncMock(return_value=connector),
    ):
        with pytest.raises(ServiceException) as disabled:
            await MindmapAiService._ensure_connector_available(db, _manifest(), 1)
        assert '管理员停用' in disabled.value.message

        connector.enabled = 1
        connector.health_status = 'unhealthy'
        connector.health_reason = '认证失败'
        with pytest.raises(ServiceException) as unhealthy:
            await MindmapAiService._ensure_connector_available(db, _manifest(), 1)
        assert '认证失败' in unhealthy.value.message

        connector.health_status = 'healthy'
        connector.network_policy = 'deny'
        with pytest.raises(ServiceException) as denied:
            await MindmapAiService._ensure_connector_available(db, _manifest(), 1)
        assert '网络策略' in denied.value.message


@pytest.mark.asyncio
async def test_connector_rollout_is_deterministic_and_zero_disables_everyone() -> None:
    connector = SimpleNamespace(
        enabled=1,
        rollout_percentage=0,
        health_status='unknown',
        health_reason=None,
        network_policy='adapter_default',
    )
    with patch(
        'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_connector',
        new=AsyncMock(return_value=connector),
    ):
        for user_id in (1, 42, 99_999):
            with pytest.raises(ServiceException) as rollout:
                await MindmapAiService._ensure_connector_available(
                    SimpleNamespace(), _manifest(), user_id,
                )
            assert '尚未向当前用户开放' in rollout.value.message


@pytest.mark.asyncio
async def test_unprovisioned_adapter_is_not_user_runnable() -> None:
    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_connector',
            new=AsyncMock(return_value=None),
        ),
        pytest.raises(ServiceException) as missing,
    ):
        await MindmapAiService._ensure_connector_available(
            SimpleNamespace(), _manifest(agent_key='future_agent'), 1,
        )
    assert '管理员配置 Connector' in missing.value.message


@pytest.mark.asyncio
async def test_agent_listing_never_probes_provider_and_keeps_unavailable_agents_visible() -> None:
    unknown_manifest = _listed_manifest('codex')
    disabled_manifest = _listed_manifest(
        'claude',
        status='disabled',
        status_reason='Claude 功能开关已关闭',
    )
    missing_manifest = _listed_manifest('future_agent')
    unknown = _connector(health_status='unknown')
    disabled = _connector(health_status='healthy')

    async def connector_for_agent(
        _db: object,
        agent_key: str,
        *,
        for_update: bool = False,
    ) -> SimpleNamespace | None:
        assert for_update is False
        return {'codex': unknown, 'claude': disabled}.get(agent_key)

    registry = SimpleNamespace(
        manifests=Mock(return_value=(unknown_manifest, disabled_manifest, missing_manifest)),
        get=Mock(side_effect=AssertionError('能力清单不应触发 Provider 健康检查')),
    )
    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.get_mindmap_agent_registry',
            return_value=registry,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_connector',
            new=AsyncMock(side_effect=connector_for_agent),
        ),
    ):
        agents = await MindmapAiService.list_agents(
            SimpleNamespace(),
            42,
            intent='create',
            input_type='none',
        )

    assert [item['agentKey'] for item in agents] == ['codex', 'claude', 'future_agent']
    assert agents[0]['status'] == 'enabled'
    assert agents[0]['healthStatus'] == 'unknown'
    assert agents[0]['healthReason'] is None
    assert agents[1]['status'] == 'disabled'
    assert agents[1]['statusReason'] == 'Claude 功能开关已关闭'
    assert agents[1]['healthStatus'] == 'healthy'
    assert agents[2]['status'] == 'disabled'
    assert '尚未由管理员配置 Connector' in agents[2]['statusReason']
    assert agents[2]['healthStatus'] == 'unknown'
    registry.get.assert_not_called()
    registry.manifests.assert_called_once_with(intent='create', input_type='none')


@pytest.mark.asyncio
async def test_unknown_connector_listing_mode_skips_healthcheck() -> None:
    connector = _connector(health_status='unknown')
    adapter = SimpleNamespace(healthcheck=AsyncMock(return_value=(True, None)))
    registry = SimpleNamespace(get=Mock(return_value=adapter))
    db = SimpleNamespace(commit=AsyncMock(), flush=AsyncMock())
    update = AsyncMock()
    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.get_mindmap_agent_registry',
            return_value=registry,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_connector',
            new=AsyncMock(return_value=connector),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_connector',
            new=update,
        ),
    ):
        result = await MindmapAiService._ensure_connector_available(
            db,
            _manifest(default_model_ref='gpt-test'),
            7,
            preflight_unknown=False,
        )

    assert result is connector
    registry.get.assert_not_called()
    adapter.healthcheck.assert_not_awaited()
    update.assert_not_awaited()
    db.commit.assert_not_awaited()
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_connector_preflight_persists_healthy_once() -> None:
    connector = _connector(health_status='unknown', health_reason='尚未检查')
    adapter = SimpleNamespace(healthcheck=AsyncMock(return_value=(True, None)))
    registry = SimpleNamespace(get=Mock(return_value=adapter))
    db = SimpleNamespace(commit=AsyncMock(), flush=AsyncMock())
    update = AsyncMock()
    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.get_mindmap_agent_registry',
            return_value=registry,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_connector',
            new=AsyncMock(return_value=connector),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_connector',
            new=update,
        ),
    ):
        result = await MindmapAiService._ensure_connector_available(
            db,
            _manifest(default_model_ref='gpt-test'),
            7,
        )

    assert result is connector
    adapter.healthcheck.assert_awaited_once_with({}, model_ref='gpt-test')
    assert update.await_count == 1
    values = update.await_args.args[2]
    assert values['health_status'] == 'healthy'
    assert values['health_reason'] is None
    assert values['last_health_time'] is not None
    assert connector.health_status == 'healthy'
    assert connector.health_reason is None
    db.commit.assert_awaited_once_with()
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_healthy_connector_is_rechecked_before_task_creation() -> None:
    connector = _connector(last_health_time=datetime.now() - timedelta(hours=1))
    adapter = SimpleNamespace(healthcheck=AsyncMock(return_value=(True, None)))
    registry = SimpleNamespace(get=Mock(return_value=adapter))
    db = SimpleNamespace(commit=AsyncMock(), flush=AsyncMock())
    update = AsyncMock()
    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.get_mindmap_agent_registry',
            return_value=registry,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_connector',
            new=AsyncMock(return_value=connector),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_connector',
            new=update,
        ),
    ):
        result = await MindmapAiService._ensure_connector_available(
            db,
            _manifest(default_model_ref='gpt-test'),
            7,
        )

    assert result is connector
    adapter.healthcheck.assert_awaited_once_with({}, model_ref='gpt-test')
    assert update.await_args.args[2]['health_status'] == 'healthy'
    db.commit.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_agent_listing_downgrades_stale_health_without_provider_probe() -> None:
    manifest = _listed_manifest('codex')
    connector = _connector(last_health_time=datetime.now() - timedelta(hours=1))
    registry = SimpleNamespace(
        manifests=Mock(return_value=(manifest,)),
        get=Mock(side_effect=AssertionError('能力清单不应触发 Provider 健康检查')),
    )
    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.get_mindmap_agent_registry',
            return_value=registry,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_connector',
            new=AsyncMock(return_value=connector),
        ),
    ):
        agents = await MindmapAiService.list_agents(SimpleNamespace(), 7)

    assert agents[0]['status'] == 'enabled'
    assert agents[0]['healthStatus'] == 'unknown'
    assert '已过期' in agents[0]['healthReason']
    registry.get.assert_not_called()


@pytest.mark.asyncio
async def test_failed_unknown_connector_preflight_is_request_local() -> None:
    connector = _connector(health_status='unknown')
    adapter = SimpleNamespace(healthcheck=AsyncMock(return_value=(False, '当前用户认证不可用')))
    registry = SimpleNamespace(get=Mock(return_value=adapter))
    db = SimpleNamespace(commit=AsyncMock(), flush=AsyncMock())
    update = AsyncMock()
    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.get_mindmap_agent_registry',
            return_value=registry,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_connector',
            new=AsyncMock(return_value=connector),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_connector',
            new=update,
        ),
        pytest.raises(ServiceException) as failure,
    ):
        await MindmapAiService._ensure_connector_available(
            db,
            _manifest(default_model_ref='gpt-test'),
            7,
        )

    assert failure.value.message == '当前用户认证不可用'
    assert connector.health_status == 'unknown'
    update.assert_not_awaited()
    db.commit.assert_not_awaited()
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_connector_preflight_has_a_total_timeout() -> None:
    async def never_finishes(
        _credential_env: dict[str, str],
        *,
        model_ref: str | None,
    ) -> tuple[bool, str | None]:
        del model_ref
        await asyncio.Event().wait()
        return True, None

    connector = _connector(health_status='unknown')
    adapter = SimpleNamespace(healthcheck=AsyncMock(side_effect=never_finishes))
    registry = SimpleNamespace(get=Mock(return_value=adapter))
    db = SimpleNamespace(commit=AsyncMock(), flush=AsyncMock())
    update = AsyncMock()
    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.get_mindmap_agent_registry',
            return_value=registry,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_connector',
            new=AsyncMock(return_value=connector),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_connector',
            new=update,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.CONNECTOR_HEALTHCHECK_TIMEOUT_SECONDS',
            0.001,
        ),
        pytest.raises(ServiceException) as timeout,
    ):
        await MindmapAiService._ensure_connector_available(
            db,
            _manifest(default_model_ref='gpt-test'),
            7,
        )

    assert '超时' in timeout.value.message
    assert connector.health_status == 'unknown'
    update.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_job_runs_only_one_unknown_health_preflight() -> None:
    manifest = _listed_manifest('codex')
    request = MindmapAiJobCreateModel(agentKey='codex', prompt='生成脑图')
    connector = _connector(health_status='unknown')
    ensure = AsyncMock(return_value=connector)
    stop_after_connector_checks = RuntimeError('connector checks observed')

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.get_mindmap_agent_registry',
            return_value=SimpleNamespace(
                get=Mock(return_value=SimpleNamespace(get_manifest=Mock(return_value=manifest))),
            ),
        ),
        patch.object(MindmapAiService, '_ensure_connector_available', new=ensure),
        patch.object(
            MindmapAiService,
            '_prepare_source_for_job',
            new=AsyncMock(return_value=(None, None, None, None, None)),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job_by_idempotency',
            new=AsyncMock(return_value=None),
        ),
        patch.object(
            MindmapAiService,
            '_runtime_policy',
            side_effect=stop_after_connector_checks,
        ),
        pytest.raises(RuntimeError) as stopped,
    ):
        await MindmapAiService.create_job(
            SimpleNamespace(),
            request,
            user_id=7,
            idempotency_key='connector-preflight-once',
        )

    assert stopped.value is stop_after_connector_checks
    assert ensure.await_count == EXPECTED_CONNECTOR_CHECKS
    first_check, preflight = ensure.await_args_list
    assert first_check.kwargs == {'preflight_unknown': False}
    assert preflight.kwargs == {'for_update': True, 'preflight_unknown': True}


def test_followup_job_splits_static_check_from_single_unknown_preflight() -> None:
    source = inspect.getsource(MindmapAiService.create_followup_job)

    assert source.count('_ensure_connector_available(') == EXPECTED_CONNECTOR_CHECKS
    assert source.count('preflight_unknown=False') == 1
    assert source.count('preflight_unknown=True') == 1


def test_connector_accepts_only_server_side_secret_references() -> None:
    assert MindmapAiConnectorUpdateModel(credentialRef='secret://mindmap/claude').credential_ref
    assert MindmapAiConnectorUpdateModel(credentialRef='env://ANTHROPIC_API_KEY').credential_ref
    with pytest.raises(ValidationError, match='服务端密钥引用'):
        MindmapAiConnectorUpdateModel(credentialRef='sk-live-should-never-be-stored')


@pytest.mark.asyncio
async def test_connector_healthcheck_validates_resolved_credential_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('ANTHROPIC_AUTH_TOKEN', 'configured-secret')
    record = SimpleNamespace(credential_ref='env://ANTHROPIC_AUTH_TOKEN')
    manifest = _manifest(agent_key='claude', default_model_ref='haiku')
    adapter = SimpleNamespace(
        get_manifest=Mock(return_value=manifest),
        healthcheck=AsyncMock(return_value=(False, '认证不可用')),
    )
    registry = SimpleNamespace(get=Mock(return_value=adapter))
    db = SimpleNamespace(commit=AsyncMock())
    update = AsyncMock()
    expected = object()

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.get_mindmap_agent_registry',
            return_value=registry,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_connector',
            new=AsyncMock(side_effect=[record, record]),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_connector',
            new=update,
        ),
        patch.object(MindmapAiService, '_connector_model', return_value=expected),
    ):
        result = await MindmapAiService.health_check_connector(db, 'claude', 'admin')

    assert result is expected
    adapter.healthcheck.assert_awaited_once_with(
        {'ANTHROPIC_AUTH_TOKEN': 'configured-secret'},
        model_ref='haiku',
    )
    assert update.await_args.args[2]['health_status'] == 'unhealthy'
    assert update.await_args.args[2]['health_reason'] == '认证不可用'


@pytest.mark.asyncio
async def test_connector_healthcheck_passes_complete_bedrock_credential_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('AWS_ACCESS_KEY_ID', 'access-id')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'secret-key')
    monkeypatch.setenv('AWS_SESSION_TOKEN', 'session-token')
    monkeypatch.setenv('AWS_REGION', 'us-east-1')
    record = SimpleNamespace(credential_ref='env://AWS_ACCESS_KEY_ID')
    manifest = _manifest(agent_key='claude', default_model_ref='bedrock-sonnet')
    adapter = SimpleNamespace(
        get_manifest=Mock(return_value=manifest),
        healthcheck=AsyncMock(return_value=(True, None)),
    )
    registry = SimpleNamespace(get=Mock(return_value=adapter))
    db = SimpleNamespace(commit=AsyncMock())

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.get_mindmap_agent_registry',
            return_value=registry,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_connector',
            new=AsyncMock(side_effect=[record, record]),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_connector',
            new=AsyncMock(),
        ),
        patch.object(MindmapAiService, '_connector_model', return_value=object()),
    ):
        await MindmapAiService.health_check_connector(db, 'claude', 'admin')

    adapter.healthcheck.assert_awaited_once_with({
        'CLAUDE_CODE_USE_BEDROCK': '1',
        'AWS_ACCESS_KEY_ID': 'access-id',
        'AWS_SECRET_ACCESS_KEY': 'secret-key',
        'AWS_SESSION_TOKEN': 'session-token',
        'AWS_REGION': 'us-east-1',
    }, model_ref='bedrock-sonnet')


def test_connector_policy_normalizes_model_allowlist_and_validates_limits() -> None:
    model = MindmapAiConnectorUpdateModel(
        modelAllowlist=[' sonnet ', 'sonnet', '', 'opus'],
        maxBudgetUsd=2.5,
        timeoutSeconds=300,
        maxNodes=500,
        maxDepth=12,
        maxConcurrentJobs=8,
        retentionPolicy='30d',
    )

    assert model.model_allowlist == ['sonnet', 'opus']
    assert model.max_budget_usd == EXPECTED_POLICY_BUDGET
    with pytest.raises(ValidationError):
        MindmapAiConnectorUpdateModel(timeoutSeconds=29)
    with pytest.raises(ValidationError):
        MindmapAiConnectorUpdateModel(maxBudgetUsd=float('nan'))
    with pytest.raises(ValidationError):
        MindmapAiConnectorUpdateModel(retentionPolicy='forever')


def test_runtime_provider_failure_cannot_mutate_global_connector_health() -> None:
    """用户/模型/瞬时网络错误只失败当前任务，不得形成跨用户全局熔断。"""
    task_source = inspect.getsource(MindmapAiTaskManager._run_job)

    assert '_mark_connector_unhealthy' not in task_source
    assert 'update_connector' not in task_source
    assert not hasattr(MindmapAiTaskManager, '_mark_connector_unhealthy')


def test_job_policy_enforces_model_and_requested_structure_limits() -> None:
    manifest = _manifest(
        agent_key='claude',
        default_model_ref='sonnet',
        max_nodes=2_000,
        max_depth=32,
    )
    policy = AgentRuntimePolicy(('sonnet',), 2.0, 300, 100, 8, 2, 30)
    request = MindmapAiJobCreateModel(
        agentKey='claude',
        prompt='生成脑图',
        parameters={'maxNodes': 100, 'maxDepth': 8},
    )

    assert MindmapAiService._validate_job_policy(request, manifest, policy) == 'sonnet'
    request.parameters.max_nodes = 101
    with pytest.raises(ServiceException) as exceeded:
        MindmapAiService._validate_job_policy(request, manifest, policy)
    assert '节点上限' in exceeded.value.message


@pytest.mark.asyncio
async def test_connector_concurrency_limit_counts_persisted_active_jobs() -> None:
    policy = AgentRuntimePolicy((), 5.0, 900, 2_000, 32, 2, 30)
    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.count_active_jobs',
            new=AsyncMock(return_value=2),
        ),
        pytest.raises(ServiceException) as exceeded,
    ):
        await MindmapAiService._ensure_concurrency_available(
            SimpleNamespace(), 'claude', policy,
        )
    assert '并发上限 2' in exceeded.value.message


def test_task_result_policy_rejects_structure_cost_and_invalid_usage() -> None:
    with pytest.raises(MindmapArtifactError) as structure:
        MindmapAiTaskManager._enforce_result_policy(
            {'nodeCount': 101, 'treeDepth': 5}, {},
            max_nodes=100, max_depth=8, max_budget_usd=1.0,
    )
    assert structure.value.code == 'AI_BUDGET_EXCEEDED'
    assert '最终节点 101/100' in str(structure.value)
    assert '最终层级 5/8' in str(structure.value)

    with pytest.raises(MindmapArtifactError) as source_structure:
        MindmapAiTaskManager._enforce_result_policy(
            {'nodeCount': 103, 'treeDepth': 4}, {},
            max_nodes=100, max_depth=6, max_budget_usd=1.0,
            source_summary={'nodeCount': 2, 'treeDepth': 2},
            scoped_summary={'nodeCount': 103, 'treeDepth': 4},
            created_count=102,
        )
    assert source_structure.value.code == 'AI_BUDGET_EXCEEDED'
    assert '累计新增节点 102/100' in str(source_structure.value)
    assert '最终层级 4/6' in str(source_structure.value)

    with pytest.raises(MindmapArtifactError) as budget:
        MindmapAiTaskManager._enforce_result_policy(
            {'nodeCount': 10, 'treeDepth': 5}, {'totalCostUsd': 1.01},
            max_nodes=100, max_depth=8, max_budget_usd=1.0,
        )
    assert budget.value.code == 'AI_BUDGET_EXCEEDED'

    with pytest.raises(MindmapArtifactError) as invalid:
        MindmapAiTaskManager._enforce_result_policy(
            {'nodeCount': 10, 'treeDepth': 5}, {'totalCostUsd': 'not-a-number'},
            max_nodes=100, max_depth=8, max_budget_usd=1.0,
        )
    assert invalid.value.code == 'AI_BUDGET_EXCEEDED'


def test_admin_routes_have_independent_permission_and_never_return_credential_ref() -> None:
    schema = create_app().openapi()

    assert '/mindmap/ai/admin/connectors' in schema['paths']
    assert '/mindmap/ai/admin/connectors/{agent_key}/health-check' in schema['paths']
    assert '/mindmap/ai/admin/connectors/{agent_key}/conformance' in schema['paths']
    connector_schema = schema['components']['schemas']['MindmapAiConnectorModel']['properties']
    assert 'credentialConfigured' in connector_schema
    assert 'credentialRef' not in connector_schema
    assert {
        'modelAllowlist', 'maxBudgetUsd', 'timeoutSeconds', 'maxNodes',
        'maxDepth', 'maxConcurrentJobs', 'retentionDays',
    } <= set(connector_schema)
    assert "UserInterfaceAuthDependency('mindmap:ai:admin')" in inspect.getsource(
        mindmap_ai_controller,
    )


def test_admin_permission_is_published_as_a_navigable_connector_page() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    for migration in (
        'ruoyi-fastapi-backend/migrations/20260910_mindmap_ai_agent.sql',
        'ruoyi-fastapi-backend/migrations/20260910_mindmap_ai_agent_postgresql.sql',
    ):
        sql = (repository_root / migration).read_text(encoding='utf-8')
        assert "'ai-agents', 'mindmap/ai-agents'" in sql
        assert "'MindmapAiAgents'" in sql
        assert "'C', '0', '0', 'mindmap:ai:admin'" in sql
