from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class FileModel(BaseModel):
    """
    文件表对应pydantic模型
    """
    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    file_id: int | None = Field(default=None, description='文件主键ID')
    file_uuid: str | None = Field(default=None, description='文件业务ID/UUID')
    file_name: str | None = Field(default=None, description='文件名')
    file_path: str | None = Field(default=None, description='文件存储路径/URL')
    file_size: int | None = Field(default=None, description='文件大小（字节）')
    file_suffix: str | None = Field(default=None, description='文件后缀')
    oss_type: int | None = Field(default=None, description='存储类型（0=local, 1=aliyun, 2=minio, 3=qiniu）')
    create_by: int | None = Field(default=None, description='创建者ID')
    create_time: datetime | None = Field(default=None, description='创建时间')
    update_by: str | None = Field(default=None, description='更新者')
    update_time: datetime | None = Field(default=None, description='更新时间')
    remark: str | None = Field(default=None, description='备注')
    del_flag: str | None = Field(default=None, description='删除标志')


class FileQueryModel(FileModel):
    """
    文件管理不分页查询模型
    """
    begin_time: str | None = Field(default=None, description='开始时间')
    end_time: str | None = Field(default=None, description='结束时间')


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
