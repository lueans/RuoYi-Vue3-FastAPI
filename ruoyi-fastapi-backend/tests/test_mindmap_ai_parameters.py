"""Validation boundaries for user-controlled AI output parameters."""

import pytest
from pydantic import ValidationError

from module_mindmap.ai.adapters.base import AgentRunContext, build_agent_generation_mode_clause
from module_mindmap.entity.vo.mindmap_ai_vo import (
    MindmapAiParametersModel,
    MindmapAiRetryParametersModel,
)


def test_output_language_is_canonicalized_for_create_and_retry() -> None:
    created = MindmapAiParametersModel(language='ZH-cn', layout='mindMap')
    retried = MindmapAiRetryParametersModel(language='ja-jp', layout='fishbone')

    assert created.language == 'zh-CN'
    assert retried.language == 'ja-JP'


@pytest.mark.parametrize('language', ['中文', 'x1', 'en_US', 'zh-CN-extra-more'])
def test_invalid_output_language_is_rejected(language: str) -> None:
    with pytest.raises(ValidationError, match='AI 输出语言代码无效'):
        MindmapAiParametersModel(language=language)


@pytest.mark.parametrize('layout', ['tree', 'mindmap', 'javascript:alert(1)'])
def test_unknown_target_layout_is_rejected_for_create_and_retry(layout: str) -> None:
    with pytest.raises(ValidationError, match='AI 目标布局无效'):
        MindmapAiParametersModel(layout=layout)
    with pytest.raises(ValidationError, match='AI 目标布局无效'):
        MindmapAiRetryParametersModel(layout=layout)


@pytest.mark.parametrize('mode', ['dfs_stream', 'bfs_stream', 'balanced', 'complete'])
def test_generation_mode_accepts_known_values_with_balanced_default(mode: str) -> None:
    assert MindmapAiParametersModel().generation_mode == 'balanced'
    assert MindmapAiParametersModel(generation_mode=mode).generation_mode == mode
    assert MindmapAiParametersModel(generation_mode=mode).model_dump(
        by_alias=True,
    )['generationMode'] == mode


@pytest.mark.parametrize('mode', ['dfs_stream', 'bfs_stream', 'balanced', 'complete'])
def test_generation_prompts_commit_real_draft_changes_before_final_result(mode: str) -> None:
    context = AgentRunContext(
        job_id='job', user_id=1, intent='create', prompt='生成脑图',
        parameters={'generationMode': mode}, source_document=None, tool_service=None,
    )
    clause = build_agent_generation_mode_clause(context)
    assert '立即调用 start_document' in clause
    assert '立即调用 add_nodes' in clause
    assert '不要先在内部生成完整脑图' in clause
    assert '每批不超过' in clause or '单批不超过' in clause


def test_edit_generation_prompt_uses_existing_draft_without_restarting_root() -> None:
    context = AgentRunContext(
        job_id='job', user_id=1, intent='edit', prompt='修改用例',
        parameters={'generationMode': 'balanced'}, source_document={'root': {}},
        tool_service=None,
    )
    clause = build_agent_generation_mode_clause(context)
    assert '立即读取已授权的现有草稿' in clause
    assert '立即调用 start_document' not in clause
    assert '已有节点的修改也应及时调用变更工具' in clause


@pytest.mark.parametrize('mode', ['fast', 'layered', 'dfs', ''])
def test_unknown_generation_mode_is_rejected_for_create_and_retry(mode: str) -> None:
    with pytest.raises(ValidationError):
        MindmapAiParametersModel(generation_mode=mode)
    with pytest.raises(ValidationError):
        MindmapAiRetryParametersModel(generation_mode=mode)


def test_retry_generation_mode_is_optional_override() -> None:
    # 与 retry_job 的合并序列化保持一致：显式 None 不会覆盖原任务参数。
    assert 'generationMode' not in MindmapAiRetryParametersModel().model_dump(
        by_alias=True,
        exclude_unset=True,
        exclude_none=True,
    )
    assert 'generationMode' not in MindmapAiRetryParametersModel(
        generation_mode=None,
    ).model_dump(by_alias=True, exclude_unset=True, exclude_none=True)
    assert MindmapAiRetryParametersModel(
        generation_mode='bfs_stream',
    ).model_dump(by_alias=True, exclude_unset=True, exclude_none=True) == {
        'generationMode': 'bfs_stream',
    }
