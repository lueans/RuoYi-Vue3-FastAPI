"""脑图文件夹请求模型。"""

import unicodedata

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator
from pydantic.alias_generators import to_camel

MAX_FOLDER_NAME_LENGTH = 100
MAX_FOLDER_SORT_ORDER = 1_000_000


def normalize_folder_name(value: object) -> str:
    """统一目录名称，避免路径歧义和不可见字符。"""
    if not isinstance(value, str):
        raise ValueError('文件夹名称必须为字符串')
    normalized = value.strip()
    if not normalized:
        raise ValueError('文件夹名称不能为空')
    if any(unicodedata.category(char) == 'Cc' for char in normalized):
        raise ValueError('文件夹名称不能包含控制字符')
    if '/' in normalized or '\\' in normalized:
        raise ValueError('文件夹名称不能包含路径分隔符')
    return normalized


class MindmapFolderCreateModel(BaseModel):
    """新建文件夹请求。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    name: str = Field(min_length=1, max_length=MAX_FOLDER_NAME_LENGTH, description='文件夹名称')
    parent_id: StrictInt = Field(default=0, ge=0, description='父文件夹ID（0=顶级）')
    sort_order: StrictInt = Field(default=0, ge=0, le=MAX_FOLDER_SORT_ORDER, description='排序序号')

    @field_validator('name', mode='before')
    @classmethod
    def validate_name(cls, value: object) -> str:
        return normalize_folder_name(value)


class MindmapFolderUpdateModel(BaseModel):
    """重命名或移动文件夹请求。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: StrictInt = Field(gt=0, description='文件夹ID')
    name: str | None = Field(default=None, min_length=1, max_length=MAX_FOLDER_NAME_LENGTH)
    parent_id: StrictInt | None = Field(default=None, ge=0, description='父文件夹ID（0=顶级）')
    sort_order: StrictInt | None = Field(default=None, ge=0, le=MAX_FOLDER_SORT_ORDER)

    @field_validator('name', mode='before')
    @classmethod
    def validate_name(cls, value: object) -> str | None:
        return None if value is None else normalize_folder_name(value)

    @model_validator(mode='after')
    def validate_mutation(self) -> 'MindmapFolderUpdateModel':
        if self.name is None and self.parent_id is None and self.sort_order is None:
            raise ValueError('至少需要提交一个文件夹变更字段')
        return self


class FolderSortItem(BaseModel):
    """排序项。"""

    model_config = ConfigDict(alias_generator=to_camel)

    id: StrictInt = Field(gt=0, description='文件夹ID')
    sort_order: StrictInt = Field(ge=0, le=MAX_FOLDER_SORT_ORDER, description='排序序号')
    parent_id: StrictInt | None = Field(default=None, ge=0, description='新的父文件夹ID（可选）')


class MindmapFolderSortModel(BaseModel):
    """文件夹排序请求。"""

    model_config = ConfigDict(alias_generator=to_camel)

    items: list[FolderSortItem] = Field(min_length=1, max_length=200, description='排序项列表')

    @field_validator('items')
    @classmethod
    def validate_unique_ids(cls, value: list[FolderSortItem]) -> list[FolderSortItem]:
        ids = [item.id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError('文件夹排序项不能包含重复 ID')
        return value


class MindmapMoveModel(BaseModel):
    """移动脑图到文件夹请求。"""

    model_config = ConfigDict(alias_generator=to_camel)

    mindmap_ids: list[StrictInt] = Field(min_length=1, max_length=100, description='脑图ID列表（最多100个）')
    folder_id: StrictInt | None = Field(default=None, gt=0, description='目标文件夹ID（null=根目录）')

    @field_validator('mindmap_ids')
    @classmethod
    def validate_mindmap_ids(cls, value: list[int]) -> list[int]:
        if any(isinstance(item, bool) or item <= 0 for item in value):
            raise ValueError('脑图 ID 必须为正整数')
        if len(value) != len(set(value)):
            raise ValueError('脑图 ID 不能重复')
        return value
