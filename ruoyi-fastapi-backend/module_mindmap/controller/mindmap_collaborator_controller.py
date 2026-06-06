"""脑图协作者 Controller"""
from typing import Annotated

from fastapi import Path, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.log_annotation import Log
from common.aspect.db_seesion import DBSessionDependency
from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import CurrentUserDependency, PreAuthDependency
from common.enums import BusinessType
from common.router import APIRouterPro
from common.vo import ResponseBaseModel
from module_admin.entity.vo.user_vo import CurrentUserModel
from module_mindmap.entity.vo.mindmap_collaborator_vo import (
    MindmapCollaboratorAddModel,
    MindmapCollaboratorUpdateModel,
)
from module_mindmap.service.mindmap_collaborator_service import MindmapCollaboratorService
from utils.log_util import logger
from utils.response_util import ResponseUtil

mindmap_collaborator_controller = APIRouterPro(
    prefix='/mindmap/collaborator',
    order_num=23,
    tags=['脑图协作者'],
    dependencies=[PreAuthDependency()],
)


@mindmap_collaborator_controller.post(
    '',
    summary='添加协作者',
    description='为脑图添加一个协作者',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:mindmap:edit')],
)
@Log(title='脑图协作者', business_type=BusinessType.INSERT)
async def add_collaborator(
    request: Request,
    add_model: MindmapCollaboratorAddModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapCollaboratorService.add_collaborator(
        query_db, add_model, current_user.user.user_id,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


@mindmap_collaborator_controller.get(
    '/list/{mindmap_id}',
    summary='获取协作者列表',
    description='获取脑图的所有协作者',
    dependencies=[UserInterfaceAuthDependency('mindmap:mindmap:query')],
)
async def get_collaborator_list(
    request: Request,
    mindmap_id: Annotated[int, Path(description='脑图ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapCollaboratorService.get_collaborator_list(
        query_db, mindmap_id, current_user.user.user_id,
    )
    return ResponseUtil.success(data=[r.model_dump(by_alias=True) for r in result])


@mindmap_collaborator_controller.put(
    '',
    summary='修改协作者权限',
    description='修改协作者的权限级别',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:mindmap:edit')],
)
@Log(title='脑图协作者', business_type=BusinessType.UPDATE)
async def update_collaborator_permission(
    request: Request,
    update_model: MindmapCollaboratorUpdateModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapCollaboratorService.update_permission(
        query_db, update_model, current_user.user.user_id,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


@mindmap_collaborator_controller.delete(
    '/{collab_id}',
    summary='移除协作者',
    description='移除指定的协作者',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:mindmap:edit')],
)
@Log(title='脑图协作者', business_type=BusinessType.DELETE)
async def remove_collaborator(
    request: Request,
    collab_id: Annotated[int, Path(description='协作者记录ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapCollaboratorService.remove_collaborator(
        query_db, collab_id, current_user.user.user_id,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)
