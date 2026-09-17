import json
import stat
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from module_mindmap.ai.document import build_smm_artifact
from module_mindmap.ai.evals import (
    REQUIRED_QUALITY_CATEGORIES,
    EvalCase,
    EvalDataset,
    EvalDatasetError,
    EvalExecution,
    load_eval_dataset,
    run_quality_evaluation,
    write_evaluation_report,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = BACKEND_ROOT / 'module_mindmap' / 'ai' / 'evals'
FIXED_TIME = datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc)
PRIVATE_REPORT_MODE = 0o600
SECOND_EXECUTION = 2


def _simple_document() -> dict:
    return {
        'root': {'data': {'uid': 'eval-root', 'text': 'Evaluation'}, 'children': []},
        'layout': 'logicalStructure',
        'theme': {'template': 'default', 'config': {}},
        'view': None,
        'documentData': {},
    }


def _passing_dataset() -> EvalDataset:
    dataset = load_eval_dataset()
    cases = []
    for case in dataset.cases:
        expectations = case.expectations
        if expectations.expected_outcome == 'artifact':
            expectations = replace(
                expectations,
                min_nodes=1,
                max_nodes=2_000,
                min_depth=1,
                max_depth=32,
                required_terms=(),
                forbidden_terms=(),
                max_duplicate_ratio=1.0,
            )
        cases.append(replace(case, expectations=expectations))
    return replace(dataset, cases=tuple(cases))


class _FixtureExecutor:
    def __init__(self, evidence_kind: str = 'synthetic') -> None:
        self.evidence_kind = evidence_kind

    async def execute(
        self,
        case: EvalCase,
        *,
        agent_key: str,
        model_ref: str | None,
    ) -> EvalExecution:
        del model_ref
        if case.expectations.expected_outcome == 'needs_input':
            return EvalExecution(
                status='needs_input',
                questions=[{
                    'questionId': 'scope',
                    'prompt': '希望脑图覆盖哪些业务范围？',
                }],
                adapter_version='1.2.3',
                sdk_version='4.5.6',
                runtime_version='python-3.12',
            )
        artifact, _summary = build_smm_artifact(
            _simple_document(),
            title='Evaluation',
            agent_key=agent_key,
            adapter_version='1.2.3',
            prompt_version='eval-1',
        )
        tool_calls = (
            ['start_document', 'validate_draft', 'complete_artifact']
            if case.source_type == 'none'
            else ['read_projection', 'update_nodes', 'validate_draft', 'complete_artifact']
        )
        return EvalExecution(
            status='completed',
            artifact=artifact,
            tool_calls=tool_calls,
            adapter_version='1.2.3',
            sdk_version='4.5.6',
            runtime_version='python-3.12',
        )


def test_checked_in_dataset_is_versioned_complete_and_schema_valid() -> None:
    dataset = load_eval_dataset()
    raw = json.loads((EVAL_ROOT / 'fixtures' / 'dataset-v1.json').read_text())
    schema = json.loads((EVAL_ROOT / 'dataset-schema-v1.json').read_text())

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(raw)
    assert dataset.dataset_version == '1.0.0'
    assert dataset.canonical_hash.startswith('sha256:')
    assert {case.category for case in dataset.cases} == REQUIRED_QUALITY_CATEGORIES
    assert {case.language for case in dataset.cases} >= {'zh-CN', 'en-US'}
    assert {case.expectations.expected_outcome for case in dataset.cases} == {
        'artifact',
        'needs_input',
    }


def test_dataset_loader_rejects_missing_frozen_category(tmp_path: Path) -> None:
    source = EVAL_ROOT / 'fixtures' / 'dataset-v1.json'
    raw = json.loads(source.read_text())
    raw['cases'] = raw['cases'][:-1]
    candidate = tmp_path / 'incomplete.json'
    candidate.write_text(json.dumps(raw), encoding='utf-8')

    with pytest.raises(EvalDatasetError, match='缺少冻结分类'):
        load_eval_dataset(candidate)


