"""脑图评论接口模型。"""
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

MAX_COMMENT_CONTENT_LENGTH = 2000


class _CommentContentModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    content: str = Field(min_length=1, max_length=MAX_COMMENT_CONTENT_LENGTH, description='纯文本评论内容')

    @field_validator('content')
    @classmethod
    def validate_content(cls, value: str) -> str:
        normalized = value.replace('\r\n', '\n').replace('\r', '\n').strip()
        if not normalized:
            raise ValueError('评论内容不能为空')
        if len(normalized) > MAX_COMMENT_CONTENT_LENGTH:
            raise ValueError('评论内容不能超过2000个字符')
        return normalized


class MindmapCommentCreateModel(_CommentContentModel):
    """创建节点评论线程。"""

    mindmap_id: int = Field(gt=0, description='脑图ID')
    node_uid: str = Field(min_length=1, max_length=64, description='节点稳定UID')

    @field_validator('node_uid')
    @classmethod
    def validate_node_uid(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError('节点UID不能为空')
        return normalized


class MindmapCommentReplyModel(_CommentContentModel):
    """回复评论线程。"""


class MindmapCommentStatusModel(BaseModel):
    """解决或重新打开评论线程。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    resolved: bool = Field(description='是否已解决')
