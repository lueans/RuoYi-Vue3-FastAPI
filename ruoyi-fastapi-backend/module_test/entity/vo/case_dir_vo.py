from datetime import datetime
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from pydantic_validation_decorator import NotBlank, Size


class CaseDirModel(BaseModel):
    """
    用例目录表对应pydantic模型
    """

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    dir_id: Optional[int] = Field(default=None, description='目录ID')
    parent_id: Optional[int] = Field(default=None, description='父目录ID')
    ancestors: Optional[str] = Field(default=None, description='祖级列表')
    dir_name: Optional[str] = Field(default=None, description='目录名称')
    order_num: Optional[int] = Field(default=None, description='显示顺序')
    status: Optional[Literal['0', '1']] = Field(default=None, description='状态（0正常 1停用）')
    del_flag: Optional[Literal['0', '2']] = Field(default=None, description='删除标志（0代表存在 2代表删除）')
    create_by: Optional[str] = Field(default=None, description='创建者')
    create_time: Optional[datetime] = Field(default=None, description='创建时间')
    update_by: Optional[str] = Field(default=None, description='更新者')
    update_time: Optional[datetime] = Field(default=None, description='更新时间')
    remark: Optional[str] = Field(default=None, description='备注')

    @NotBlank(field_name='dir_name', message='目录名称不能为空')
    @Size(field_name='dir_name', min_length=0, max_length=100, message='目录名称长度不能超过100个字符')
    def get_dir_name(self) -> Union[str, None]:
        return self.dir_name

    def validate_fields(self) -> None:
        self.get_dir_name()


class CaseDirQueryModel(CaseDirModel):
    """
    用例目录不分页查询模型
    """

    begin_time: Optional[str] = Field(default=None, description='开始时间')
    end_time: Optional[str] = Field(default=None, description='结束时间')


class CaseDirTreeModel(BaseModel):
    """
    用例目录树模型
    """

    model_config = ConfigDict(alias_generator=to_camel)

    id: int = Field(description='目录ID')
    label: str = Field(description='目录名称')
    parent_id: int = Field(description='父目录ID')
    children: Optional[list['CaseDirTreeModel']] = Field(default=None, description='子目录树')


class DeleteCaseDirModel(BaseModel):
    """
    删除用例目录模型
    """

    model_config = ConfigDict(alias_generator=to_camel)

    dir_ids: str = Field(default=None, description='需要删除的目录ID')
    update_by: Optional[str] = Field(default=None, description='更新者')
    update_time: Optional[str] = Field(default=None, description='更新时间')
