from datetime import datetime

from sqlalchemy import CHAR, BigInteger, Column, DateTime, Integer, String

from config.database import Base
from config.env import DataBaseConfig
from utils.common_util import SqlalchemyUtil


class TestBusinessLine(Base):
    """
    业务线表
    """

    __tablename__ = 'test_business_line'
    __table_args__ = {'comment': '业务线表'}

    line_id = Column(BigInteger, primary_key=True, autoincrement=True, comment='业务线id')
    parent_id = Column(BigInteger, server_default='0', comment='父业务线id')
    ancestors = Column(String(50), nullable=True, server_default="''", comment='祖级列表')
    line_code = Column(String(50), nullable=True, server_default="''", comment='业务线编码')
    line_name = Column(String(30), nullable=True, server_default="''", comment='业务线名称')
    order_num = Column(Integer, server_default='0', comment='显示顺序')
    leader = Column(
        String(20),
        nullable=True,
        server_default=SqlalchemyUtil.get_server_default_null(DataBaseConfig.db_type),
        comment='负责人',
    )
    status = Column(CHAR(1), nullable=True, server_default='0', comment='业务线状态（0正常 1停用）')
    del_flag = Column(CHAR(1), nullable=True, server_default='0', comment='删除标志（0代表存在 2代表删除）')
    create_by = Column(String(64), nullable=True, server_default="''", comment='创建者')
    create_time = Column(DateTime, nullable=True, default=datetime.now(), comment='创建时间')
    update_by = Column(String(64), nullable=True, server_default="''", comment='更新者')
    update_time = Column(DateTime, nullable=True, default=datetime.now(), comment='更新时间')
    remark = Column(String(500), nullable=True, server_default="''", comment='备注')
