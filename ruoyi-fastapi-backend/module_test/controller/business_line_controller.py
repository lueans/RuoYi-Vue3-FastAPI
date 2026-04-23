from datetime import datetime
from typing import Annotated

from fastapi import Path, Query, Request, Response
from pydantic_validation_decorator import ValidateFields
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.log_annotation import Log
from common.aspect.db_seesion import DBSessionDependency
from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import CurrentUserDependency, PreAuthDependency
from common.enums import BusinessType
from common.router import APIRouterPro
from common.vo import DataResponseModel, ResponseBaseModel
from module_test.entity.vo.business_line_vo import (
    BusinessLineModel,
    BusinessLineQueryModel,
    DeleteBusinessLineModel,
)
from module_admin.entity.vo.user_vo import CurrentUserModel
from module_test.service.business_line_service import BusinessLineService
from utils.log_util import logger
from utils.response_util import ResponseUtil

business_line_controller = APIRouterPro(
    prefix='/test/businessLine',
    order_num=1,
    tags=['测试管理-业务线管理'],
    dependencies=[PreAuthDependency()],
)


@business_line_controller.get(
    '/list/exclude/{line_id}',
    summary='获取编辑业务线的下拉树接口',
    response_model=DataResponseModel[list[BusinessLineModel]],
    dependencies=[UserInterfaceAuthDependency('test:businessLine:list')],
)
async def get_business_line_tree_for_edit_option(
    request: Request,
    line_id: Annotated[int, Path(description='业务线id')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    query = BusinessLineModel(lineId=line_id)
    query_result = await BusinessLineService.get_business_line_for_edit_option_services(query_db, query)
    logger.info('获取成功')

    return ResponseUtil.success(data=query_result)


@business_line_controller.get(
    '/list',
    summary='获取业务线列表接口',
    response_model=DataResponseModel[list[BusinessLineModel]],
    dependencies=[UserInterfaceAuthDependency('test:businessLine:list')],
)
async def get_business_line_list(
    request: Request,
    query: Annotated[BusinessLineQueryModel, Query()],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    query_result = await BusinessLineService.get_business_line_list_services(query_db, query)
    logger.info('获取成功')

    return ResponseUtil.success(data=query_result)


@business_line_controller.post(
    '',
    summary='新增业务线接口',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('test:businessLine:add')],
)
@ValidateFields(validate_model='add_business_line')
@Log(title='业务线管理', business_type=BusinessType.INSERT)
async def add_business_line(
    request: Request,
    add_business_line: BusinessLineModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    add_business_line.create_by = current_user.user.user_name
    add_business_line.create_time = datetime.now()
    add_business_line.update_by = current_user.user.user_name
    add_business_line.update_time = datetime.now()
    result = await BusinessLineService.add_business_line_services(query_db, add_business_line)
    logger.info(result.message)

    return ResponseUtil.success(msg=result.message)


@business_line_controller.put(
    '',
    summary='编辑业务线接口',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('test:businessLine:edit')],
)
@ValidateFields(validate_model='edit_business_line')
@Log(title='业务线管理', business_type=BusinessType.UPDATE)
async def edit_business_line(
    request: Request,
    edit_business_line: BusinessLineModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    edit_business_line.update_by = current_user.user.user_name
    edit_business_line.update_time = datetime.now()
    result = await BusinessLineService.edit_business_line_services(query_db, edit_business_line)
    logger.info(result.message)

    return ResponseUtil.success(msg=result.message)


@business_line_controller.delete(
    '/{line_ids}',
    summary='删除业务线接口',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('test:businessLine:remove')],
)
@Log(title='业务线管理', business_type=BusinessType.DELETE)
async def delete_business_line(
    request: Request,
    line_ids: Annotated[str, Path(description='需要删除的业务线id')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    delete_model = DeleteBusinessLineModel(lineIds=line_ids)
    delete_model.update_by = current_user.user.user_name
    delete_model.update_time = datetime.now()
    result = await BusinessLineService.delete_business_line_services(query_db, delete_model)
    logger.info(result.message)

    return ResponseUtil.success(msg=result.message)


@business_line_controller.get(
    '/{line_id}',
    summary='获取业务线详情接口',
    response_model=DataResponseModel[BusinessLineModel],
    dependencies=[UserInterfaceAuthDependency('test:businessLine:query')],
)
async def query_detail_business_line(
    request: Request,
    line_id: Annotated[int, Path(description='业务线id')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    result = await BusinessLineService.business_line_detail_services(query_db, line_id)
    logger.info(f'获取line_id为{line_id}的信息成功')

    return ResponseUtil.success(data=result)
