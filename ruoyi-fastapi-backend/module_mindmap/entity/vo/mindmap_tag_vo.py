"""脑图标签 Pydantic 模型"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class MindmapTagCategoryModel(BaseModel):
    """标签分类模型"""
    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    id: int | None = Field(default=None, description='分类ID')
    name: str | None = Field(default=None, description='分类名称')
    owner_id: int | None = Field(default=0, description='所有者(0=全局)')
    sort_order: int | None = Field(default=0, description='排序')
    created_by: str | None = Field(default=None, description='创建人')
    created_time: datetime | None = Field(default=None, description='创建时间')


class MindmapTagModel(BaseModel):
    """标签模型（用于创建/更新）"""
    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True, populate_by_name=True)

    id: int | None = Field(default=None, description='标签ID')
    uuid: str | None = Field(default=None, description='UUID(自动生成)')
    tag_key: str = Field(description='标签key(自定义必填)')
    name: str = Field(description='标签显示名称')
    category_id: int | None = Field(default=None, description='所属分类ID')
    owner_id: int | None = Field(default=0, description='所有者(0=全局)')
    style: dict[str, Any] | None = Field(default=None, description='标签样式JSON')
    description: str | None = Field(default=None, description='标签描述')
    created_by: str | None = Field(default=None, description='创建人')
    created_time: datetime | None = Field(default=None, description='创建时间')
    updated_time: datetime | None = Field(default=None, description='更新时间')


class MindmapTagListItemModel(BaseModel):
    """标签列表项（轻量）"""
    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    id: int | None = Field(default=None, description='标签ID')
    uuid: str | None = Field(default=None, description='UUID')
    tag_key: str | None = Field(default=None, description='标签key')
    name: str | None = Field(default=None, description='标签名称')
    category_id: int | None = Field(default=None, description='分类ID')
    owner_id: int | None = Field(default=None, description='所有者')
    style: dict[str, Any] | None = Field(default=None, description='标签样式')
    description: str | None = Field(default=None, description='描述')
    created_by: str | None = Field(default=None, description='创建人')
    created_time: datetime | None = Field(default=None, description='创建时间')


class MindmapTagQueryModel(BaseModel):
    """标签查询模型"""
    model_config = ConfigDict(alias_generator=to_camel)

    category_id: int | None = Field(default=None, description='分类ID筛选')
    keyword: str | None = Field(default=None, description='关键词搜索(name/tag_key)')
    owner_scope: str | None = Field(default='all', description='范围: all/mine/global')
    page_num: int = Field(default=1, description='页码')
    page_size: int = Field(default=20, description='每页数量')


class MindmapTagSuggestionModel(BaseModel):
    """标签建议模型（用于编辑器自动补全）"""
    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    id: int | None = Field(default=None, description='标签ID')
    uuid: str | None = Field(default=None, description='UUID')
    tag_key: str | None = Field(default=None, description='标签key')
    name: str | None = Field(default=None, description='标签名称')
    style: dict[str, Any] | None = Field(default=None, description='标签样式')
    owner_id: int | None = Field(default=None, description='所有者(0=全局)')
