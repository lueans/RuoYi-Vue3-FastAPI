"""脑图协作者 Pydantic 模型"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class MindmapCollaboratorModel(BaseModel):
    """协作者完整模型"""
    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    id: int | None = Field(default=None, description='记录ID')
    mindmap_id: int | None = Field(default=None, description='脑图ID')
    user_id: int | None = Field(default=None, description='协作用户ID')
    permission: int | None = Field(default=0, description='0=查看 1=编辑')
    created_by: int | None = Field(default=None, description='添加者')
    created_time: datetime | None = Field(default=None, description='创建时间')
    # 额外展示字段（从 user 表 join 或填充）
    user_name: str | None = Field(default=None, description='用户名')
    nick_name: str | None = Field(default=None, description='昵称')
    avatar: str | None = Field(default=None, description='头像')


class MindmapCollaboratorAddModel(BaseModel):
    """添加协作者模型"""
    model_config = ConfigDict(alias_generator=to_camel)

    mindmap_id: int = Field(description='脑图ID')
    user_id: int = Field(description='协作用户ID')
    permission: int = Field(default=0, ge=0, le=1, description='0=查看 1=编辑')


class MindmapCollaboratorUpdateModel(BaseModel):
    """修改协作者权限模型"""
    model_config = ConfigDict(alias_generator=to_camel)

    id: int = Field(description='协作者记录ID')
    permission: int = Field(ge=0, le=1, description='0=查看 1=编辑')
