"""脑图评论线程与消息表。"""
from datetime import datetime

from sqlalchemy import CHAR, BigInteger, Column, DateTime, Index, SmallInteger, String, Text

from config.database import Base


class MindmapCommentThread(Base):
    """绑定脑图节点的评论线程。"""

    __tablename__ = 'mindmap_comment_thread'
    __table_args__ = (
        Index('idx_mindmap_comment_thread_file', 'mindmap_id', 'status', 'last_comment_time'),
        Index('idx_mindmap_comment_thread_node', 'mindmap_id', 'node_uid', 'status'),
        {'comment': '脑图评论线程表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='评论线程ID')
    mindmap_id = Column(BigInteger, nullable=False, comment='脑图ID')
    node_uid = Column(String(64), nullable=False, comment='节点稳定UID')
    node_text = Column(String(500), nullable=True, comment='创建评论时的节点文本快照')
    status = Column(SmallInteger, nullable=False, server_default='0', comment='0待处理 1已解决')
    created_by = Column(BigInteger, nullable=False, comment='线程创建者用户ID')
    created_time = Column(DateTime, nullable=False, default=datetime.now, comment='创建时间')
    last_comment_time = Column(DateTime, nullable=False, default=datetime.now, comment='最后回复时间')
    resolved_by = Column(BigInteger, nullable=True, comment='解决人用户ID')
    resolved_time = Column(DateTime, nullable=True, comment='解决时间')
    del_flag = Column(CHAR(1), nullable=False, server_default='0', comment='删除标志（0存在 2删除）')


class MindmapComment(Base):
    """评论线程中的消息。"""

    __tablename__ = 'mindmap_comment'
    __table_args__ = {'comment': '脑图评论消息表'}

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='评论消息ID')
    thread_id = Column(BigInteger, nullable=False, comment='评论线程ID')
    mindmap_id = Column(BigInteger, nullable=False, comment='脑图ID')
    content = Column(Text, nullable=False, comment='评论内容')
    created_by = Column(BigInteger, nullable=False, comment='评论人用户ID')
    client_request_id = Column(String(100), nullable=True, comment='客户端写入幂等键')
    created_time = Column(DateTime, nullable=False, default=datetime.now, comment='创建时间')
    update_time = Column(DateTime, nullable=True, comment='更新时间')
    del_flag = Column(CHAR(1), nullable=False, server_default='0', comment='删除标志（0存在 2删除）')


Index('idx_mindmap_comment_thread', MindmapComment.thread_id, MindmapComment.created_time)
Index('idx_mindmap_comment_author', MindmapComment.created_by, MindmapComment.created_time)
Index(
    'uk_mindmap_comment_author_request',
    MindmapComment.created_by,
    MindmapComment.client_request_id,
    unique=True,
)
