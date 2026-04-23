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
from module_test.entity.vo.case_dir_vo import CaseDirModel, CaseDirQueryModel, DeleteCaseDirModel
from module_admin.entity.vo.user_vo import CurrentUserModel
from module_test.service.case_dir_service import CaseDirService
from utils.log_util import logger
from utils.response_util import ResponseUtil

case_dir_controller = APIRouterPro(
    prefix='/test/caseDir',
    order_num=2,
    tags=['测试管理-用例目录管理'],
    dependencies=[PreAuthDependency()],
)


@case_dir_controller.get(
    '/list/exclude/{dir_id}',
    summary='获取编辑目录的下拉树接口',
    response_model=DataResponseModel[list[CaseDirModel]],
    dependencies=[UserInterfaceAuthDependency('test:caseDir:list')],
)
async def get_case_dir_tree_for_edit_option(
    request: Request,
    dir_id: Annotated[int, Path(description='目录id')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    query = CaseDirModel(dirId=dir_id)
    query_result = await CaseDirService.get_case_dir_for_edit_option_services(query_db, query)
    logger.info('获取成功')
    return ResponseUtil.success(data=query_result)


@case_dir_controller.get(
    '/list',
    summary='获取目录列表接口',
    response_model=DataResponseModel[list[CaseDirModel]],
    dependencies=[UserInterfaceAuthDependency('test:caseDir:list')],
)
async def get_case_dir_list(
    request: Request,
    query: Annotated[CaseDirQueryModel, Query()],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    query_result = await CaseDirService.get_case_dir_list_services(query_db, query)
    logger.info('获取成功')
    return ResponseUtil.success(data=query_result)


@case_dir_controller.post(
    '',
    summary='新增目录接口',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('test:caseDir:add')],
)
@ValidateFields(validate_model='add_case_dir')
@Log(title='用例目录管理', business_type=BusinessType.INSERT)
async def add_case_dir(
    request: Request,
    add_case_dir: CaseDirModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    add_case_dir.create_by = current_user.user.user_name
    add_case_dir.create_time = datetime.now()
    add_case_dir.update_by = current_user.user.user_name
    add_case_dir.update_time = datetime.now()
    result = await CaseDirService.add_case_dir_services(query_db, add_case_dir)
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


@case_dir_controller.put(
    '',
    summary='编辑目录接口',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('test:caseDir:edit')],
)
@ValidateFields(validate_model='edit_case_dir')
@Log(title='用例目录管理', business_type=BusinessType.UPDATE)
async def edit_case_dir(
    request: Request,
    edit_case_dir: CaseDirModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    edit_case_dir.update_by = current_user.user.user_name
    edit_case_dir.update_time = datetime.now()
    result = await CaseDirService.edit_case_dir_services(query_db, edit_case_dir)
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


@case_dir_controller.delete(
    '/{dir_ids}',
    summary='删除目录接口',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('test:caseDir:remove')],
)
@Log(title='用例目录管理', business_type=BusinessType.DELETE)
async def delete_case_dir(
    request: Request,
    dir_ids: Annotated[str, Path(description='需要删除的目录id')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    delete_model = DeleteCaseDirModel(dirIds=dir_ids)
    delete_model.update_by = current_user.user.user_name
    delete_model.update_time = datetime.now()
    result = await CaseDirService.delete_case_dir_services(query_db, delete_model)
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


@case_dir_controller.get(
    '/{dir_id}',
    summary='获取目录详情接口',
    response_model=DataResponseModel[CaseDirModel],
    dependencies=[UserInterfaceAuthDependency('test:caseDir:query')],
)
async def query_detail_case_dir(
    request: Request,
    dir_id: Annotated[int, Path(description='目录id')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    result = await CaseDirService.case_dir_detail_services(query_db, dir_id)
    logger.info(f'获取dir_id为{dir_id}的信息成功')
    return ResponseUtil.success(data=result)
