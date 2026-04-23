from datetime import datetime
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from pydantic_validation_decorator import NotBlank, Size


class BusinessLineModel(BaseModel):
    """
    业务线表对应pydantic模型
    """

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    line_id: Optional[int] = Field(default=None, description='业务线id')
    parent_id: Optional[int] = Field(default=None, description='父业务线id')
    ancestors: Optional[str] = Field(default=None, description='祖级列表')
    line_code: Optional[str] = Field(default=None, description='业务线编码')
    line_name: Optional[str] = Field(default=None, description='业务线名称')
    order_num: Optional[int] = Field(default=None, description='显示顺序')
    leader: Optional[str] = Field(default=None, description='负责人')
    status: Optional[Literal['0', '1']] = Field(default=None, description='业务线状态（0正常 1停用）')
    del_flag: Optional[Literal['0', '2']] = Field(default=None, description='删除标志（0代表存在 2代表删除）')
    create_by: Optional[str] = Field(default=None, description='创建者')
    create_time: Optional[datetime] = Field(default=None, description='创建时间')
    update_by: Optional[str] = Field(default=None, description='更新者')
    update_time: Optional[datetime] = Field(default=None, description='更新时间')
    remark: Optional[str] = Field(default=None, description='备注')

    @NotBlank(field_name='line_name', message='业务线名称不能为空')
    @Size(field_name='line_name', min_length=0, max_length=30, message='业务线名称长度不能超过30个字符')
    def get_line_name(self) -> Union[str, None]:
        return self.line_name

    @NotBlank(field_name='line_code', message='业务线编码不能为空')
    @Size(field_name='line_code', min_length=0, max_length=50, message='业务线编码长度不能超过50个字符')
    def get_line_code(self) -> Union[str, None]:
        return self.line_code

    @NotBlank(field_name='order_num', message='显示顺序不能为空')
    def get_order_num(self) -> Union[int, None]:
        return self.order_num

    def validate_fields(self) -> None:
        self.get_line_name()
        self.get_line_code()
        self.get_order_num()


class BusinessLineQueryModel(BusinessLineModel):
    """
    业务线管理不分页查询模型
    """

    begin_time: Optional[str] = Field(default=None, description='开始时间')
    end_time: Optional[str] = Field(default=None, description='结束时间')


class BusinessLineTreeModel(BaseModel):
    """
    业务线树模型
    """

    model_config = ConfigDict(alias_generator=to_camel)

    id: int = Field(description='业务线id')
    label: str = Field(description='业务线名称')
    parent_id: int = Field(description='父业务线id')
    children: Optional[list['BusinessLineTreeModel']] = Field(default=None, description='子业务线树')


class DeleteBusinessLineModel(BaseModel):
    """
    删除业务线模型
    """

    model_config = ConfigDict(alias_generator=to_camel)

    line_ids: str = Field(default=None, description='需要删除的业务线id')
    update_by: Optional[str] = Field(default=None, description='更新者')
    update_time: Optional[str] = Field(default=None, description='更新时间')
