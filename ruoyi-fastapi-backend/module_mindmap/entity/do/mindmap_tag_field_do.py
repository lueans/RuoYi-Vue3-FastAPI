"""脑图标签字段与选项表"""
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String
from sqlalchemy.dialects import mysql, postgresql

from config.database import Base, DataBaseConfig

# JSON 类型兼容 MySQL + PostgreSQL
JSON_TYPE = mysql.JSON if DataBaseConfig.db_type == 'mysql' else postgresql.JSONB


class MindmapTagField(Base):
    """脑图标签字段表"""

    __tablename__ = 'mindmap_tag_field'
    __table_args__ = (
        Index('idx_tag_field_owner_key', 'owner_id', 'field_key', unique=True),
        Index('idx_tag_field_owner', 'owner_id'),
        {'comment': '脑图标签字段表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='字段ID')
    field_key = Column(String(100), nullable=False, comment='字段key(英文/数字/下划线)')
    name = Column(String(100), nullable=False, comment='字段显示名称')
    select_mode = Column(String(10), nullable=False, server_default='single', comment='选择模式: single/multi')
    style = Column(JSON_TYPE, nullable=True, comment='基础样式 {fontSize,radius,paddingX,placement,align}')
    owner_id = Column(BigInteger, nullable=False, server_default='0', comment='所有者(0=全局)')
    sort_order = Column(Integer, nullable=True, server_default='0', comment='排序')
    description = Column(String(500), nullable=True, comment='字段描述')
    created_by = Column(String(64), nullable=True, comment='创建人')
    created_time = Column(DateTime, nullable=True, default=datetime.now, comment='创建时间')
    updated_time = Column(DateTime, nullable=True, default=datetime.now, onupdate=datetime.now, comment='更新时间')


class MindmapTagFieldOption(Base):
    """脑图标签字段选项表"""

    __tablename__ = 'mindmap_tag_field_option'
    __table_args__ = (
        Index('idx_tag_option_field_key', 'field_id', 'option_key', unique=True),
        Index('idx_tag_option_field', 'field_id'),
        {'comment': '脑图标签字段选项表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='选项ID')
    field_id = Column(BigInteger, nullable=False, comment='所属字段ID')
    tag_id = Column(BigInteger, nullable=True, comment='关联的统一标签ID')
    option_key = Column(String(100), nullable=False, comment='选项key(字段内唯一)')
    name = Column(String(200), nullable=False, comment='选项显示名称')
    fill = Column(String(20), nullable=True, comment='背景色')
    color = Column(String(20), nullable=True, comment='文字色')
    sort_order = Column(Integer, nullable=True, server_default='0', comment='排序')
    created_time = Column(DateTime, nullable=True, default=datetime.now, comment='创建时间')
