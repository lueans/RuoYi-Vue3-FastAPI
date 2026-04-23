from datetime import datetime

from sqlalchemy import CHAR, BigInteger, Column, DateTime, Integer, String

from config.database import Base


class TestCaseDir(Base):
    """
    用例目录表
    """

    __tablename__ = 'test_case_dir'
    __table_args__ = {'comment': '用例目录表'}

    dir_id = Column(BigInteger, primary_key=True, autoincrement=True, comment='目录ID')
    parent_id = Column(BigInteger, server_default='0', comment='父目录ID')
    ancestors = Column(String(200), nullable=True, server_default="''", comment='祖级列表')
    dir_name = Column(String(100), nullable=True, server_default="''", comment='目录名称')
    order_num = Column(Integer, server_default='0', comment='显示顺序')
    status = Column(CHAR(1), nullable=True, server_default='0', comment='状态（0正常 1停用）')
    del_flag = Column(CHAR(1), nullable=True, server_default='0', comment='删除标志（0代表存在 2代表删除）')
    create_by = Column(String(64), nullable=True, server_default="''", comment='创建者')
    create_time = Column(DateTime, nullable=True, default=datetime.now(), comment='创建时间')
    update_by = Column(String(64), nullable=True, server_default="''", comment='更新者')
    update_time = Column(DateTime, nullable=True, default=datetime.now(), comment='更新时间')
    remark = Column(String(500), nullable=True, server_default="''", comment='备注')
