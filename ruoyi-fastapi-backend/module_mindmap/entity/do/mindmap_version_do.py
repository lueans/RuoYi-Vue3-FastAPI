"""脑图版本历史表"""
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, SmallInteger, String, Text
from sqlalchemy.dialects import mysql, postgresql

from config.database import Base
from config.env import DataBaseConfig


class MindmapVersion(Base):
    """脑图版本历史表"""

    __tablename__ = 'mindmap_version'
    __table_args__ = (
        Index('idx_version_mindmap', 'mindmap_id', 'version_type'),
        Index('idx_version_time', 'mindmap_id', 'created_time'),
        {'comment': '脑图版本历史表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='版本ID')
    mindmap_id = Column(BigInteger, nullable=False, comment='脑图ID')
    version_number = Column(Integer, nullable=False, comment='版本号')
    version_type = Column(
        SmallInteger, nullable=False, server_default='0',
        comment='版本类型: 0=草稿 1=正式',
    )
    name = Column(String(200), nullable=True, comment='版本名称（仅正式版本）')
    node_tree = Column(
        mysql.LONGTEXT if DataBaseConfig.db_type == 'mysql' else Text,
        nullable=False,
        comment='节点树快照JSON',
    )
    view_data = Column(
        mysql.JSON if DataBaseConfig.db_type == 'mysql' else postgresql.JSONB,
        nullable=True,
        comment='视图状态快照',
    )
    layout = Column(String(50), nullable=True, comment='布局类型')
    theme = Column(
        mysql.JSON if DataBaseConfig.db_type == 'mysql' else postgresql.JSONB,
        nullable=True,
        comment='主题配置',
    )
    snapshot_schema_version = Column(Integer, nullable=False, server_default='1', comment='版本快照结构版本')
    tag_snapshots = Column(
        mysql.JSON if DataBaseConfig.db_type == 'mysql' else postgresql.JSONB,
        nullable=True,
        comment='版本创建时引用标签的不可变定义快照',
    )
    created_by = Column(String(64), nullable=False, comment='创建者')
    created_time = Column(DateTime, nullable=True, default=datetime.now, comment='创建时间')
