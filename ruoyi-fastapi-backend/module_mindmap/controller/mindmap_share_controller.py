"""脑图分享链接 Controller"""
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
from module_mindmap.entity.vo.mindmap_share_vo import MindmapShareCreateModel
from module_mindmap.service.mindmap_share_service import MindmapShareService
from utils.log_util import logger
from utils.response_util import ResponseUtil

mindmap_share_controller = APIRouterPro(
    prefix='/mindmap/share',
    order_num=22,
    tags=['脑图分享'],
    dependencies=[PreAuthDependency(exclude_routes=[
        {'path': '/mindmap/share/view/{share_token}', 'methods': ['GET']},
    ])],
)


# ──────────────────── 创建分享链接 ────────────────────

@mindmap_share_controller.post(
    '/link',
    summary='创建分享链接',
    description='为脑图创建一个新的分享链接',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:mindmap:edit')],
)
@Log(title='脑图分享', business_type=BusinessType.INSERT)
async def create_share_link(
    request: Request,
    create_model: MindmapShareCreateModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapShareService.create_share_link(
        query_db, create_model, current_user.user.user_id,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


# ──────────────────── 获取分享链接列表 ────────────────────

@mindmap_share_controller.get(
    '/link/{mindmap_id}',
    summary='获取分享链接列表',
    description='获取脑图的所有分享链接',
    dependencies=[UserInterfaceAuthDependency('mindmap:mindmap:query')],
)
async def get_share_link_list(
    request: Request,
    mindmap_id: Annotated[int, Path(description='脑图ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapShareService.get_share_list(
        query_db, mindmap_id, current_user.user.user_id,
    )
    return ResponseUtil.success(data=[r.model_dump(by_alias=True) for r in result])


# ──────────────────── 禁用分享链接 ────────────────────

@mindmap_share_controller.delete(
    '/link/{share_id}',
    summary='禁用分享链接',
    description='禁用指定的分享链接',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:mindmap:edit')],
)
@Log(title='脑图分享', business_type=BusinessType.DELETE)
async def delete_share_link(
    request: Request,
    share_id: Annotated[int, Path(description='分享链接ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapShareService.delete_share_link(
        query_db, share_id, current_user.user.user_id,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


# ──────────────────── 公开查看（无需登录） ────────────────────

@mindmap_share_controller.get(
    '/view/{share_token}',
    summary='通过分享链接查看脑图',
    description='公开接口，无需登录即可查看分享的脑图',
)
async def view_by_share_token(
    request: Request,
    share_token: Annotated[str, Path(description='分享token')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    result = await MindmapShareService.view_by_share_token(query_db, share_token)
    return ResponseUtil.success(data=result)
