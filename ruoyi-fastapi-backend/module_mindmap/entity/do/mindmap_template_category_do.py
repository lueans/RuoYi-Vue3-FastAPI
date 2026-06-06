"""脑图模板分类表"""
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Integer, String

from config.database import Base


class MindmapTemplateCategory(Base):
    """脑图模板分类表"""

    __tablename__ = 'mindmap_template_category'
    __table_args__ = ({'comment': '脑图模板分类表'},)

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='分类ID')
    name = Column(String(100), nullable=False, comment='分类名称')
    sort_order = Column(Integer, nullable=True, server_default='0', comment='排序')
    created_time = Column(DateTime, nullable=True, default=datetime.now, comment='创建时间')
