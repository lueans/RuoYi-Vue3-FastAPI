"""脑图标签 Pydantic 模型"""
import math
import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH = 200
MINDMAP_TAG_SEARCH_KEYWORD_PATTERN = r'^[^\x00-\x1f\x7f]*$'
MAX_MINDMAP_TAG_KEY_LENGTH = 100
MAX_MINDMAP_TAG_NAME_LENGTH = 200
MAX_MINDMAP_TAG_DESCRIPTION_LENGTH = 500
MAX_MINDMAP_TAG_CATEGORY_NAME_LENGTH = 100
MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER = 100_000
MAX_MINDMAP_TAG_CATEGORY_BATCH_SIZE = 500
MAX_MINDMAP_TAG_BATCH_SIZE = 100
MAX_MINDMAP_TAG_BATCH_IDS_TEXT_LENGTH = 4096
MAX_MINDMAP_TAG_ID = 9_223_372_036_854_775_807
MINDMAP_TAG_BATCH_IDS_PATTERN = r'^[ ]*[1-9][0-9]*(?:[ ]*,[ ]*[1-9][0-9]*)*[ ]*$'
MIN_CONTROL_CHARACTER_CODEPOINT = 32
DELETE_CONTROL_CHARACTER_CODEPOINT = 127
ALLOWED_DESCRIPTION_CONTROL_CHARACTERS = frozenset({'\t', '\n', '\r'})
MINDMAP_TAG_STYLE_NUMBER_BOUNDS = {
    'fontSize': (10, 24),
    'radius': (0, 20),
    'paddingX': (0, 30),
}
MINDMAP_TAG_STYLE_COLOR_KEYS = frozenset({'fill', 'color'})
MINDMAP_TAG_STYLE_PLACEMENTS = frozenset({'left', 'right', 'top', 'bottom'})
MINDMAP_TAG_STYLE_ALIGNS = frozenset({'left', 'right', 'top', 'bottom', 'center'})
MINDMAP_TAG_MARKER_ICON_PATTERN = re.compile(
    r'^(?:priority_(?:10|[1-9])|progress_[1-8]|'
    r'expression_(?:20|1[0-9]|[1-9])|sign_(?:2[0-3]|1[0-9]|[1-9]))$'
)
MINDMAP_TAG_STYLE_KEYS = frozenset({
    *MINDMAP_TAG_STYLE_COLOR_KEYS,
    *MINDMAP_TAG_STYLE_NUMBER_BOUNDS,
    'placement',
    'align',
    'iconKey',
})
MINDMAP_TAG_COLOR_PATTERN = re.compile(r'^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$')
MINDMAP_TAG_RGB_COLOR_PATTERN = re.compile(
    r'^rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)$',
    re.IGNORECASE,
)
MINDMAP_TAG_RGBA_COLOR_PATTERN = re.compile(
    r'^rgba\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})'
    r'\s*,\s*(0(?:\.\d+)?|1(?:\.0+)?|\.\d+)\s*\)$',
    re.IGNORECASE,
)
MAX_MINDMAP_TAG_COLOR_CHANNEL = 255
MINDMAP_TAG_RGBA_MATCH_GROUP_COUNT = 4


def _contains_control_character(value: str, *, allow_multiline: bool = False) -> bool:
    return any(
        (
            ord(char) < MIN_CONTROL_CHARACTER_CODEPOINT
            and (not allow_multiline or char not in ALLOWED_DESCRIPTION_CONTROL_CHARACTERS)
        )
        or ord(char) == DELETE_CONTROL_CHARACTER_CODEPOINT
        for char in value
    )


def normalize_mindmap_tag_identifier(value: Any) -> Any:
    """清理标签体系稳定 Key，格式由字段 pattern 继续验证。"""
    return value.strip() if isinstance(value, str) else value


def normalize_mindmap_tag_display_name(value: Any, *, label: str) -> Any:
    """清理必填展示名称并拒绝不可见控制字符。"""
    if not isinstance(value, str):
        return value
    normalized = value.strip()
    if not normalized:
        raise ValueError(f'{label}不能为空')
    if _contains_control_character(normalized):
        raise ValueError(f'{label}不能包含控制字符')
    return normalized


