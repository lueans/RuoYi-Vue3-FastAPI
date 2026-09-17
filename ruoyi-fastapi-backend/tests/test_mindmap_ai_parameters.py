"""Validation boundaries for user-controlled AI output parameters."""

import pytest
from pydantic import ValidationError

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
