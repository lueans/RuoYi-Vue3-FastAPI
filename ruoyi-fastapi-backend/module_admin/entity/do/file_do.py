from sqlalchemy import BigInteger, Column, DateTime, Integer, String
from config.database import Base

class SysFile(Base):
    """
    文件管理表
    """

    __tablename__ = 'sys_file'
    __table_args__ = {'comment': '文件管理表'}

    file_id = Column(BigInteger, primary_key=True, autoincrement=True, comment='文件主键ID')
    file_uuid = Column(String(128), default=None, unique=True, comment='文件业务ID/UUID')
    file_name = Column(String(255), default=None, comment='文件名')
    file_path = Column(String(1024), default=None, comment='文件存储路径/URL')
    file_size = Column(BigInteger, default=None, comment='文件大小（字节）')
    file_suffix = Column(String(32), default=None, comment='文件后缀')
    oss_type = Column(Integer, default=0, comment='存储类型（0=local, 1=aliyun, 2=minio, 3=qiniu）')
    create_by = Column(BigInteger, default=None, comment='创建者ID')
    create_time = Column(DateTime, default=None, comment='创建时间')
    update_by = Column(String(64), default=None, comment='更新者')
    update_time = Column(DateTime, default=None, comment='更新时间')
    remark = Column(String(500), default=None, comment='备注')
    del_flag = Column(String(1), default='0', comment='删除标志（0代表存在，2代表删除）')
