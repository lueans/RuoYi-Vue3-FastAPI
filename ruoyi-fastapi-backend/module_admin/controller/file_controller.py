from typing import Annotated

from fastapi import Depends, File, Query, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.log_annotation import Log
from common.aspect.db_seesion import DBSessionDependency
from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import CurrentUserDependency, PreAuthDependency
from common.enums import BusinessType
from common.router import APIRouterPro
from common.vo import DynamicResponseModel, PageResponseModel, ResponseBaseModel
from module_admin.entity.vo.file_vo import DeleteFileModel, FileModel, FilePageQueryModel
from module_admin.entity.vo.user_vo import CurrentUserModel
from module_admin.service.file_service import FileService
from utils.response_util import ResponseUtil

file_controller = APIRouterPro(
    prefix='/system/file', order_num=100, tags=['系统管理-文件管理'], dependencies=[PreAuthDependency()]
)


@file_controller.get(
    '/list',
    summary='获取文件列表',
    response_model=PageResponseModel[FileModel],
    dependencies=[UserInterfaceAuthDependency('system:file:list')],
)
async def get_file_list(
    request: Request,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    page_param: Annotated[FilePageQueryModel, Query()],
) -> ResponseBaseModel:
    result = await FileService.get_file_list_services(query_db, page_param)
    print(f"result: {result}")
    return ResponseUtil.success(model_content=result)


@file_controller.post(
    '/upload',
    summary='上传文件',
    response_model=DynamicResponseModel[FileModel],
    dependencies=[UserInterfaceAuthDependency('system:file:upload')],
)
@Log(title='文件管理', business_type=BusinessType.INSERT)
async def upload_file(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> ResponseBaseModel:
    result = await FileService.add_file_services(request, file, query_db, current_user)
    return ResponseUtil.success(model_content=result)


@file_controller.delete(
    '/{file_ids}',
    summary='删除文件',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('system:file:remove')],
)
@Log(title='文件管理', business_type=BusinessType.DELETE)
async def delete_file(
    request: Request,
    file_ids: str,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
) -> ResponseBaseModel:
    delete_param = DeleteFileModel(file_ids=file_ids)
    await FileService.delete_file_services(query_db, delete_param)
    return ResponseUtil.success(msg='删除成功')
