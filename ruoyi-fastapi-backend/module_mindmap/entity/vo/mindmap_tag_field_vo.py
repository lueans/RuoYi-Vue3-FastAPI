"""脑图标签字段 Pydantic 模型"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from module_mindmap.entity.vo.mindmap_tag_vo import (
    MAX_MINDMAP_TAG_DESCRIPTION_LENGTH,
    MAX_MINDMAP_TAG_KEY_LENGTH,
    MAX_MINDMAP_TAG_NAME_LENGTH,
    MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH,
    normalize_mindmap_tag_color,
    normalize_mindmap_tag_description,
    normalize_mindmap_tag_display_name,
    normalize_mindmap_tag_identifier,
    normalize_mindmap_tag_search_keyword,
    normalize_mindmap_tag_style,
)

MAX_MINDMAP_TAG_FIELD_NAME_LENGTH = 100

# ── 选项模型 ──

class TagFieldOptionModel(BaseModel):
    """字段选项模型（创建/更新）"""
    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True, populate_by_name=True)

    id: int | None = Field(default=None, description='选项ID')
    field_id: int | None = Field(default=None, description='所属字段ID')
    tag_id: int | None = Field(default=None, description='关联统一标签ID')
    option_key: str = Field(
        min_length=1,
        max_length=MAX_MINDMAP_TAG_KEY_LENGTH,
        pattern=r'^[a-zA-Z0-9_\-]+$',
        description='选项key',
    )
    name: str = Field(min_length=1, max_length=MAX_MINDMAP_TAG_NAME_LENGTH, description='选项显示名称')
    fill: str | None = Field(default=None, max_length=20, description='背景色')
    color: str | None = Field(default=None, max_length=20, description='文字色')
    sort_order: int | None = Field(default=0, description='排序')

    @field_validator('option_key', mode='before')
    @classmethod
    def normalize_option_key(cls, value: Any) -> Any:
        return normalize_mindmap_tag_identifier(value)

    @field_validator('name', mode='before')
    @classmethod
    def normalize_name(cls, value: Any) -> Any:
        return normalize_mindmap_tag_display_name(value, label='选项名称')

    @field_validator('fill', mode='before')
    @classmethod
    def normalize_fill(cls, value: Any) -> Any:
        return normalize_mindmap_tag_color(value, label='选项背景色')

    @field_validator('color', mode='before')
    @classmethod
    def normalize_color(cls, value: Any) -> Any:
        return normalize_mindmap_tag_color(value, label='选项文字色')


class TagFieldOptionItemModel(BaseModel):
    """选项列表项（轻量）"""
    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    id: int | None = Field(default=None, description='选项ID')
    field_id: int | None = Field(default=None, description='所属字段ID')
    tag_id: int | None = Field(default=None, description='关联统一标签ID')
    option_key: str | None = Field(default=None, description='选项key')
    name: str | None = Field(default=None, description='选项名称')
    fill: str | None = Field(default=None, description='背景色')
    color: str | None = Field(default=None, description='文字色')
    sort_order: int | None = Field(default=None, description='排序')
    created_time: datetime | None = Field(default=None, description='创建时间')


class TagFieldOptionSortModel(BaseModel):
    """选项批量排序模型"""
    model_config = ConfigDict(alias_generator=to_camel)

    option_id: int = Field(description='选项ID')
    sort_order: int = Field(description='排序值')


# ── 字段模型 ──

class TagFieldModel(BaseModel):
    """标签字段模型（创建/更新）"""
    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True, populate_by_name=True)

    id: int | None = Field(default=None, description='字段ID')
    field_key: str = Field(
        min_length=1,
        max_length=MAX_MINDMAP_TAG_KEY_LENGTH,
        pattern=r'^[a-zA-Z0-9_\-]+$',
        description='字段key',
    )
    name: str = Field(min_length=1, max_length=MAX_MINDMAP_TAG_FIELD_NAME_LENGTH, description='字段显示名称')
    select_mode: str = Field(default='single', pattern=r'^(single|multi)$', description='选择模式: single/multi')
    style: dict[str, Any] | None = Field(default=None, description='基础样式 {fontSize,radius,paddingX,placement,align}')
    owner_id: int | None = Field(default=0, description='所有者(0=全局)')
    sort_order: int | None = Field(default=0, description='排序')
    description: str | None = Field(
        default=None,
        max_length=MAX_MINDMAP_TAG_DESCRIPTION_LENGTH,
        description='字段描述',
    )

    @field_validator('field_key', mode='before')
    @classmethod
    def normalize_field_key(cls, value: Any) -> Any:
        return normalize_mindmap_tag_identifier(value)

    @field_validator('name', mode='before')
    @classmethod
    def normalize_name(cls, value: Any) -> Any:
        return normalize_mindmap_tag_display_name(value, label='字段名称')

    @field_validator('description', mode='before')
    @classmethod
    def normalize_description(cls, value: Any) -> Any:
        return normalize_mindmap_tag_description(value, label='字段说明')

    @field_validator('style', mode='before')
    @classmethod
    def normalize_style(cls, value: Any) -> dict[str, Any] | None:
        return normalize_mindmap_tag_style(value, field_style=True)


class TagFieldListItemModel(BaseModel):
    """字段列表项"""
    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    id: int | None = Field(default=None, description='字段ID')
    field_key: str | None = Field(default=None, description='字段key')
    name: str | None = Field(default=None, description='字段名称')
    select_mode: str | None = Field(default=None, description='选择模式')
    style: dict[str, Any] | None = Field(default=None, description='基础样式')
    owner_id: int | None = Field(default=None, description='所有者')
    sort_order: int | None = Field(default=None, description='排序')
    description: str | None = Field(default=None, description='描述')
    created_by: str | None = Field(default=None, description='创建人')
    created_time: datetime | None = Field(default=None, description='创建时间')
    updated_time: datetime | None = Field(default=None, description='更新时间')


class TagFieldDetailModel(TagFieldListItemModel):
    """字段详情（含选项列表）"""
    options: list[TagFieldOptionItemModel] | None = Field(default=None, description='选项列表')


# ── 搜索建议 ──

class TagFieldSuggestionQueryModel(BaseModel):
    """字段和选项搜索查询模型。"""

    keyword: str | None = Field(
        default=None,
        max_length=MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH,
        description='字段名称、字段 Key、选项名称或选项 Key',
    )

    @field_validator('keyword', mode='before')
    @classmethod
    def normalize_keyword(cls, value: str | None) -> str | None:
        return normalize_mindmap_tag_search_keyword(value)

class TagFieldSuggestionOptionModel(BaseModel):
    """搜索建议中的选项"""
    model_config = ConfigDict(alias_generator=to_camel)

    id: int = Field(description='选项ID')
    tag_id: int | None = Field(default=None, description='关联统一标签ID')
    option_key: str = Field(description='选项key')
    name: str = Field(description='选项名称')
    fill: str | None = Field(default=None, description='背景色')
    color: str | None = Field(default=None, description='文字色')


class TagFieldSuggestionModel(BaseModel):
    """字段搜索建议（侧边栏用）"""
    model_config = ConfigDict(alias_generator=to_camel)

    field_id: int = Field(description='字段ID')
    field_name: str = Field(description='字段名称')
    field_key: str = Field(description='字段key')
    select_mode: str = Field(description='选择模式')
    style: dict[str, Any] | None = Field(default=None, description='基础样式')
    options: list[TagFieldSuggestionOptionModel] = Field(default_factory=list, description='匹配的选项')
