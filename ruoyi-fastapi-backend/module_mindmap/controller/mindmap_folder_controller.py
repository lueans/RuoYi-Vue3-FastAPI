"""脑图文件夹 Controller"""
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
from module_mindmap.entity.vo.mindmap_folder_vo import (
    MindmapFolderModel,
    MindmapFolderSortModel,
    MindmapMoveModel,
)
from module_mindmap.service.mindmap_folder_service import MindmapFolderService
from utils.log_util import logger
from utils.response_util import ResponseUtil

mindmap_folder_controller = APIRouterPro(
    prefix='/mindmap/folder',
    order_num=24,
    tags=['脑图文件夹'],
    dependencies=[PreAuthDependency()],
)


@mindmap_folder_controller.get(
    '/tree',
    summary='获取文件夹树',
    description='获取当前用户的文件夹树结构',
    dependencies=[UserInterfaceAuthDependency('mindmap:folder:list')],
)
async def get_folder_tree(
    request: Request,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapFolderService.get_folder_tree(query_db, current_user.user.user_id)
    return ResponseUtil.success(data=result)


@mindmap_folder_controller.post(
    '',
    summary='新建文件夹',
    description='创建新的文件夹',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:folder:add')],
)
@Log(title='文件夹管理', business_type=BusinessType.INSERT)
async def add_folder(
    request: Request,
    model: MindmapFolderModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapFolderService.add_folder(
        query_db, model, current_user.user.user_id, current_user.user.user_name,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message, data=result.result)


@mindmap_folder_controller.put(
    '',
    summary='编辑文件夹',
    description='重命名或移动文件夹',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:folder:edit')],
)
@Log(title='文件夹管理', business_type=BusinessType.UPDATE)
async def update_folder(
    request: Request,
    model: MindmapFolderModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapFolderService.update_folder(
        query_db, model, current_user.user.user_id, current_user.user.user_name,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


@mindmap_folder_controller.put(
    '/sort',
    summary='文件夹排序',
    description='批量更新文件夹排序和父级',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:folder:edit')],
)
async def sort_folders(
    request: Request,
    model: MindmapFolderSortModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapFolderService.sort_folders(
        query_db, model, current_user.user.user_id,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


@mindmap_folder_controller.delete(
    '/{folder_id}',
    summary='删除文件夹',
    description='删除文件夹，内容自动移至根目录',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:folder:remove')],
)
@Log(title='文件夹管理', business_type=BusinessType.DELETE)
async def delete_folder(
    request: Request,
    folder_id: Annotated[int, Path(description='文件夹ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapFolderService.delete_folder(
        query_db, folder_id, current_user.user.user_id,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


# ──────────────────── 移动脑图 ────────────────────

# 注意：此接口挂在 /mindmap 前缀下，需要单独的 router
mindmap_move_controller = APIRouterPro(
    prefix='/mindmap',
    order_num=24,
    tags=['脑图文件夹'],
    dependencies=[PreAuthDependency()],
)


@mindmap_move_controller.put(
    '/move',
    summary='移动脑图到文件夹',
    description='批量将脑图移动到指定文件夹',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:mindmap:edit')],
)
@Log(title='脑图移动', business_type=BusinessType.UPDATE)
async def move_mindmaps(
    request: Request,
    model: MindmapMoveModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapFolderService.move_mindmaps(
        query_db, model, current_user.user.user_id,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)
