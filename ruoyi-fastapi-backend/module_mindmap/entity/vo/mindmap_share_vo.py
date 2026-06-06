"""脑图分享链接 Pydantic 模型"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class MindmapShareModel(BaseModel):
    """分享链接完整模型"""
    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    id: int | None = Field(default=None, description='分享ID')
    mindmap_id: int | None = Field(default=None, description='脑图ID')
    share_token: str | None = Field(default=None, description='分享token')
    share_type: int | None = Field(default=0, description='0=查看 1=编辑')
    expire_time: datetime | None = Field(default=None, description='过期时间')
    created_by: int | None = Field(default=None, description='创建者')
    created_time: datetime | None = Field(default=None, description='创建时间')
    is_active: int | None = Field(default=1, description='是否有效')


class MindmapShareCreateModel(BaseModel):
    """创建分享链接模型"""
    model_config = ConfigDict(alias_generator=to_camel)

    mindmap_id: int = Field(description='脑图ID')
    share_type: int = Field(default=0, description='0=查看 1=编辑')
    expire_time: datetime | None = Field(default=None, description='过期时间（不传=永久）')
