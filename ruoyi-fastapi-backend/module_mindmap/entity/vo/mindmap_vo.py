import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator
from pydantic.alias_generators import to_camel
from pydantic_validation_decorator import NotBlank, Size

NODE_OPERATION_TYPES = frozenset({'node.create', 'node.update', 'node.delete'})
NODE_TAG_OPERATION_TYPES = frozenset({'node.tag.bind', 'node.tag.unbind', 'node.tag.reorder'})
CROSS_NODE_OPERATION_PREFIXES = frozenset({'relation', 'summary', 'group', 'asset'})
CROSS_NODE_OPERATION_TYPES = frozenset({
    f'{prefix}.{action}'
    for prefix in CROSS_NODE_OPERATION_PREFIXES
    for action in ('upsert', 'delete')
})
TREE_OPERATION_TYPES = NODE_OPERATION_TYPES | NODE_TAG_OPERATION_TYPES | CROSS_NODE_OPERATION_TYPES
FILE_OPERATION_FIELDS = {
    'file.layout.update': 'layout',
    'file.theme.update': 'theme',
    'file.view.update': 'view_data',
    'file.document_data.update': 'document_data',
}
LEGACY_DOCUMENT_OPERATION_TYPES = frozenset({'document.update'})
CONTENT_SNAPSHOT_OPERATION_TYPES = frozenset({'document.content.update'})
SUPPORTED_CONTENT_OPERATION_TYPES = (
    TREE_OPERATION_TYPES
    | frozenset(FILE_OPERATION_FIELDS)
    | LEGACY_DOCUMENT_OPERATION_TYPES
    | CONTENT_SNAPSHOT_OPERATION_TYPES
)
MAX_MINDMAP_NAME_LENGTH = 200
MAX_MINDMAP_DESCRIPTION_LENGTH = 500
MAX_MINDMAP_FILE_KEYWORD_LENGTH = 100
ASCII_CONTROL_END = 32
ASCII_DELETE = 127
MAX_DOCUMENT_DATA_BYTES = 128 * 1024
MAX_DOCUMENT_DATA_DEPTH = 20
MAX_DOCUMENT_DATA_ITEMS = 5_000


def normalize_mindmap_name(value: Any) -> Any:
    """统一清理名称并拒绝不可见控制字符。"""
    if not isinstance(value, str):
        return value
    normalized = value.strip()
    if any(ord(char) < ASCII_CONTROL_END or ord(char) == ASCII_DELETE for char in normalized):
        raise ValueError('脑图名称不能包含控制字符')
    return normalized


def normalize_mindmap_description(value: Any) -> Any:
    """清理文件说明，允许换行与制表但拒绝其他控制字符。"""
    if value is None or not isinstance(value, str):
        return value
    normalized = value.strip()
    if any(
        (ord(char) < ASCII_CONTROL_END and char not in {'\t', '\n', '\r'})
        or ord(char) == ASCII_DELETE
        for char in normalized
    ):
        raise ValueError('脑图说明不能包含不可见控制字符')
    return normalized or None


def normalize_mindmap_file_keyword(value: Any) -> Any:
    """规范化文件搜索词，拒绝无法展示的控制字符。"""
    if value is None or not isinstance(value, str):
        return value
    normalized = value.strip()
    if any(ord(char) < ASCII_CONTROL_END or ord(char) == ASCII_DELETE for char in normalized):
        raise ValueError('文件搜索关键词不能包含控制字符')
    return normalized or None


