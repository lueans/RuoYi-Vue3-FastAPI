"""Strict loader for the versioned PRD 22.2 quality fixture set."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import rfc8785

DATASET_SCHEMA = 'ruoyi-mindmap-agent-quality-dataset/v1'
CASE_ID_PATTERN = re.compile(r'^[a-z][a-z0-9_-]{2,63}$')
AGENT_INTENTS = frozenset({
    'create',
    'expand',
    'rewrite_branch',
    'condense_branch',
    'reorganize',
})
SOURCE_TYPES = frozenset({'none', 'local_snapshot'})
REQUIRED_QUALITY_CATEGORIES = frozenset({
    'knowledge_graph',
    'project_plan',
    'requirements_breakdown',
    'long_text_zh',
    'long_text_en',
    'branch_rewrite',
    'structure_condense',
    'prompt_injection',
    'ambiguous_input',
})
DEFAULT_ALLOWED_TOOLS = (
    'read_projection',
    'start_document',
    'add_nodes',
    'update_nodes',
    'move_nodes',
    'remove_nodes',
    'set_document_meta',
    'validate_draft',
    'complete_artifact',
)


class EvalDatasetError(ValueError):
    """The checked-in evaluation dataset does not satisfy its frozen schema."""


@dataclass(frozen=True, slots=True)
class EvalExpectations:
    expected_outcome: Literal['artifact', 'needs_input']
    min_nodes: int
    max_nodes: int
    min_depth: int
    max_depth: int
    required_terms: tuple[str, ...]
    forbidden_terms: tuple[str, ...]
    max_duplicate_ratio: float
    allowed_tools: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvalCase:
    case_id: str
    category: str
    language: str
    intent: str
    prompt: str
    source_type: str
    source_document: dict[str, Any] | None
    scope: dict[str, Any] | None
    parameters: dict[str, Any]
    expectations: EvalExpectations


@dataclass(frozen=True, slots=True)
class EvalDataset:
    schema: str
    dataset_version: str
    cases: tuple[EvalCase, ...]
    canonical_hash: str


def _expect_record(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvalDatasetError(f'{field} 必须是对象')
    return value


def _expect_text(value: Any, field: str, *, maximum: int = 20_000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise EvalDatasetError(f'{field} 必须是非空且长度不超过 {maximum} 的文本')
    return value


def _text_tuple(value: Any, field: str, *, maximum_items: int = 30) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > maximum_items:
        raise EvalDatasetError(f'{field} 必须是有界文本数组')
    output = tuple(_expect_text(item, field, maximum=200) for item in value)
    if len(set(output)) != len(output):
        raise EvalDatasetError(f'{field} 不能包含重复项')
    return output


def _bounded_int(value: Any, field: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise EvalDatasetError(f'{field} 必须在 {minimum} 到 {maximum} 之间')
    return value


def _parse_expectations(value: Any, case_id: str) -> EvalExpectations:
    record = _expect_record(value, f'{case_id}.expected')
    required = {
        'expectedOutcome', 'minNodes', 'maxNodes', 'minDepth', 'maxDepth', 'requiredTerms',
        'forbiddenTerms', 'maxDuplicateRatio',
    }
    if set(record) - (required | {'allowedTools'}) or not required.issubset(record):
        raise EvalDatasetError(f'{case_id}.expected 字段不符合 v1 合同')
    min_nodes = _bounded_int(record['minNodes'], f'{case_id}.minNodes', 1, 2_000)
    max_nodes = _bounded_int(record['maxNodes'], f'{case_id}.maxNodes', 1, 2_000)
    min_depth = _bounded_int(record['minDepth'], f'{case_id}.minDepth', 1, 32)
    max_depth = _bounded_int(record['maxDepth'], f'{case_id}.maxDepth', 1, 32)
    duplicate_ratio = record['maxDuplicateRatio']
    expected_outcome = record['expectedOutcome']
    if min_nodes > max_nodes or min_depth > max_depth:
        raise EvalDatasetError(f'{case_id}.expected 最小值不能大于最大值')
    if (
        not isinstance(duplicate_ratio, (int, float))
        or isinstance(duplicate_ratio, bool)
        or not 0 <= float(duplicate_ratio) <= 1
    ):
        raise EvalDatasetError(f'{case_id}.maxDuplicateRatio 必须在 0 到 1 之间')
    if expected_outcome not in {'artifact', 'needs_input'}:
        raise EvalDatasetError(f'{case_id}.expectedOutcome 无效')
    allowed_tools = _text_tuple(
        record.get('allowedTools', list(DEFAULT_ALLOWED_TOOLS)),
        f'{case_id}.allowedTools',
    )
    return EvalExpectations(
        expected_outcome=expected_outcome,
        min_nodes=min_nodes,
        max_nodes=max_nodes,
        min_depth=min_depth,
        max_depth=max_depth,
        required_terms=_text_tuple(record['requiredTerms'], f'{case_id}.requiredTerms'),
        forbidden_terms=_text_tuple(record['forbiddenTerms'], f'{case_id}.forbiddenTerms'),
        max_duplicate_ratio=float(duplicate_ratio),
        allowed_tools=allowed_tools,
    )


def _parse_case(value: Any) -> EvalCase:
    record = _expect_record(value, 'case')
    required = {
        'caseId', 'category', 'language', 'intent', 'prompt', 'sourceType',
        'parameters', 'expected',
    }
    if set(record) - (required | {'sourceDocument', 'scope'}) or not required.issubset(record):
        raise EvalDatasetError('评测用例字段不符合 v1 合同')
    case_id = _expect_text(record['caseId'], 'caseId', maximum=64)
    category = _expect_text(record['category'], f'{case_id}.category', maximum=64)
    intent = _expect_text(record['intent'], f'{case_id}.intent', maximum=32)
    source_type = _expect_text(record['sourceType'], f'{case_id}.sourceType', maximum=32)
    if not CASE_ID_PATTERN.fullmatch(case_id):
        raise EvalDatasetError(f'用例 ID 无效: {case_id}')
    if category not in REQUIRED_QUALITY_CATEGORIES:
        raise EvalDatasetError(f'{case_id}.category 不在冻结分类中')
    if intent not in AGENT_INTENTS or source_type not in SOURCE_TYPES:
        raise EvalDatasetError(f'{case_id} 的 intent 或 sourceType 无效')
    source_document = record.get('sourceDocument')
    if (source_type == 'none') != (source_document is None):
        raise EvalDatasetError(f'{case_id} 的 sourceType 与 sourceDocument 不一致')
    if source_document is not None:
        source_document = _expect_record(source_document, f'{case_id}.sourceDocument')
    scope = record.get('scope')
    if scope is not None:
        scope = _expect_record(scope, f'{case_id}.scope')
    parameters = _expect_record(record['parameters'], f'{case_id}.parameters')
    return EvalCase(
        case_id=case_id,
        category=category,
        language=_expect_text(record['language'], f'{case_id}.language', maximum=16),
        intent=intent,
        prompt=_expect_text(record['prompt'], f'{case_id}.prompt'),
        source_type=source_type,
        source_document=source_document,
        scope=scope,
        parameters=parameters,
        expectations=_parse_expectations(record['expected'], case_id),
    )


def load_eval_dataset(path: str | Path | None = None) -> EvalDataset:
    dataset_path = Path(path) if path is not None else Path(__file__).with_name('fixtures').joinpath('dataset-v1.json')
    try:
        raw_bytes = dataset_path.read_bytes()
        raw = json.loads(raw_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvalDatasetError('无法读取 AI 脑图质量评测数据集') from exc
    record = _expect_record(raw, 'dataset')
    if set(record) != {'schema', 'datasetVersion', 'cases'}:
        raise EvalDatasetError('评测数据集顶层字段不符合 v1 合同')
    if record.get('schema') != DATASET_SCHEMA:
        raise EvalDatasetError('评测数据集 schema 不受支持')
    dataset_version = _expect_text(record.get('datasetVersion'), 'datasetVersion', maximum=32)
    if not re.fullmatch(r'\d+\.\d+\.\d+', dataset_version):
        raise EvalDatasetError('评测数据集版本必须使用语义版本')
    raw_cases = record.get('cases')
    if not isinstance(raw_cases, list) or not raw_cases:
        raise EvalDatasetError('评测数据集至少包含一个用例')
    cases = tuple(_parse_case(item) for item in raw_cases)
    case_ids = [case.case_id for case in cases]
    if len(set(case_ids)) != len(case_ids):
        raise EvalDatasetError('评测用例 ID 必须唯一')
    categories = {case.category for case in cases}
    missing = sorted(REQUIRED_QUALITY_CATEGORIES - categories)
    if missing:
        raise EvalDatasetError(f'评测数据集缺少冻结分类: {", ".join(missing)}')
    canonical_hash = 'sha256:' + hashlib.sha256(rfc8785.dumps(record)).hexdigest()
    return EvalDataset(
        schema=DATASET_SCHEMA,
        dataset_version=dataset_version,
        cases=cases,
        canonical_hash=canonical_hash,
    )