@pytest.mark.asyncio
async def test_no_executor_is_blocked_not_run_and_report_is_redacted(tmp_path: Path) -> None:
    dataset = load_eval_dataset()
    report = await run_quality_evaluation(
        dataset,
        agent_key='codex',
        model_ref='gpt-5.6-terra',
        generated_at=FIXED_TIME,
    )

    assert report['overallStatus'] == 'blocked'
    assert report['assessmentScope'] == 'agent_quality_dataset'
    assert report['providerExecution'] == 'not_run'
    assert report['evidenceKind'] == 'not_run'
    assert report['releaseEligible'] is False
    assert report['summary'] == {
        'selected': len(dataset.cases),
        'passed': 0,
        'failed': 0,
        'blocked': len(dataset.cases),
    }
    assert all(item['score'] is None for item in report['results'])
    serialized = json.dumps(report, ensure_ascii=False)
    assert '帮我做一个脑图' not in serialized
    assert 'sourceDocument' not in serialized
    assert '/Users/' not in serialized

    output = write_evaluation_report(report, tmp_path / 'nested' / 'report.json')
    persisted = json.loads(output.read_text())
    assert persisted == report
    assert stat.S_IMODE(output.stat().st_mode) == PRIVATE_REPORT_MODE
    assert not output.with_suffix('.json.tmp').exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('evidence_kind', ['synthetic', 'replay'])
async def test_non_provider_evidence_can_never_be_release_eligible(evidence_kind: str) -> None:
    report = await run_quality_evaluation(
        _passing_dataset(),
        agent_key='codex',
        model_ref='gpt-5.6-terra',
        executor=_FixtureExecutor(evidence_kind),
        generated_at=FIXED_TIME,
    )

    assert report['overallStatus'] == 'passed'
    assert report['coverageComplete'] is True
    assert report['providerExecution'] == 'completed'
    assert report['releaseEligible'] is False


@pytest.mark.asyncio
async def test_real_provider_full_run_is_the_only_release_eligible_shape() -> None:
    dataset = _passing_dataset()
    first = await run_quality_evaluation(
        dataset,
        agent_key='claude',
        model_ref='anthropic/claude-sonnet-4-5',
        executor=_FixtureExecutor('real_provider'),
        generated_at=FIXED_TIME,
    )
    second = await run_quality_evaluation(
        dataset,
        agent_key='claude',
        model_ref='anthropic/claude-sonnet-4-5',
        executor=_FixtureExecutor('real_provider'),
        generated_at=FIXED_TIME,
    )

    assert first['overallStatus'] == 'passed'
    assert first['providerExecution'] == 'completed'
    assert first['coverageComplete'] is True
    assert first['releaseEligible'] is True
    assert first['runConfigurationHash'] == second['runConfigurationHash']
    assert first['generatedAt'] == '2026-09-14T08:00:00Z'
    report_schema = json.loads((EVAL_ROOT / 'report-schema-v1.json').read_text())
    Draft202012Validator.check_schema(report_schema)
    Draft202012Validator(report_schema).validate(first)


@pytest.mark.asyncio
async def test_selected_fixture_is_not_complete_release_coverage() -> None:
    report = await run_quality_evaluation(
        _passing_dataset(),
        agent_key='native_mindmap',
        model_ref='native/model-test',
        fixture_ids={'project_plan_zh'},
        executor=_FixtureExecutor('real_provider'),
        generated_at=FIXED_TIME,
    )

    assert report['overallStatus'] == 'passed'
    assert report['coverageComplete'] is False
    assert report['releaseEligible'] is False
    assert report['summary']['selected'] == 1


@pytest.mark.asyncio
async def test_needs_input_with_mutation_side_effect_fails_hard_gate() -> None:
    class UnsafeClarificationExecutor:
        evidence_kind = 'real_provider'

        async def execute(
            self,
            case: EvalCase,
            *,
            agent_key: str,
            model_ref: str | None,
        ) -> EvalExecution:
            del case, agent_key, model_ref
            return EvalExecution(
                status='needs_input',
                tool_calls=['start_document'],
                questions=[{
                    'questionId': 'scope',
                    'prompt': '希望脑图覆盖哪些业务范围？',
                }],
                adapter_version='1.2.3',
                sdk_version='4.5.6',
                runtime_version='python-3.12',
            )

    report = await run_quality_evaluation(
        load_eval_dataset(),
        agent_key='native_mindmap',
        model_ref='native/model-test',
        fixture_ids={'ambiguous_input_zh'},
        executor=UnsafeClarificationExecutor(),
        generated_at=FIXED_TIME,
    )

    assert report['overallStatus'] == 'failed'
    assert report['results'][0]['hardGateFailures'] == [
        'needs_input_has_mutation_side_effect',
        'unauthorized_tool_call',
    ]