def validate_document_data(value: Any) -> Any:
    """限制文档扩展配置，保留 JSON 透传能力但拒绝无界或异常结构。"""
    if value is None:
        return value
    if not isinstance(value, dict):
        raise ValueError('文档扩展配置必须是对象')
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise ValueError('文档扩展配置必须是有效 JSON') from exc
    if len(encoded) > MAX_DOCUMENT_DATA_BYTES:
        raise ValueError('文档扩展配置不能超过128KB')

    item_count = 0
    pending = [(value, 1)]
    while pending:
        current, depth = pending.pop()
        if depth > MAX_DOCUMENT_DATA_DEPTH:
            raise ValueError(f'文档扩展配置层级不能超过{MAX_DOCUMENT_DATA_DEPTH}层')
        children = current.values() if isinstance(current, dict) else current
        for child in children:
            item_count += 1
            if item_count > MAX_DOCUMENT_DATA_ITEMS:
                raise ValueError(f'文档扩展配置元素不能超过{MAX_DOCUMENT_DATA_ITEMS}个')
            if isinstance(child, (dict, list)):
                pending.append((child, depth + 1))
    return value


class MindmapModel(BaseModel):
    """思维导图模型"""

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True, populate_by_name=True)

    id: int | None = Field(default=None, description='思维导图ID')
    name: str | None = Field(default=None, max_length=MAX_MINDMAP_NAME_LENGTH, description='思维导图名称')
    description: str | None = Field(
        default=None,
        max_length=MAX_MINDMAP_DESCRIPTION_LENGTH,
        description='描述',
    )
    owner_id: int | None = Field(default=None, description='所有者ID')
    folder_id: int | None = Field(default=None, description='所属文件夹ID')
    layout: str | None = Field(default='logicalStructure', description='布局类型')
    theme: dict[str, Any] | None = Field(default=None, description='主题配置')
    node_tree: dict[str, Any] | None = Field(default=None, description='节点树')
    root_node_id: int | None = Field(default=None, description='结构化根节点ID')
    content_revision: int | None = Field(default=1, description='内容修订号')
    node_count: int | None = Field(default=0, description='节点数量')
    schema_version: int | None = Field(default=1, description='内容模型版本')
    engine_name: str | None = Field(default='simple-mind-map', description='脑图引擎')
    engine_version: str | None = Field(default=None, description='脑图引擎版本')
    document_data: dict[str, Any] | None = Field(default=None, description='文档级扩展配置')
    node_revisions: dict[str, int] | None = Field(default=None, description='节点UID到修订号映射')
    view_data: dict[str, Any] | None = Field(default=None, description='视图状态')
    cover_image: str | None = Field(default=None, description='封面图片URL')
    last_version_id: int | None = Field(default=None, description='最新版本ID')
    version_count: int | None = Field(default=1, description='版本总数')
    status: Literal[0, 1] | None = Field(default=0, description='状态（0正常 1归档）')
    create_by: str | None = Field(default=None, description='创建者')
    create_time: datetime | None = Field(default=None, description='创建时间')
    update_by: str | None = Field(default=None, description='更新者')
    update_time: datetime | None = Field(default=None, description='更新时间')
    remark: str | None = Field(default=None, description='备注')
    access_type: Literal['owned', 'shared'] | None = Field(default=None, description='访问来源')
    effective_permission: int | None = Field(default=None, ge=0, le=1, description='当前用户有效权限')
    is_owner: bool | None = Field(default=None, description='当前用户是否为所有者')
    can_edit: bool | None = Field(default=None, description='当前用户是否可编辑')
    owner_name: str | None = Field(default=None, description='所有者昵称')
    content_state: Literal['ready', 'migration_failed', 'integrity_failed', 'load_failed'] | None = Field(
        default=None, description='内容可编辑状态',
    )
    content_state_message: str | None = Field(default=None, description='内容状态说明')

    @field_validator('name', mode='before')
    @classmethod
    def normalize_name(cls, value: Any) -> Any:
        return normalize_mindmap_name(value)

    @field_validator('description', mode='before')
    @classmethod
    def normalize_description(cls, value: Any) -> Any:
        return normalize_mindmap_description(value)

    @field_validator('document_data')
    @classmethod
    def validate_document_data_field(cls, value: Any) -> Any:
        return validate_document_data(value)

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
    keyword: str | None = Field(
        default=None,
        max_length=MAX_MINDMAP_FILE_KEYWORD_LENGTH,
        description='文件关键词（同时匹配名称和说明）',
    )
    sort_field: Literal['name', 'create_time', 'update_time', 'version_count', 'status'] = Field(
        default='update_time', description='排序字段'
    )
    sort_order: Literal['asc', 'desc'] = Field(default='desc', description='排序方向')
    folder_id: int | None = Field(default=None, description='文件夹ID筛选')
    tag_id: int | None = Field(default=None, gt=0, description='统一标签ID筛选')
    access_scope: Literal['owned', 'shared', 'trash'] = Field(default='owned', description='列表访问范围')
    status: int | None = Field(default=None, ge=0, le=1, description='状态筛选（0正常 1归档）')

    @field_validator('keyword', mode='before')
    @classmethod
    def normalize_keyword(cls, value: Any) -> Any:
        return normalize_mindmap_file_keyword(value)


