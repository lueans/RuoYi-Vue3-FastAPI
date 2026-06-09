"""脑图标签与标签分类表"""
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String
from sqlalchemy.dialects import mysql, postgresql

from config.database import Base, DataBaseConfig

# JSON 类型兼容 MySQL + PostgreSQL
JSON_TYPE = mysql.JSON if DataBaseConfig.db_type == 'mysql' else postgresql.JSONB


class MindmapTagCategory(Base):
    """脑图标签分类表"""

    __tablename__ = 'mindmap_tag_category'
    __table_args__ = (
        Index('idx_tag_cat_owner', 'owner_id'),
        {'comment': '脑图标签分类表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='分类ID')
    name = Column(String(100), nullable=False, comment='分类名称')
    owner_id = Column(BigInteger, nullable=False, server_default='0', comment='所有者(0=全局)')
    sort_order = Column(Integer, nullable=True, server_default='0', comment='排序')
    created_by = Column(String(64), nullable=True, comment='创建人')
    created_time = Column(DateTime, nullable=True, default=datetime.now, comment='创建时间')


class MindmapTag(Base):
    """脑图标签表"""

    __tablename__ = 'mindmap_tag'
    __table_args__ = (
        Index('idx_tag_owner_key', 'owner_id', 'tag_key', unique=True),
        Index('idx_tag_category', 'category_id'),
        Index('idx_tag_uuid', 'uuid', unique=True),
        {'comment': '脑图标签表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='标签ID')
    uuid = Column(String(36), nullable=False, comment='UUID(自动生成)')
    tag_key = Column(String(100), nullable=False, comment='标签key(自定义必填)')
    name = Column(String(200), nullable=False, comment='标签显示名称')
    category_id = Column(BigInteger, nullable=True, comment='所属分类ID')
    owner_id = Column(BigInteger, nullable=False, server_default='0', comment='所有者(0=全局)')
    style = Column(JSON_TYPE, nullable=True, comment='标签样式JSON {fill,color,fontSize,radius}')
    description = Column(String(500), nullable=True, comment='标签描述')
    created_by = Column(String(64), nullable=True, comment='创建人')
    created_time = Column(DateTime, nullable=True, default=datetime.now, comment='创建时间')
    updated_time = Column(DateTime, nullable=True, default=datetime.now, onupdate=datetime.now, comment='更新时间')
