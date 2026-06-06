"""脑图模板 Pydantic 模型"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class MindmapTemplateCategoryModel(BaseModel):
    """模板分类模型"""
    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    id: int | None = Field(default=None, description='分类ID')
    name: str | None = Field(default=None, description='分类名称')
    sort_order: int | None = Field(default=0, description='排序')
    created_time: datetime | None = Field(default=None, description='创建时间')


class MindmapTemplateListItemModel(BaseModel):
    """模板列表项（轻量，不含 node_tree）"""
    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    id: int | None = Field(default=None, description='模板ID')
    name: str | None = Field(default=None, description='模板名称')
    description: str | None = Field(default=None, description='描述')
    cover_image: str | None = Field(default=None, description='封面图')
    layout: str | None = Field(default=None, description='布局类型')
    template_category_id: int | None = Field(default=None, description='分类ID')
    create_time: datetime | None = Field(default=None, description='创建时间')


class MindmapTemplatePublishModel(BaseModel):
    """发布模板模型"""
    model_config = ConfigDict(alias_generator=to_camel)

    mindmap_id: int = Field(description='源脑图ID（将复制为模板）')
    name: str = Field(description='模板名称')
    description: str | None = Field(default=None, description='模板描述')
    cover_image: str | None = Field(default=None, description='封面图URL')
    template_category_id: int | None = Field(default=None, description='分类ID')


class MindmapTemplateQueryModel(BaseModel):
    """模板查询模型"""
    model_config = ConfigDict(alias_generator=to_camel)

    category_id: int | None = Field(default=None, description='分类ID筛选')
    keyword: str | None = Field(default=None, description='关键词搜索')
    page_num: int = Field(default=1, description='页码')
    page_size: int = Field(default=20, description='每页数量')