class MindmapContentUpdateModel(BaseModel):
    """思维导图内容更新模型（自动保存）"""

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True, populate_by_name=True)

    id: int = Field(description='思维导图ID')
    node_tree: dict[str, Any] = Field(description='完整节点树')
    view_data: dict[str, Any] | None = Field(default=None, description='视图状态')
    layout: str | None = Field(default=None, description='布局类型')
    theme: dict[str, Any] | None = Field(default=None, description='主题配置')
    document_data: dict[str, Any] | None = Field(default=None, description='文档级扩展配置')
    base_revision: int | None = Field(default=None, description='客户端基准内容修订号')
    client_mutation_id: str | None = Field(default=None, max_length=100, description='客户端幂等标识')

    @field_validator('document_data')
    @classmethod
    def validate_document_data_field(cls, value: Any) -> Any:
        return validate_document_data(value)


class MindmapViewUpdateModel(BaseModel):
    """与正文修订号解耦的画布视图偏好。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    view_data: dict[str, Any] | None = Field(default=None, description='平移、缩放等视图状态')


class MindmapContentOperationModel(BaseModel):
    """前端 data_change_detail 转换后的领域操作。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    type: str = Field(
        min_length=1,
        max_length=50,
        description=(
            'node.create/node.update/node.delete/'
            'node.tag.bind/node.tag.unbind/node.tag.reorder/'
            'relation|summary|group|asset.upsert|delete/'
            'file.layout.update/file.theme.update/file.view.update/'
            'file.document_data.update/document.content.update/document.update'
        ),
    )
    node_uid: str | None = Field(default=None, max_length=64, description='目标节点UID')
    target_revision: int | None = Field(default=None, ge=1, description='目标节点基准修订号')
    payload: dict[str, Any] | None = Field(default=None, description='操作必要载荷')

    @field_validator('type')
    @classmethod
    def validate_operation_type(cls, value: str) -> str:
        if value not in SUPPORTED_CONTENT_OPERATION_TYPES:
            raise ValueError(f'不支持的脑图内容操作: {value}')
        return value

    @model_validator(mode='after')
    def validate_operation_shape(self) -> 'MindmapContentOperationModel':
        if (
            self.type in NODE_OPERATION_TYPES | NODE_TAG_OPERATION_TYPES
            and (not self.node_uid or not self.node_uid.strip())
        ):
            raise ValueError(f'{self.type} 必须提供 nodeUid')
        needs_payload = (
            self.type in CROSS_NODE_OPERATION_TYPES
            or self.type in NODE_TAG_OPERATION_TYPES
            or self.type in {'node.create', 'node.update'}
        )
        if needs_payload and not isinstance(self.payload, dict):
            raise ValueError(f'{self.type} 必须提供 payload')
        return self