def normalize_mindmap_tag_description(value: Any, *, label: str) -> Any:
    """清理可选说明，保留换行/制表并拒绝其他控制字符。"""
    if value is None or not isinstance(value, str):
        return value
    normalized = value.strip()
    if not normalized:
        return None
    if _contains_control_character(normalized, allow_multiline=True):
        raise ValueError(f'{label}不能包含不可见控制字符')
    return normalized


def normalize_mindmap_tag_search_keyword(value: Any) -> Any:
    if value is None or not isinstance(value, str):
        return value
    normalized = value.strip()
    if not normalized:
        return None
    if _contains_control_character(normalized):
        raise ValueError('标签搜索关键词不能包含控制字符')
    return normalized


def normalize_mindmap_tag_color(value: Any, *, label: str) -> Any:
    """把标签颜色收敛为 transparent 或 Hex/Hex8，拒绝任意 CSS 值。"""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f'{label}必须是颜色字符串')
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.lower() == 'transparent':
        return 'transparent'
    if MINDMAP_TAG_COLOR_PATTERN.fullmatch(normalized):
        return normalized.lower()
    rgb_match = (
        MINDMAP_TAG_RGB_COLOR_PATTERN.fullmatch(normalized)
        or MINDMAP_TAG_RGBA_COLOR_PATTERN.fullmatch(normalized)
    )
    if rgb_match:
        channels = tuple(int(rgb_match.group(index)) for index in range(1, 4))
        if any(channel > MAX_MINDMAP_TAG_COLOR_CHANNEL for channel in channels):
            raise ValueError(f'{label}RGB 通道必须在 0 到 255 之间')
        alpha = (
            rgb_match.group(MINDMAP_TAG_RGBA_MATCH_GROUP_COUNT)
            if rgb_match.lastindex == MINDMAP_TAG_RGBA_MATCH_GROUP_COUNT
            else None
        )
        if alpha is not None and float(alpha) > 1:
            raise ValueError(f'{label}透明度必须在 0 到 1 之间')
        suffix = '' if alpha is None else f'{round(float(alpha) * 255):02x}'
        return f'#{"".join(f"{channel:02x}" for channel in channels)}{suffix}'
    raise ValueError(f'{label}仅支持 transparent、Hex、RGB 或 RGBA 颜色')


def _normalize_mindmap_tag_style_number(value: Any, *, key: str) -> int | float:
    label = {'fontSize': '字号', 'radius': '圆角', 'paddingX': '水平内边距'}[key]
    minimum, maximum = MINDMAP_TAG_STYLE_NUMBER_BOUNDS[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'标签{label}必须是有限数字')
    if value < minimum or value > maximum:
        raise ValueError(f'标签{label}必须在 {minimum} 到 {maximum} 之间')
    return int(value) if float(value).is_integer() else value


def _normalize_mindmap_tag_style_value(key: str, raw: Any) -> Any:
    if key in MINDMAP_TAG_STYLE_COLOR_KEYS:
        return normalize_mindmap_tag_color(
            raw,
            label='标签背景色' if key == 'fill' else '标签文字色',
        )
    if key in MINDMAP_TAG_STYLE_NUMBER_BOUNDS:
        return _normalize_mindmap_tag_style_number(raw, key=key)
    if key == 'placement':
        if not isinstance(raw, str) or raw not in MINDMAP_TAG_STYLE_PLACEMENTS:
            raise ValueError('标签位置必须是 left、right、top 或 bottom')
        return raw
    if key == 'align':
        if not isinstance(raw, str) or raw not in MINDMAP_TAG_STYLE_ALIGNS:
            raise ValueError('标签对齐方式不合法')
        return raw
    if not isinstance(raw, str) or not MINDMAP_TAG_MARKER_ICON_PATTERN.fullmatch(raw):
        raise ValueError('节点标记图标不在内置图标范围内')
    return raw


def _validate_mindmap_tag_style_alignment(style: dict[str, Any]) -> None:
    placement = style.get('placement')
    align = style.get('align')
    if not placement or not align or align == 'center':
        return
    valid_aligns = {'left', 'right'} if placement in {'top', 'bottom'} else {'top', 'bottom'}
    if align not in valid_aligns:
        raise ValueError('标签位置与对齐方式不兼容')


