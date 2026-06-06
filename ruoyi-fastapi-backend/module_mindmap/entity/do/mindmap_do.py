from datetime import datetime
from sqlalchemy import BigInteger, CHAR, Column, DateTime, Index, Integer, SmallInteger, String, Text
from sqlalchemy.dialects import mysql, postgresql
from config.database import Base
from config.env import DataBaseConfig
from utils.common_util import SqlalchemyUtil


class Mindmap(Base):
    """
    思维导图主表
    """

    __tablename__ = 'mindmap'
    __table_args__ = (
        Index('idx_mindmap_owner', 'owner_id', 'del_flag'),
        Index('idx_mindmap_name', 'name'),
        {'comment': '思维导图主表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='思维导图ID')
    name = Column(String(200), nullable=False, comment='思维导图名称')
    description = Column(String(500), nullable=True, server_default=SqlalchemyUtil.get_server_default_null(DataBaseConfig.db_type), comment='描述')
    owner_id = Column(BigInteger, nullable=False, comment='所有者用户ID')
    layout = Column(String(50), nullable=False, server_default='logicalStructure', comment='布局类型')
    theme = Column(
        mysql.JSON if DataBaseConfig.db_type == 'mysql' else postgresql.JSONB,
        nullable=True, comment='主题配置JSON {template, config}',
    )
    node_tree = Column(
        mysql.LONGTEXT if DataBaseConfig.db_type == 'mysql' else Text,
        nullable=False, comment='完整节点树JSON',
    )
    view_data = Column(
        mysql.JSON if DataBaseConfig.db_type == 'mysql' else postgresql.JSONB,
        nullable=True, comment='视图状态JSON {transform, state}',
    )
    cover_image = Column(String(500), nullable=True, server_default=SqlalchemyUtil.get_server_default_null(DataBaseConfig.db_type), comment='封面图片URL')
    is_template = Column(SmallInteger, nullable=False, server_default='0', comment='是否模板（0否 1是）')
    last_version_id = Column(BigInteger, nullable=True, server_default=SqlalchemyUtil.get_server_default_null(DataBaseConfig.db_type), comment='最新版本ID')
    version_count = Column(Integer, nullable=False, server_default='1', comment='版本总数')
    status = Column(SmallInteger, nullable=False, server_default='0', comment='状态（0正常 1归档）')
    del_flag = Column(CHAR(1), nullable=False, server_default='0', comment='删除标志（0存在 2删除）')
    create_by = Column(String(64), nullable=True, server_default="''", comment='创建者')
    create_time = Column(DateTime, nullable=True, default=datetime.now(), comment='创建时间')
    update_by = Column(String(64), nullable=True, server_default="''", comment='更新者')
    update_time = Column(DateTime, nullable=True, default=datetime.now(), comment='更新时间')
    remark = Column(String(500), nullable=True, server_default=SqlalchemyUtil.get_server_default_null(DataBaseConfig.db_type), comment='备注')