class MindmapContentBatchModel(BaseModel):
    """结构化内容批量增量保存请求。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    base_revision: int = Field(ge=1, description='客户端基准内容修订号')
    client_mutation_id: str = Field(min_length=1, max_length=100, description='客户端幂等标识')
    operations: list[MindmapContentOperationModel] = Field(min_length=1, max_length=2000)
    node_tree: dict[str, Any] = Field(description='本批操作后的物化节点树')
    view_data: dict[str, Any] | None = Field(default=None, description='视图状态')
    layout: str | None = Field(default=None, description='布局类型')
    theme: dict[str, Any] | None = Field(default=None, description='主题配置')
    document_data: dict[str, Any] | None = Field(default=None, description='文档级扩展配置')

    @field_validator('document_data')
    @classmethod
    def validate_document_data_field(cls, value: Any) -> Any:
        return validate_document_data(value)

    @model_validator(mode='after')
    def validate_file_operation_values(self) -> 'MindmapContentBatchModel':
        operation_types = {operation.type for operation in self.operations}
        if 'file.layout.update' in operation_types and not self.layout:
            raise ValueError('file.layout.update 必须提供 layout')
        if 'file.theme.update' in operation_types and self.theme is None:
            raise ValueError('file.theme.update 必须提供 theme')
        if 'file.document_data.update' in operation_types and self.document_data is None:
            raise ValueError('file.document_data.update 必须提供 documentData')
        return self


class MindmapRenameModel(BaseModel):
    """思维导图重命名模型"""

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True, populate_by_name=True)

    id: int = Field(gt=0, description='思维导图ID')
    name: str = Field(min_length=1, max_length=MAX_MINDMAP_NAME_LENGTH, description='新名称')

    @field_validator('name', mode='before')
    @classmethod
    def normalize_name(cls, value: Any) -> Any:
        return normalize_mindmap_name(value)

    @NotBlank(field_name='name', message='名称不能为空')
    @Size(field_name='name', min_length=0, max_length=200, message='名称长度不能超过200个字符')
    def get_name(self) -> str:
        return self.name

    def validate_fields(self) -> None:
        self.get_name()


class MindmapMetadataUpdateModel(BaseModel):
    """用户可编辑的脑图文件信息。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: StrictInt = Field(gt=0, description='脑图ID')
    name: str = Field(min_length=1, max_length=MAX_MINDMAP_NAME_LENGTH, description='脑图名称')
    description: str | None = Field(
        default=None,
        max_length=MAX_MINDMAP_DESCRIPTION_LENGTH,
        description='脑图说明',
    )

    @field_validator('name', mode='before')
    @classmethod
    def normalize_name(cls, value: Any) -> Any:
        return normalize_mindmap_name(value)

    @field_validator('description', mode='before')
    @classmethod
    def normalize_description(cls, value: Any) -> Any:
        return normalize_mindmap_description(value)


class MindmapListItemModel(BaseModel):
    """思维导图列表项模型（轻量，不含node_tree）"""

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True, populate_by_name=True)

    id: int | None = Field(default=None, description='思维导图ID')
    name: str | None = Field(default=None, description='思维导图名称')
    description: str | None = Field(default=None, description='描述')
    owner_id: int | None = Field(default=None, description='所有者ID')
    owner_name: str | None = Field(default=None, description='所有者昵称')
    layout: str | None = Field(default=None, description='布局类型')
    cover_image: str | None = Field(default=None, description='封面图片URL')
    folder_id: int | None = Field(default=None, description='所属文件夹ID')
    version_count: int | None = Field(default=1, description='版本总数')
    node_count: int | None = Field(default=0, description='节点数量')
    content_revision: int | None = Field(default=1, description='内容修订号')
    schema_version: int | None = Field(default=1, description='内容模型版本')
    status: Literal[0, 1] | None = Field(default=0, description='状态（0正常 1归档）')
    create_time: datetime | None = Field(default=None, description='创建时间')
    update_time: datetime | None = Field(default=None, description='更新时间')
    access_type: Literal['owned', 'shared', 'trash'] = Field(description='访问来源')
    effective_permission: int = Field(ge=0, le=1, description='当前用户有效权限')
    is_owner: bool = Field(description='当前用户是否为所有者')
    can_edit: bool = Field(description='当前用户是否可编辑')
    content_state: Literal['ready', 'migration_failed', 'integrity_failed', 'load_failed'] = Field(
        description='内容可编辑状态',
    )


