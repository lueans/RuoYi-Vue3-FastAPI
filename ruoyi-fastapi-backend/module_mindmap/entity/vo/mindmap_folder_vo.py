"""脑图文件夹 Pydantic 模型"""
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class MindmapFolderModel(BaseModel):
    """文件夹请求模型（客户端可提交字段）"""
    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True, populate_by_name=True)

    id: int | None = Field(default=None, description='文件夹ID（更新时必填）')
    name: str | None = Field(default=None, min_length=1, max_length=100, description='文件夹名称')
    parent_id: int | None = Field(default=None, description='父文件夹ID（0=顶级）')
    sort_order: int | None = Field(default=None, description='排序序号')


class MindmapFolderSortModel(BaseModel):
    """文件夹排序模型"""
    model_config = ConfigDict(alias_generator=to_camel)

    items: list['FolderSortItem'] = Field(min_length=1, max_length=200, description='排序项列表')


class FolderSortItem(BaseModel):
    """排序项"""
    model_config = ConfigDict(alias_generator=to_camel)

    id: int = Field(description='文件夹ID')
    sort_order: int = Field(description='排序序号')
    parent_id: int | None = Field(default=None, description='新的父文件夹ID（可选）')


class MindmapMoveModel(BaseModel):
    """移动脑图到文件夹"""
    model_config = ConfigDict(alias_generator=to_camel)

    mindmap_ids: list[int] = Field(min_length=1, max_length=100, description='脑图ID列表（最多100个）')
    folder_id: int | None = Field(default=None, description='目标文件夹ID（null=根目录）')
