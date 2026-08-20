"""脑图文件夹表"""
from datetime import datetime

from sqlalchemy import BigInteger, Column, Computed, DateTime, Index, Integer, String
from sqlalchemy.orm import deferred

from config.database import Base


class MindmapFolder(Base):
    """脑图文件夹表"""

    __tablename__ = 'mindmap_folder'
    __table_args__ = (
        Index('idx_folder_owner', 'owner_id', 'del_flag'),
        Index('idx_folder_parent', 'parent_id'),
        Index(
            'uq_mindmap_folder_active_sibling',
            'owner_id',
            'parent_id',
            'active_name',
            unique=True,
        ),
        {'comment': '脑图文件夹表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='文件夹ID')
    name = Column(String(100), nullable=False, comment='文件夹名称')
    parent_id = Column(BigInteger, nullable=False, server_default='0', comment='父文件夹ID（0=顶级）')
    owner_id = Column(BigInteger, nullable=False, comment='所有者用户ID')
    sort_order = Column(Integer, nullable=False, server_default='0', comment='排序序号')
    del_flag = Column(String(1), nullable=False, server_default='0', comment='删除标志（0存在 2删除）')
    # 该生成列只承担数据库唯一索引，不参与业务读取。延迟加载可让应用在
    # 20260818 迁移执行前后的滚动升级窗口内继续读取旧表结构。
    active_name = deferred(
        Column(
            String(100),
            Computed("CASE WHEN del_flag = '0' THEN name ELSE NULL END", persisted=True),
            comment='活动目录唯一名称',
        ),
    )
    create_by = Column(String(64), nullable=True, server_default="''", comment='创建者')
    create_time = Column(DateTime, nullable=True, default=datetime.now, comment='创建时间')
    update_by = Column(String(64), nullable=True, server_default="''", comment='更新者')
    update_time = Column(DateTime, nullable=True, default=datetime.now, comment='更新时间')