def normalize_mindmap_tag_style(value: Any) -> dict[str, Any] | None:
    """校验统一标签样式，避免任意对象进入跨文件渲染链路。"""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError('标签样式必须是对象')
    unknown_keys = sorted(str(key) for key in value if key not in MINDMAP_TAG_STYLE_KEYS)
    if unknown_keys:
        raise ValueError(f'标签样式包含不支持的字段: {", ".join(unknown_keys)}')

    normalized: dict[str, Any] = {}
    for key, raw in value.items():
        if raw is None or raw == '':
            continue
        normalized_value = _normalize_mindmap_tag_style_value(key, raw)
        if normalized_value is not None:
            normalized[key] = normalized_value

    _validate_mindmap_tag_style_alignment(normalized)
    return normalized or None


class MindmapTagCategoryModel(BaseModel):
    """标签分组模型（字段名保持 category 兼容）。"""
    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    id: int | None = Field(default=None, description='分组ID')
    name: str | None = Field(default=None, description='分组名称')
    category_type: Literal['system', 'custom'] = Field(
        default='custom', description='分组类型:system系统 custom用户自定义',
    )
    owner_id: int | None = Field(default=0, description='所有者(0=全局)')
    sort_order: int | None = Field(default=0, description='排序')
    created_by: str | None = Field(default=None, description='创建人')
    created_time: datetime | None = Field(default=None, description='创建时间')


class MindmapTagCategoryListItemModel(MindmapTagCategoryModel):
    """标签分组列表项。"""

    tag_count: int = Field(default=0, ge=0, description='分组下的标签数量')


class MindmapTagCategoryMutationModel(BaseModel):
    """标签分组创建/更新模型。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    name: str = Field(
        min_length=1,
        max_length=MAX_MINDMAP_TAG_CATEGORY_NAME_LENGTH,
        description='分组名称',
    )
    sort_order: int = Field(
        default=0,
        ge=-MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER,
        le=MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER,
        description='排序值',
    )
    owner_scope: Literal['mine', 'global'] = Field(default='mine', description='分组作用域')

    @field_validator('name', mode='before')
    @classmethod
    def normalize_name(cls, value: Any) -> Any:
        return normalize_mindmap_tag_display_name(value, label='分组名称')


class MindmapTagCategoryCreateResultModel(BaseModel):
    """标签分组创建结果。"""

    model_config = ConfigDict(alias_generator=to_camel)

    category_id: int = Field(gt=0, description='新分组ID')


class MindmapTagCategoryReorderModel(BaseModel):
    """同一所有者范围内的标签分组排序。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    category_ids: list[Annotated[int, Field(strict=True, gt=0)]] = Field(
        min_length=1,
        max_length=MAX_MINDMAP_TAG_CATEGORY_BATCH_SIZE,
        description='按目标顺序排列的完整分组ID列表',
    )

    @field_validator('category_ids')
    @classmethod
    def validate_category_ids(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError('分组ID不能重复')
        return value


class MindmapTagArchiveResultModel(BaseModel):
    """批量标签归档结果。"""

    model_config = ConfigDict(alias_generator=to_camel)

    tag_ids: list[int] = Field(
        min_length=1,
        max_length=MAX_MINDMAP_TAG_BATCH_SIZE,
        description='已归档标签ID',
    )
    unbind: bool = Field(description='是否已解除当前节点绑定')
    affected_file_count: int = Field(ge=0, description='受影响脑图数量')


class MindmapTagModel(BaseModel):
    """标签模型（用于创建/更新）"""
    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True, populate_by_name=True)

    id: int | None = Field(default=None, description='标签ID')
    uuid: str | None = Field(default=None, description='UUID(自动生成)')
    tag_key: str = Field(
        min_length=1,
        max_length=MAX_MINDMAP_TAG_KEY_LENGTH,
        pattern=r'^[a-zA-Z0-9_\-]+$',
        description='标签key(自定义必填)',
    )
    name: str = Field(min_length=1, max_length=MAX_MINDMAP_TAG_NAME_LENGTH, description='标签显示名称')
    category_id: int | None = Field(default=None, description='所属分组ID')
    owner_id: int | None = Field(default=0, description='所有者(0=全局)')
    style: dict[str, Any] | None = Field(default=None, description='标签样式JSON')
    description: str | None = Field(
        default=None,
        max_length=MAX_MINDMAP_TAG_DESCRIPTION_LENGTH,
        description='标签描述',
    )
    status: int | None = Field(default=0, ge=0, le=2, description='状态:0启用 1停用 2归档')
    definition_revision: int | None = Field(default=1, description='定义修订号')
    usage_node_count: int | None = Field(default=0, description='使用节点数')
    usage_file_count: int | None = Field(default=0, description='使用文件数')
    update_by: str | None = Field(default=None, description='最后修改人')
    created_by: str | None = Field(default=None, description='创建人')
    created_time: datetime | None = Field(default=None, description='创建时间')
    updated_time: datetime | None = Field(default=None, description='更新时间')

    @field_validator('tag_key', mode='before')
    @classmethod
    def normalize_tag_key(cls, value: Any) -> Any:
        return normalize_mindmap_tag_identifier(value)

    @field_validator('name', mode='before')
    @classmethod
    def normalize_name(cls, value: Any) -> Any:
        return normalize_mindmap_tag_display_name(value, label='标签名称')

    @field_validator('description', mode='before')
    @classmethod
    def normalize_description(cls, value: Any) -> Any:
        return normalize_mindmap_tag_description(value, label='标签说明')

    @field_validator('style', mode='before')
    @classmethod
    def normalize_style(cls, value: Any) -> dict[str, Any] | None:
        return normalize_mindmap_tag_style(value)


