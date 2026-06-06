"""脑图分享链接表"""
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, SmallInteger, String

from config.database import Base


class MindmapShare(Base):
    """脑图分享链接表"""

    __tablename__ = 'mindmap_share'
    __table_args__ = (
        Index('idx_share_token', 'share_token'),
        Index('idx_share_mindmap', 'mindmap_id'),
        {'comment': '脑图分享链接表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='分享ID')
    mindmap_id = Column(BigInteger, nullable=False, comment='脑图ID')
    share_token = Column(String(64), nullable=False, unique=True, comment='分享token')
    share_type = Column(SmallInteger, nullable=False, server_default='0', comment='0=查看 1=编辑')
    expire_time = Column(DateTime, nullable=True, comment='过期时间（NULL=永久）')
    created_by = Column(BigInteger, nullable=False, comment='创建者用户ID')
    created_time = Column(DateTime, nullable=True, default=datetime.now, comment='创建时间')
    is_active = Column(SmallInteger, nullable=False, server_default='1', comment='是否有效')
