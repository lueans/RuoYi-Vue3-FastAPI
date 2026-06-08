"""脑图协作者 Controller"""
from typing import Annotated

from fastapi import Path, Query, Request, Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.log_annotation import Log
from common.aspect.db_seesion import DBSessionDependency
from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import CurrentUserDependency, PreAuthDependency
from common.enums import BusinessType
from common.router import APIRouterPro
from common.vo import ResponseBaseModel
from module_admin.entity.do.user_do import SysUser
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


@mindmap_collaborator_controller.get(
    '/search-users',
    summary='搜索用户',
    description='根据关键字搜索用户（用于添加协作者）',
    dependencies=[UserInterfaceAuthDependency('mindmap:mindmap:query')],
)
async def search_users(
    request: Request,
    keyword: Annotated[str, Query(description='搜索关键字（用户名/昵称）', min_length=1)],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    """根据用户名或昵称模糊搜索活跃用户，返回最多 20 条结果"""
    # 转义 LIKE 通配符，防止用户注入 % 或 _ 操纵查询
    escaped = keyword.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    like_pattern = f'%{escaped}%'
    stmt = (
        select(
            SysUser.user_id,
            SysUser.user_name,
            SysUser.nick_name,
            SysUser.avatar,
        )
        .where(
            SysUser.status == '0',
            SysUser.del_flag == '0',
            or_(
                SysUser.user_name.ilike(like_pattern),
                SysUser.nick_name.ilike(like_pattern),
            ),
        )
        .limit(20)
    )
    result = await query_db.execute(stmt)
    users = [
        {
            'userId': row.user_id,
            'userName': row.user_name,
            'nickName': row.nick_name,
            'avatar': row.avatar,
        }
        for row in result.all()
    ]
    return ResponseUtil.success(data=users)
