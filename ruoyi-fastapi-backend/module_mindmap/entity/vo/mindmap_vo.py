from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from pydantic_validation_decorator import NotBlank, Size


class MindmapModel(BaseModel):
    """思维导图模型"""

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True, populate_by_name=True)

    id: int | None = Field(default=None, description='思维导图ID')
    name: str | None = Field(default=None, description='思维导图名称')
    description: str | None = Field(default=None, description='描述')
    owner_id: int | None = Field(default=None, description='所有者ID')
    layout: str | None = Field(default='logicalStructure', description='布局类型')
    theme: dict[str, Any] | None = Field(default=None, description='主题配置')
    node_tree: dict[str, Any] | None = Field(default=None, description='节点树')
    view_data: dict[str, Any] | None = Field(default=None, description='视图状态')
    cover_image: str | None = Field(default=None, description='封面图片URL')
    is_template: int | None = Field(default=0, description='是否模板')
    last_version_id: int | None = Field(default=None, description='最新版本ID')
    version_count: int | None = Field(default=1, description='版本总数')
    status: int | None = Field(default=0, description='状态')
    create_by: str | None = Field(default=None, description='创建者')
    create_time: datetime | None = Field(default=None, description='创建时间')
    update_by: str | None = Field(default=None, description='更新者')
    update_time: datetime | None = Field(default=None, description='更新时间')
    remark: str | None = Field(default=None, description='备注')

    @NotBlank(field_name='name', message='思维导图名称不能为空')
    @Size(field_name='name', min_length=0, max_length=200, message='思维导图名称长度不能超过200个字符')
    def get_name(self) -> str | None:
        return self.name

    def validate_fields(self) -> None:
        self.get_name()


class MindmapQueryModel(MindmapModel):
    """思维导图查询模型（不分页）"""

    begin_time: str | None = Field(default=None, description='开始时间')
    end_time: str | None = Field(default=None, description='结束时间')


class MindmapPageQueryModel(MindmapQueryModel):
    """思维导图分页查询模型"""

    page_num: int = Field(default=1, description='当前页码')
    page_size: int = Field(default=10, description='每页记录数')
    sort_field: str | None = Field(default='update_time', description='排序字段')
    sort_order: str | None = Field(default='desc', description='排序方向')


class MindmapContentUpdateModel(BaseModel):
    """思维导图内容更新模型（自动保存）"""

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True, populate_by_name=True)

    id: int = Field(description='思维导图ID')
    node_tree: dict[str, Any] = Field(description='完整节点树')
    view_data: dict[str, Any] | None = Field(default=None, description='视图状态')
    layout: str | None = Field(default=None, description='布局类型')
    theme: dict[str, Any] | None = Field(default=None, description='主题配置')


class MindmapRenameModel(BaseModel):
    """思维导图重命名模型"""

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True, populate_by_name=True)

    id: int = Field(description='思维导图ID')
    name: str = Field(description='新名称')

    @NotBlank(field_name='name', message='名称不能为空')
    @Size(field_name='name', min_length=0, max_length=200, message='名称长度不能超过200个字符')
    def get_name(self) -> str:
        return self.name

    def validate_fields(self) -> None:
        self.get_name()


class MindmapListItemModel(BaseModel):
    """思维导图列表项模型（轻量，不含node_tree）"""

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True, populate_by_name=True)

    id: int | None = Field(default=None, description='思维导图ID')
    name: str | None = Field(default=None, description='思维导图名称')
    description: str | None = Field(default=None, description='描述')
    layout: str | None = Field(default=None, description='布局类型')
    cover_image: str | None = Field(default=None, description='封面图片URL')
    is_template: int | None = Field(default=0, description='是否模板')
    version_count: int | None = Field(default=1, description='版本总数')
    status: int | None = Field(default=0, description='状态')
    create_time: datetime | None = Field(default=None, description='创建时间')
    update_time: datetime | None = Field(default=None, description='更新时间')


class DeleteMindmapModel(BaseModel):
    """删除思维导图模型"""

    model_config = ConfigDict(alias_generator=to_camel)

    mindmap_ids: str = Field(description='需要删除的思维导图ID，逗号分隔')


class MindmapImportModel(BaseModel):
    """从localStorage导入思维导图模型"""

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True, populate_by_name=True)

    name: str = Field(description='思维导图名称')
    root: dict[str, Any] = Field(description='节点树（来自localStorage）')
    layout: str | None = Field(default='logicalStructure', description='布局类型')
    theme: dict[str, Any] | None = Field(default=None, description='主题配置')
    view: dict[str, Any] | None = Field(default=None, description='视图状态')