class MindmapTagListItemModel(BaseModel):
    """标签列表项（轻量）"""
    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    id: int | None = Field(default=None, description='标签ID')
    uuid: str | None = Field(default=None, description='UUID')
    tag_key: str | None = Field(default=None, description='标签key')
    name: str | None = Field(default=None, description='标签名称')
    category_id: int | None = Field(default=None, description='分组ID')
    owner_id: int | None = Field(default=None, description='所有者')
    style: dict[str, Any] | None = Field(default=None, description='标签样式')
    description: str | None = Field(default=None, description='描述')
    status: int | None = Field(default=0, description='状态')
    definition_revision: int | None = Field(default=1, description='定义修订号')
    usage_node_count: int | None = Field(default=0, description='使用节点数')
    usage_file_count: int | None = Field(default=0, description='使用文件数')
    created_by: str | None = Field(default=None, description='创建人')
    created_time: datetime | None = Field(default=None, description='创建时间')
    update_by: str | None = Field(default=None, description='最后修改人')
    updated_time: datetime | None = Field(default=None, description='更新时间')


class MindmapTagQueryModel(BaseModel):
    """标签查询模型"""
    model_config = ConfigDict(alias_generator=to_camel)

    category_id: int | None = Field(default=None, ge=0, description='分组ID筛选，0 表示未分组')
    status: int | None = Field(default=None, ge=0, le=2, description='状态筛选:0启用 1停用 2归档')
    keyword: str | None = Field(
        default=None,
        max_length=MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH,
        description='关键词搜索(name/tag_key/description)',
    )
    owner_scope: Literal['all', 'mine', 'global'] = Field(default='all', description='范围')
    page_num: int = Field(default=1, ge=1, description='页码')
    page_size: int = Field(default=20, ge=1, le=100, description='每页数量')

    @field_validator('keyword', mode='before')
    @classmethod
    def normalize_keyword(cls, value: str | None) -> str | None:
        return normalize_mindmap_tag_search_keyword(value)


class MindmapTagSuggestionQueryModel(BaseModel):
    """标签自动完成查询模型。"""

    keyword: str | None = Field(
        default=None,
        max_length=MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH,
        description='标签名称或 Key 关键词',
    )

    @field_validator('keyword', mode='before')
    @classmethod
    def normalize_keyword(cls, value: str | None) -> str | None:
        return normalize_mindmap_tag_search_keyword(value)


class MindmapTagReplaceModel(BaseModel):
    """全局替换标签请求。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    target_tag_id: int = Field(gt=0, description='目标标签ID')


class MindmapTagSuggestionModel(BaseModel):
    """标签建议模型（用于编辑器自动补全）"""
    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    id: int | None = Field(default=None, description='标签ID')
    uuid: str | None = Field(default=None, description='UUID')
    tag_key: str | None = Field(default=None, description='标签key')
    name: str | None = Field(default=None, description='标签名称')
    category_id: int | None = Field(default=None, description='所属标签分组ID')
    style: dict[str, Any] | None = Field(default=None, description='标签样式')
    owner_id: int | None = Field(default=None, description='所有者(0=全局)')
    status: int | None = Field(default=0, description='状态')
    definition_revision: int | None = Field(default=1, description='定义修订号')
