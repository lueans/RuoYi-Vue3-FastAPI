"""Reproducible evaluator that never invokes a provider unless one is injected."""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

import rfc8785

from module_mindmap.ai.adapters.base import normalize_agent_input_questions
from module_mindmap.ai.document import MindmapArtifactError, validate_smm_artifact
from module_mindmap.ai.evals.dataset import (
    REQUIRED_QUALITY_CATEGORIES,
    EvalCase,
    EvalDataset,
)

REPORT_SCHEMA = 'ruoyi-mindmap-agent-quality-report/v1'
RUNNER_VERSION = '1.0.0'
EVIDENCE_KINDS = frozenset({'real_provider', 'replay', 'synthetic'})
COMPLETION_TOOL = 'complete_artifact'
MUTATION_TOOLS = frozenset({
    'start_document',
    'add_nodes',
    'update_nodes',
    'move_nodes',
    'remove_nodes',
    'set_document_meta',
    'complete_artifact',
})
SAFE_IDENTIFIER_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$')
SENSITIVE_IDENTIFIER_PATTERN = re.compile(
    r'(?i)(?:sk-|api[_-]?key|token|secret|password|bearer|-----begin|/users/|\\users\\|://|\.\.)'
)
SAFE_ERROR_CODE_PATTERN = re.compile(r'^[A-Z0-9][A-Z0-9_]{1,63}$')
SAFE_TOOL_NAME_PATTERN = re.compile(r'^[a-z][a-z0-9_]{0,63}$')
MAX_QUALITY_SCORE = 100.0
MAX_EVAL_TOOL_CALLS = 1_000


@dataclass(slots=True)
class EvalExecution:
    status: Literal['completed', 'needs_input', 'blocked', 'failed']
    artifact: dict[str, Any] | None = None
    tool_calls: list[str] = field(default_factory=list)
    questions: list[dict[str, str]] = field(default_factory=list)
    error_code: str | None = None
    adapter_version: str | None = None
    sdk_version: str | None = None
    runtime_version: str | None = None


class EvalExecutor(Protocol):
    """A deployment plugin may implement this without changing product code."""

    evidence_kind: Literal['real_provider', 'replay', 'synthetic']

    async def execute(
        self,
        case: EvalCase,
        *,
        agent_key: str,
        model_ref: str | None,
    ) -> EvalExecution: ...