@pytest.mark.asyncio
async def test_needs_input_without_valid_questions_fails_hard_gate() -> None:
    class MissingQuestionsExecutor:
        evidence_kind = 'synthetic'

        async def execute(
            self,
            case: EvalCase,
            *,
            agent_key: str,
            model_ref: str | None,
        ) -> EvalExecution:
            del case, agent_key, model_ref
            return EvalExecution(status='needs_input')

    report = await run_quality_evaluation(
        load_eval_dataset(),
        agent_key='native_mindmap',
        fixture_ids={'ambiguous_input_zh'},
        executor=MissingQuestionsExecutor(),
        generated_at=FIXED_TIME,
    )

    assert report['overallStatus'] == 'failed'
    assert report['results'][0]['hardGateFailures'] == [
        'needs_input_questions_invalid',
    ]


@pytest.mark.asyncio
async def test_real_provider_evidence_requires_consistent_versions_and_model() -> None:
    class MixedVersionExecutor(_FixtureExecutor):
        def __init__(self) -> None:
            super().__init__('real_provider')
            self.calls = 0

        async def execute(
            self,
            case: EvalCase,
            *,
            agent_key: str,
            model_ref: str | None,
        ) -> EvalExecution:
            execution = await super().execute(
                case,
                agent_key=agent_key,
                model_ref=model_ref,
            )
            self.calls += 1
            if self.calls == SECOND_EXECUTION:
                execution.sdk_version = '4.5.7'
            return execution

    mixed = await run_quality_evaluation(
        _passing_dataset(),
        agent_key='codex',
        model_ref='gpt-5.6-terra',
        executor=MixedVersionExecutor(),
        generated_at=FIXED_TIME,
    )
    missing_model = await run_quality_evaluation(
        _passing_dataset(),
        agent_key='codex',
        executor=_FixtureExecutor('real_provider'),
        generated_at=FIXED_TIME,
    )

    assert mixed['releaseEligible'] is False
    assert mixed['overallStatus'] == 'failed'
    assert any(
        'provider_version_evidence_inconsistent' in item['hardGateFailures']
        for item in mixed['results']
    )
    assert missing_model['releaseEligible'] is False
    assert missing_model['overallStatus'] == 'failed'
    assert all(
        'provider_model_evidence_missing' in item['hardGateFailures']
        for item in missing_model['results']
    )


@pytest.mark.asyncio
async def test_runner_rejects_sensitive_model_ref_before_execution() -> None:
    with pytest.raises(ValueError, match='敏感信息'):
        await run_quality_evaluation(
            load_eval_dataset(),
            agent_key='codex',
            model_ref='sk-live-not-a-model',
            executor=_FixtureExecutor('real_provider'),
        )


@pytest.mark.asyncio
async def test_executor_error_text_cannot_leak_into_report() -> None:
    class BlockedExecutor:
        evidence_kind = 'real_provider'

        async def execute(
            self,
            case: EvalCase,
            *,
            agent_key: str,
            model_ref: str | None,
        ) -> EvalExecution:
            del case, agent_key, model_ref
            return EvalExecution(
                status='blocked',
                error_code='token=do-not-leak /Users/private',
            )

    report = await run_quality_evaluation(
        load_eval_dataset(),
        agent_key='codex',
        fixture_ids={'project_plan_zh'},
        executor=BlockedExecutor(),
        generated_at=FIXED_TIME,
    )

    serialized = json.dumps(report)
    assert 'do-not-leak' not in serialized
    assert '/Users/private' not in serialized
    assert report['providerExecution'] == 'partial'
    assert report['results'][0]['hardGateFailures'] == ['PROVIDER_EXECUTION_BLOCKED']


@pytest.mark.asyncio
async def test_executor_exception_cannot_be_reported_as_completed_provider_execution() -> None:
    class CrashingExecutor:
        evidence_kind = 'real_provider'

        async def execute(
            self,
            case: EvalCase,
            *,
            agent_key: str,
            model_ref: str | None,
        ) -> EvalExecution:
            del case, agent_key, model_ref
            raise RuntimeError('provider process terminated')

    report = await run_quality_evaluation(
        load_eval_dataset(),
        agent_key='codex',
        model_ref='gpt-5.6-terra',
        fixture_ids={'project_plan_zh'},
        executor=CrashingExecutor(),
        generated_at=FIXED_TIME,
    )

    assert report['providerExecution'] == 'partial'
    assert report['overallStatus'] == 'failed'
    assert report['releaseEligible'] is False
