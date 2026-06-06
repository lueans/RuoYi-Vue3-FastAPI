"""脑图 Yjs 文档持久化状态模型"""
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime
from sqlalchemy.dialects import mysql, postgresql

from config.database import Base
from config.env import DataBaseConfig


class MindmapWsState(Base):
    __tablename__ = 'mindmap_ws_state'
    __table_args__ = ({'comment': '脑图Yjs文档持久化状态表'},)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    mindmap_id = Column(BigInteger, nullable=False, unique=True, comment='脑图ID')
    yjs_state = Column(
        mysql.MEDIUMBLOB if DataBaseConfig.db_type == 'mysql' else postgresql.BYTEA,
        nullable=True,
        comment='Yjs文档二进制状态',
    )
    updated_at = Column(
        DateTime, nullable=True, default=datetime.now, onupdate=datetime.now, comment='更新时间'
    )