def _document_texts(document: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    stack = [document.get('root')]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        data = node.get('data')
        if isinstance(data, dict):
            for field_name in ('text', 'note'):
                value = data.get(field_name)
                if isinstance(value, str) and value.strip():
                    texts.append(value.strip())
        children = node.get('children')
        if isinstance(children, list):
            stack.extend(reversed(children))
    return texts


def _duplicate_ratio(texts: list[str]) -> float:
    normalized = [' '.join(text.casefold().split()) for text in texts if text.strip()]
    if not normalized:
        return 0.0
    duplicates = sum(count - 1 for count in Counter(normalized).values() if count > 1)
    return duplicates / len(normalized)


def _safe_version(value: Any) -> str | None:
    if not isinstance(value, str) or not SAFE_IDENTIFIER_PATTERN.fullmatch(value):
        return None
    if SENSITIVE_IDENTIFIER_PATTERN.search(value):
        return None
    return value


def _safe_error_code(value: Any, fallback: str) -> str:
    if isinstance(value, str) and SAFE_ERROR_CODE_PATTERN.fullmatch(value):
        return value
    return fallback


def _blocked_case(case: EvalCase, reason: str) -> dict[str, Any]:
    return {
        'caseId': case.case_id,
        'category': case.category,
        'status': 'blocked',
        'score': None,
        'hardGateFailures': [reason],
        'qualityFailures': [],
        'metrics': {},
    }


def _failed_case(case: EvalCase, reason: str) -> dict[str, Any]:
    return {
        'caseId': case.case_id,
        'category': case.category,
        'status': 'failed',
        'score': 0.0,
        'hardGateFailures': [reason],
        'qualityFailures': [],
        'metrics': {},
    }


def _validated_tool_calls(value: Any) -> list[str] | None:
    if (
        not isinstance(value, list)
        or len(value) > MAX_EVAL_TOOL_CALLS
        or any(
            not isinstance(item, str) or not SAFE_TOOL_NAME_PATTERN.fullmatch(item)
            for item in value
        )
    ):
        return None
    return list(value)


def _add_hard_failure(result: dict[str, Any], failure: str) -> None:
    failures = result.setdefault('hardGateFailures', [])
    if failure not in failures:
        failures.append(failure)
        failures.sort()
    result['status'] = 'failed'
    result['score'] = 0.0


def _score_execution(  # noqa: PLR0912
    case: EvalCase,
    execution: EvalExecution,
    *,
    agent_key: str,
    quality_threshold: float,
) -> dict[str, Any]:
    hard_failures: list[str] = []
    quality_failures: list[str] = []
    if case.expectations.expected_outcome != 'artifact':
        return _failed_case(case, 'expected_needs_input')
    if execution.artifact is None:
        return _failed_case(case, 'artifact_missing')
    try:
        artifact, summary = validate_smm_artifact(execution.artifact)
    except MindmapArtifactError:
        return _failed_case(case, 'artifact_validation_failed')
    generator = artifact.get('manifest', {}).get('generator', {})
    if generator.get('agentKey') != agent_key:
        hard_failures.append('agent_provenance_mismatch')
    tool_calls = _validated_tool_calls(execution.tool_calls)
    if tool_calls is None:
        return _failed_case(case, 'executor_tool_trace_invalid')
    unauthorized = sorted(set(tool_calls) - set(case.expectations.allowed_tools))
    if unauthorized:
        hard_failures.append('unauthorized_tool_call')
    if not tool_calls or tool_calls[-1] != COMPLETION_TOOL or tool_calls.count(COMPLETION_TOOL) != 1:
        hard_failures.append('complete_artifact_not_last_exactly_once')

    texts = _document_texts(artifact['document'])
    searchable = '\n'.join(texts).casefold()
    required_hits = sum(term.casefold() in searchable for term in case.expectations.required_terms)
    coverage = (
        required_hits / len(case.expectations.required_terms)
        if case.expectations.required_terms
        else 1.0
    )
    forbidden_hits = [term for term in case.expectations.forbidden_terms if term.casefold() in searchable]
    if forbidden_hits:
        hard_failures.append('forbidden_content_present')

    node_count = int(summary['nodeCount'])
    tree_depth = int(summary['treeDepth'])
    node_range_ok = case.expectations.min_nodes <= node_count <= case.expectations.max_nodes
    depth_range_ok = case.expectations.min_depth <= tree_depth <= case.expectations.max_depth
    duplicate_ratio = _duplicate_ratio(texts)
    duplicate_ok = duplicate_ratio <= case.expectations.max_duplicate_ratio

    if not node_range_ok:
        quality_failures.append('node_count_outside_fixture_range')
    if not depth_range_ok:
        quality_failures.append('tree_depth_outside_fixture_range')
    if coverage < 1:
        quality_failures.append('required_concept_coverage_incomplete')
    if not duplicate_ok:
        quality_failures.append('duplicate_text_ratio_exceeded')

    score = round(
        40 * coverage
        + 20 * float(node_range_ok)
        + 20 * float(depth_range_ok)
        + 20 * float(duplicate_ok),
        2,
    )
    if not math.isfinite(score) or score < quality_threshold:
        quality_failures.append('quality_score_below_threshold')
    return {
        'caseId': case.case_id,
        'category': case.category,
        'status': 'passed' if not hard_failures and not quality_failures else 'failed',
        'score': score,
        'hardGateFailures': sorted(set(hard_failures)),
        'qualityFailures': sorted(set(quality_failures)),
        'metrics': {
            'nodeCount': node_count,
            'treeDepth': tree_depth,
            'requiredConceptCoverage': round(coverage, 4),
            'duplicateTextRatio': round(duplicate_ratio, 4),
        },
    }


def _score_needs_input(case: EvalCase, execution: EvalExecution) -> dict[str, Any]:
    hard_failures: list[str] = []
    if case.expectations.expected_outcome != 'needs_input':
        hard_failures.append('unexpected_needs_input')
    if execution.artifact is not None:
        hard_failures.append('needs_input_must_not_include_artifact')
    tool_calls = _validated_tool_calls(execution.tool_calls)
    if tool_calls is None:
        return _failed_case(case, 'executor_tool_trace_invalid')
    try:
        questions = normalize_agent_input_questions({
            'completionState': 'needs_input',
            'questions': execution.questions,
        })
    except MindmapArtifactError:
        questions = ()
        hard_failures.append('needs_input_questions_invalid')
    if set(tool_calls) & MUTATION_TOOLS:
        hard_failures.append('needs_input_has_mutation_side_effect')
    unauthorized = sorted(set(tool_calls) - set(case.expectations.allowed_tools))
    if unauthorized:
        hard_failures.append('unauthorized_tool_call')
    return {
        'caseId': case.case_id,
        'category': case.category,
        'status': 'passed' if not hard_failures else 'failed',
        'score': 100.0 if not hard_failures else 0.0,
        'hardGateFailures': sorted(set(hard_failures)),
        'qualityFailures': [],
        'metrics': {
            'clarificationRequested': True,
            'questionCount': len(questions),
        },
    }


def _selected_cases(dataset: EvalDataset, fixture_ids: set[str] | None) -> tuple[EvalCase, ...]:
    if not fixture_ids:
        return dataset.cases
    known = {case.case_id for case in dataset.cases}
    unknown = sorted(fixture_ids - known)
    if unknown:
        raise ValueError(f'未知评测用例: {", ".join(unknown)}')
    return tuple(case for case in dataset.cases if case.case_id in fixture_ids)


async def run_quality_evaluation(  # noqa: PLR0912, PLR0915
    dataset: EvalDataset,
    *,
    agent_key: str,
    model_ref: str | None = None,
    fixture_ids: set[str] | None = None,
    quality_threshold: float = 80.0,
    executor: EvalExecutor | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Run selected fixtures and return a redacted, immutable report payload."""
    if not re.fullmatch(r'[a-z][a-z0-9_]{1,63}', agent_key):
        raise ValueError('agent_key 无效')
    if model_ref is not None and (
        not isinstance(model_ref, str)
        or not SAFE_IDENTIFIER_PATTERN.fullmatch(model_ref)
        or SENSITIVE_IDENTIFIER_PATTERN.search(model_ref)
    ):
        raise ValueError('model_ref 无效或可能包含敏感信息')
    if (
        not isinstance(quality_threshold, (int, float))
        or not 0 <= quality_threshold <= MAX_QUALITY_SCORE
    ):
        raise ValueError('quality_threshold 必须在 0 到 100 之间')
    selected = _selected_cases(dataset, fixture_ids)
    evidence_kind = getattr(executor, 'evidence_kind', 'not_run') if executor else 'not_run'
    if evidence_kind not in EVIDENCE_KINDS | {'not_run'}:
        raise ValueError('评测执行器 evidence_kind 无效')
    results: list[dict[str, Any]] = []
    versions: dict[str, str | None] = {
        'adapterVersion': None,
        'sdkVersion': None,
        'runtimeVersion': None,
    }
    observed_versions: dict[str, set[str]] = {
        'adapterVersion': set(),
        'sdkVersion': set(),
        'runtimeVersion': set(),
    }
    provider_case_executions = 0
    for case in selected:
        if executor is None:
            results.append(_blocked_case(case, 'provider_executor_not_configured'))
            continue
        try:
            execution = executor.execute(case, agent_key=agent_key, model_ref=model_ref)
            if inspect.isawaitable(execution):
                execution = await execution
        except Exception:
            results.append(_failed_case(case, 'executor_failed'))
            continue
        if not isinstance(execution, EvalExecution):
            results.append(_failed_case(case, 'executor_contract_invalid'))
            continue
        if execution.status != 'blocked':
            provider_case_executions += 1
        execution_versions: dict[str, str | None] = {}
        for report_key, attr in (
            ('adapterVersion', 'adapter_version'),
            ('sdkVersion', 'sdk_version'),
            ('runtimeVersion', 'runtime_version'),
        ):
            safe_value = _safe_version(getattr(execution, attr))
            execution_versions[report_key] = safe_value
            versions[report_key] = versions[report_key] or safe_value
            if safe_value is not None:
                observed_versions[report_key].add(safe_value)
        if execution.status == 'blocked':
            result = _blocked_case(
                case,
                _safe_error_code(execution.error_code, 'PROVIDER_EXECUTION_BLOCKED'),
            )
        elif execution.status == 'needs_input':
            result = _score_needs_input(case, execution)
        elif execution.status != 'completed':
            result = _failed_case(
                case,
                _safe_error_code(execution.error_code, 'PROVIDER_EXECUTION_FAILED'),
            )
        else:
            result = _score_execution(
                case,
                execution,
                agent_key=agent_key,
                quality_threshold=float(quality_threshold),
            )
        if (
            evidence_kind == 'real_provider'
            and result['status'] != 'blocked'
            and any(value is None for value in execution_versions.values())
        ):
            _add_hard_failure(result, 'provider_version_evidence_missing_or_invalid')
        results.append(result)

    if evidence_kind == 'real_provider' and any(
        len(values) > 1 for values in observed_versions.values()
    ):
        for result in results:
            if result['status'] != 'blocked':
                _add_hard_failure(result, 'provider_version_evidence_inconsistent')
    if evidence_kind == 'real_provider' and model_ref is None:
        for result in results:
            if result['status'] != 'blocked':
                _add_hard_failure(result, 'provider_model_evidence_missing')

    selected_categories = {case.category for case in selected}
    coverage_complete = selected_categories == REQUIRED_QUALITY_CATEGORIES
    provider_execution = (
        'not_run'
        if executor is None
        else ('completed' if provider_case_executions == len(selected) else 'partial')
    )
    statuses = {item['status'] for item in results}
    overall_status = 'blocked' if 'blocked' in statuses else ('failed' if 'failed' in statuses else 'passed')
    release_eligible = (
        evidence_kind == 'real_provider'
        and provider_execution == 'completed'
        and coverage_complete
        and overall_status == 'passed'
        and model_ref is not None
        and all(len(values) == 1 for values in observed_versions.values())
    )
    report_time = generated_at or datetime.now(timezone.utc)
    if report_time.tzinfo is None or report_time.utcoffset() is None:
        raise ValueError('generated_at 必须包含时区')
    run_configuration = {
        'runnerVersion': RUNNER_VERSION,
        'datasetHash': dataset.canonical_hash,
        'agentKey': agent_key,
        'modelRef': model_ref,
        'fixtureIds': [case.case_id for case in selected],
        'qualityThreshold': float(quality_threshold),
        'evidenceKind': evidence_kind,
    }
    return {
        'schema': REPORT_SCHEMA,
        # This is one release-gate input, never a product or Adapter release
        # decision. Deterministic conformance and security/fault-injection
        # evidence are tracked separately.
        'assessmentScope': 'agent_quality_dataset',
        'runnerVersion': RUNNER_VERSION,
        'generatedAt': report_time.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'runConfigurationHash': 'sha256:' + hashlib.sha256(
            rfc8785.dumps(run_configuration)
        ).hexdigest(),
        'datasetVersion': dataset.dataset_version,
        'datasetHash': dataset.canonical_hash,
        'agentKey': agent_key,
        'modelRef': model_ref,
        **versions,
        'evidenceKind': evidence_kind,
        'providerExecution': provider_execution,
        'coverageComplete': coverage_complete,
        'qualityThreshold': float(quality_threshold),
        'overallStatus': overall_status,
        'releaseEligible': release_eligible,
        'summary': {
            'selected': len(results),
            'passed': sum(item['status'] == 'passed' for item in results),
            'failed': sum(item['status'] == 'failed' for item in results),
            'blocked': sum(item['status'] == 'blocked' for item in results),
        },
        'results': results,
    }


def write_evaluation_report(report: dict[str, Any], path: str | Path) -> Path:
    """Atomically persist the redacted report; never persist artifacts or prompts."""
    output_path = Path(path)
    output_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    encoded = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2).encode('utf-8') + b'\n'
    temporary = output_path.with_suffix(output_path.suffix + '.tmp')
    temporary.write_bytes(encoded)
    temporary.chmod(0o600)
    temporary.replace(output_path)
    return output_path
