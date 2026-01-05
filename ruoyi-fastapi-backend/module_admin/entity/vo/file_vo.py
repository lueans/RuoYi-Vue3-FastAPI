from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class FileModel(BaseModel):
    """
    文件表对应pydantic模型
    """
    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    file_id: Optional[int] = Field(default=None, description='文件主键ID')
    file_uuid: Optional[str] = Field(default=None, description='文件业务ID/UUID')
    file_name: Optional[str] = Field(default=None, description='文件名')
    file_path: Optional[str] = Field(default=None, description='文件存储路径/URL')
    file_size: Optional[int] = Field(default=None, description='文件大小（字节）')
    file_suffix: Optional[str] = Field(default=None, description='文件后缀')
    oss_type: Optional[int] = Field(default=None, description='存储类型（0=local, 1=aliyun, 2=minio, 3=qiniu）')
    create_by: Optional[int] = Field(default=None, description='创建者ID')
    create_time: Optional[datetime] = Field(default=None, description='创建时间')
    update_by: Optional[str] = Field(default=None, description='更新者')
    update_time: Optional[datetime] = Field(default=None, description='更新时间')
    remark: Optional[str] = Field(default=None, description='备注')
    del_flag: Optional[str] = Field(default=None, description='删除标志')


class FileQueryModel(FileModel):
    """
    文件管理不分页查询模型
    """
    begin_time: Optional[str] = Field(default=None, description='开始时间')
    end_time: Optional[str] = Field(default=None, description='结束时间')


class FilePageQueryModel(FileQueryModel):
    """
    文件管理分页查询模型
    """
    page_num: int = Field(default=1, description='当前页码')
    page_size: int = Field(default=10, description='每页记录数')


class DeleteFileModel(BaseModel):
    """
    删除文件模型
    """
    file_ids: str = Field(description='需要删除的文件ID，多个以逗号分隔')
