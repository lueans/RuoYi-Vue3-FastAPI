"""脑图标签字段 Pydantic 模型"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


# ── 选项模型 ──

class TagFieldOptionModel(BaseModel):
    """字段选项模型（创建/更新）"""
    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True, populate_by_name=True)

    id: int | None = Field(default=None, description='选项ID')
    field_id: int | None = Field(default=None, description='所属字段ID')
    option_key: str = Field(min_length=1, max_length=100, pattern=r'^[a-zA-Z0-9_\-]+$', description='选项key')
    name: str = Field(min_length=1, max_length=200, description='选项显示名称')
    fill: str | None = Field(default=None, max_length=20, description='背景色')
    color: str | None = Field(default=None, max_length=20, description='文字色')
    sort_order: int | None = Field(default=0, description='排序')


class TagFieldOptionItemModel(BaseModel):
    """选项列表项（轻量）"""
    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    id: int | None = Field(default=None, description='选项ID')
    field_id: int | None = Field(default=None, description='所属字段ID')
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
    field_key: str = Field(min_length=1, max_length=100, pattern=r'^[a-zA-Z0-9_\-]+$', description='字段key')
    name: str = Field(min_length=1, max_length=100, description='字段显示名称')
    select_mode: str = Field(default='single', pattern=r'^(single|multi)$', description='选择模式: single/multi')
    style: dict[str, Any] | None = Field(default=None, description='基础样式 {fontSize,radius,paddingX,placement,align}')
    owner_id: int | None = Field(default=0, description='所有者(0=全局)')
    sort_order: int | None = Field(default=0, description='排序')
    description: str | None = Field(default=None, max_length=500, description='字段描述')


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

class TagFieldSuggestionOptionModel(BaseModel):
    """搜索建议中的选项"""
    model_config = ConfigDict(alias_generator=to_camel)

    id: int = Field(description='选项ID')
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
    options: list[TagFieldSuggestionOptionModel] = Field(default=[], description='匹配的选项')