class DeleteMindmapModel(BaseModel):
    """删除思维导图模型"""

    model_config = ConfigDict(alias_generator=to_camel)

    mindmap_ids: str = Field(description='需要删除的思维导图ID，逗号分隔')


class MindmapRestoreResultModel(BaseModel):
    """回收站恢复结果与兼容降级信息。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    restored_ids: list[int] = Field(description='已恢复的脑图ID')
    legacy_recovered_ids: list[int] = Field(description='仅从旧快照重建正文的脑图ID')
    moved_to_root_ids: list[int] = Field(description='因原目录失效而恢复到根目录的脑图ID')


class MindmapStatusUpdateModel(BaseModel):
    """所有者归档或恢复脑图。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: StrictInt = Field(gt=0, description='脑图ID')
    status: StrictInt = Field(ge=0, le=1, description='目标状态（0正常 1归档）')


class MindmapBatchStatusUpdateModel(BaseModel):
    """所有者批量归档或恢复脑图。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    mindmap_ids: list[StrictInt] = Field(
        min_length=1,
        max_length=100,
        description='脑图ID列表（最多100个）',
    )
    status: StrictInt = Field(ge=0, le=1, description='目标状态（0正常 1归档）')

    @field_validator('mindmap_ids')
    @classmethod
    def validate_mindmap_ids(cls, value: list[int]) -> list[int]:
        if any(isinstance(item, bool) or item <= 0 for item in value):
            raise ValueError('脑图 ID 必须为正整数')
        if len(value) != len(set(value)):
            raise ValueError('脑图 ID 不能重复')
        return value


class MindmapBatchStatusResultModel(BaseModel):
    """批量归档或恢复的精确执行结果。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    requested_ids: list[int] = Field(description='请求处理的脑图ID')
    changed_ids: list[int] = Field(description='本次实际发生状态变化的脑图ID')
    status: Literal[0, 1] = Field(description='目标状态（0正常 1归档）')


class MindmapNodePathItemModel(BaseModel):
    """节点搜索结果中的路径片段。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    node_uid: str = Field(description='节点稳定UID')
    text: str = Field(description='节点纯文本')


class MindmapGlobalNodeSearchItemModel(BaseModel):
    """跨文件节点搜索结果。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: int = Field(description='节点数据库ID')
    node_uid: str = Field(description='节点稳定UID')
    text: str = Field(description='节点纯文本')
    mindmap_id: int = Field(description='所属脑图ID')
    mindmap_name: str = Field(description='所属脑图名称')
    owner_name: str | None = Field(default=None, description='文件所有者名称')
    access_type: Literal['owned', 'shared'] = Field(description='当前用户访问来源')
    effective_permission: Literal[0, 1] = Field(description='当前用户有效权限（0只读 1编辑）')
    status: Literal[0, 1] = Field(description='文件状态（0正常 1归档）')
    can_edit: bool = Field(description='当前是否可编辑')
    path: list[MindmapNodePathItemModel] = Field(description='从根节点到命中节点的路径')
    path_text: str = Field(description='可读节点路径')


class MindmapImportModel(BaseModel):
    """从localStorage导入思维导图模型"""

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True, populate_by_name=True)

    name: str = Field(min_length=1, max_length=MAX_MINDMAP_NAME_LENGTH, description='思维导图名称')
    root: dict[str, Any] = Field(description='节点树（来自localStorage）')
    layout: str | None = Field(default='logicalStructure', description='布局类型')
    theme: dict[str, Any] | None = Field(default=None, description='主题配置')
    view: dict[str, Any] | None = Field(default=None, description='视图状态')
    document_data: dict[str, Any] | None = Field(default=None, description='文档级扩展配置')

    @field_validator('name', mode='before')
    @classmethod
    def normalize_name(cls, value: Any) -> Any:
        return normalize_mindmap_name(value)

    @field_validator('document_data')
    @classmethod
    def validate_document_data_field(cls, value: Any) -> Any:
        return validate_document_data(value)
