"""脑图版本历史 Pydantic 模型"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class MindmapVersionModel(BaseModel):
    """版本完整模型"""

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True, populate_by_name=True)

    id: int | None = Field(default=None, description='版本ID')
    mindmap_id: int | None = Field(default=None, description='脑图ID')
    version_number: int | None = Field(default=None, description='版本号')
    version_type: int | None = Field(default=0, description='版本类型: 0=草稿 1=正式')
    name: str | None = Field(default=None, description='版本名称')
    node_tree: dict[str, Any] | None = Field(default=None, description='节点树快照')
    view_data: dict[str, Any] | None = Field(default=None, description='视图状态')
    layout: str | None = Field(default=None, description='布局类型')
    theme: dict[str, Any] | None = Field(default=None, description='主题配置')
    snapshot_schema_version: int = Field(default=1, description='版本快照结构版本')
    tag_snapshots: dict[str, Any] | None = Field(default=None, description='历史标签定义快照')
    created_by: str | None = Field(default=None, description='创建者')
    created_time: datetime | None = Field(default=None, description='创建时间')


class MindmapVersionListModel(BaseModel):
    """版本列表项模型（不含 node_tree 大字段）"""

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True, populate_by_name=True)

    id: int | None = Field(default=None, description='版本ID')
    mindmap_id: int | None = Field(default=None, description='脑图ID')
    version_number: int | None = Field(default=None, description='版本号')
    version_type: int | None = Field(default=0, description='版本类型')
    name: str | None = Field(default=None, description='版本名称')
    layout: str | None = Field(default=None, description='布局类型')
    snapshot_schema_version: int = Field(default=1, description='版本快照结构版本')
    created_by: str | None = Field(default=None, description='创建者')
    created_time: datetime | None = Field(default=None, description='创建时间')


class MindmapVersionQueryModel(BaseModel):
    """版本查询模型"""

    model_config = ConfigDict(alias_generator=to_camel)

    mindmap_id: int = Field(description='脑图ID')
    version_type: int | None = Field(default=None, description='版本类型筛选')
    page_num: int = Field(default=1, description='当前页码')
    page_size: int = Field(default=20, description='每页记录数')


class MindmapVersionSaveModel(BaseModel):
    """手动创建正式版本模型"""

    model_config = ConfigDict(alias_generator=to_camel)

    mindmap_id: int = Field(description='脑图ID')
    name: str | None = Field(default=None, description='版本名称')
