"""脑图协作者表"""
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, SmallInteger
from config.database import Base


class MindmapCollaborator(Base):
    """脑图协作者表"""

    __tablename__ = 'mindmap_collaborator'
    __table_args__ = (
        Index('idx_collab_unique', 'mindmap_id', 'user_id', unique=True),
        Index('idx_collab_user', 'user_id'),
        {'comment': '脑图协作者表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='协作者记录ID')
    mindmap_id = Column(BigInteger, nullable=False, comment='脑图ID')
    user_id = Column(BigInteger, nullable=False, comment='协作用户ID')
    permission = Column(SmallInteger, nullable=False, server_default='0', comment='0=查看 1=编辑')
    created_by = Column(BigInteger, nullable=False, comment='添加者用户ID')
    created_time = Column(DateTime, nullable=True, default=datetime.now, comment='创建时间')
