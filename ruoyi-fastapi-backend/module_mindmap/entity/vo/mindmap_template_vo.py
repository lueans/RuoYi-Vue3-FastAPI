"""脑图模板 Pydantic 模型"""
from datetime import datetime
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

MAX_TEMPLATE_NAME_LENGTH = 200
MAX_TEMPLATE_DESCRIPTION_LENGTH = 500
MAX_TEMPLATE_COVER_URL_LENGTH = 500
MAX_TEMPLATE_CATEGORY_NAME_LENGTH = 100
ASCII_CONTROL_END = 32
ASCII_DELETE = 127


def normalize_template_text(value: object, *, allow_empty: bool = False) -> str | None:
    """Normalize single-line template text and reject hidden control characters."""
    if value is None:
        return None if allow_empty else ''
    normalized = str(value).strip()
    if not normalized and allow_empty:
        return None
    if any(ord(char) < ASCII_CONTROL_END or ord(char) == ASCII_DELETE for char in normalized):
        raise ValueError('内容不能包含控制字符')
    return normalized


def normalize_template_cover_url(value: object) -> str | None:
    """Allow only persistent HTTP(S) or same-origin relative cover URLs."""
    normalized = normalize_template_text(value, allow_empty=True)
    if normalized is None:
        return None
    if len(normalized) > MAX_TEMPLATE_COVER_URL_LENGTH:
        raise ValueError(f'封面地址不能超过 {MAX_TEMPLATE_COVER_URL_LENGTH} 个字符')
    if normalized.startswith('/') and not normalized.startswith('//'):
        return normalized
    parsed = urlsplit(normalized)
    if not parsed.scheme and not parsed.netloc:
        return normalized
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        raise ValueError('封面地址仅支持 HTTP、HTTPS 或同源相对路径')
    if parsed.username or parsed.password:
        raise ValueError('封面地址不能包含账号或密码')
    return normalized


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

    mindmap_id: int = Field(gt=0, description='源脑图ID（将复制为模板）')
    name: str = Field(min_length=1, max_length=MAX_TEMPLATE_NAME_LENGTH, description='模板名称')
    description: str | None = Field(
        default=None,
        max_length=MAX_TEMPLATE_DESCRIPTION_LENGTH,
        description='模板描述',
    )
    cover_image: str | None = Field(
        default=None,
        max_length=MAX_TEMPLATE_COVER_URL_LENGTH,
        description='封面图URL',
    )
    template_category_id: int | None = Field(default=None, gt=0, description='分类ID')

    @field_validator('name', mode='before')
    @classmethod
    def validate_name(cls, value: object) -> str:
        return normalize_template_text(value) or ''

    @field_validator('description', mode='before')
    @classmethod
    def validate_description(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator('cover_image', mode='before')
    @classmethod
    def validate_cover_image(cls, value: object) -> str | None:
        return normalize_template_cover_url(value)


class MindmapTemplateQueryModel(BaseModel):
    """模板查询模型"""
    model_config = ConfigDict(alias_generator=to_camel)

    category_id: int | None = Field(default=None, gt=0, description='分类ID筛选')
    keyword: str | None = Field(default=None, max_length=MAX_TEMPLATE_NAME_LENGTH, description='关键词搜索')
    page_num: int = Field(default=1, ge=1, description='页码')
    page_size: int = Field(default=20, ge=1, le=100, description='每页数量')

    @field_validator('keyword', mode='before')
    @classmethod
    def validate_keyword(cls, value: object) -> str | None:
        return normalize_template_text(value, allow_empty=True)
