from datetime import datetime
from typing import Annotated

from fastapi import Path, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.log_annotation import Log
from common.aspect.db_seesion import DBSessionDependency
from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import CurrentUserDependency, PreAuthDependency
from common.enums import BusinessType
from common.router import APIRouterPro
from common.vo import DataResponseModel, PageResponseModel, ResponseBaseModel
from module_admin.entity.vo.user_vo import CurrentUserModel
from module_mindmap.entity.vo.mindmap_vo import (
    DeleteMindmapModel,
    MindmapContentUpdateModel,
    MindmapImportModel,
    MindmapModel,
    MindmapPageQueryModel,
    MindmapRenameModel,
)
from module_mindmap.service.mindmap_service import MindmapService
from utils.log_util import logger
from utils.response_util import ResponseUtil

mindmap_controller = APIRouterPro(
    prefix='/mindmap',
    order_num=20,
    tags=['脑图管理'],
    dependencies=[PreAuthDependency()],
)


@mindmap_controller.get(
    '/list',
    summary='获取脑图分页列表接口',
    description='用于获取脑图分页列表',
    response_model=PageResponseModel[MindmapModel],
    dependencies=[UserInterfaceAuthDependency('mindmap:mindmap:list')],
)
async def get_mindmap_list(
    request: Request,
    query: Annotated[MindmapPageQueryModel, Query()],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    # 设置所有者过滤，只查询当前用户的脑图
    query.owner_id = current_user.user.user_id
    result = await MindmapService.get_mindmap_list_services(query_db, query, is_page=True)
    logger.info('获取成功')

    return ResponseUtil.success(model_content=result)


@mindmap_controller.post(
    '',
    summary='新增脑图接口',
    description='用于新增脑图',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:mindmap:add')],
)
@Log(title='脑图管理', business_type=BusinessType.INSERT)
async def add_mindmap(
    request: Request,
    model: MindmapModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    model.owner_id = current_user.user.user_id
    model.create_by = current_user.user.user_name
    model.create_time = datetime.now()
    model.update_by = current_user.user.user_name
    model.update_time = datetime.now()
    result = await MindmapService.add_mindmap_services(query_db, model)
    logger.info(result.message)

    return ResponseUtil.success(msg=result.message)


@mindmap_controller.put(
    '',
    summary='编辑脑图接口',
    description='用于编辑脑图元数据',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:mindmap:edit')],
)
@Log(title='脑图管理', business_type=BusinessType.UPDATE)
async def edit_mindmap(
    request: Request,
    model: MindmapModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    model.update_by = current_user.user.user_name
    model.update_time = datetime.now()
    result = await MindmapService.edit_mindmap_services(query_db, model, current_user.user.user_id)
    logger.info(result.message)

    return ResponseUtil.success(msg=result.message)


@mindmap_controller.put(
    '/rename',
    summary='重命名脑图接口',
    description='用于重命名脑图',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:mindmap:edit')],
)
@Log(title='脑图管理', business_type=BusinessType.UPDATE)
async def rename_mindmap(
    request: Request,
    model: MindmapRenameModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapService.rename_mindmap_services(query_db, model, current_user.user.user_id)
    logger.info(result.message)

    return ResponseUtil.success(msg=result.message)


@mindmap_controller.put(
    '/content',
    summary='更新脑图内容接口',
    description='用于自动保存脑图内容',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:mindmap:edit')],
)
async def update_mindmap_content(
    request: Request,
    model: MindmapContentUpdateModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapService.update_content_services(query_db, model, current_user.user.user_id)
    logger.info(result.message)

    return ResponseUtil.success(msg=result.message)


@mindmap_controller.post(
    '/copy/{mindmap_id}',
    summary='复制脑图接口',
    description='用于复制指定脑图',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:mindmap:add')],
)
@Log(title='脑图管理', business_type=BusinessType.INSERT)
async def copy_mindmap(
    request: Request,
    mindmap_id: Annotated[int, Path(description='需要复制的脑图ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapService.copy_mindmap_services(query_db, mindmap_id, current_user.user.user_id)
    logger.info(result.message)

    return ResponseUtil.success(msg=result.message)


@mindmap_controller.post(
    '/import',
    summary='导入脑图接口',
    description='用于从localStorage导入脑图',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:mindmap:add')],
)
@Log(title='脑图管理', business_type=BusinessType.INSERT)
async def import_mindmap(
    request: Request,
    import_model: MindmapImportModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    mindmap_model = MindmapModel(
        name=import_model.name,
        owner_id=current_user.user.user_id,
        layout=import_model.layout,
        theme=import_model.theme,
        node_tree=import_model.root,
        view_data=import_model.view,
        create_by=current_user.user.user_name,
        create_time=datetime.now(),
        update_by=current_user.user.user_name,
        update_time=datetime.now(),
    )
    result = await MindmapService.add_mindmap_services(query_db, mindmap_model)
    logger.info(result.message)

    return ResponseUtil.success(msg=result.message)


@mindmap_controller.delete(
    '/{mindmap_ids}',
    summary='删除脑图接口',
    description='用于删除脑图',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:mindmap:remove')],
)
@Log(title='脑图管理', business_type=BusinessType.DELETE)
async def delete_mindmap(
    request: Request,
    mindmap_ids: Annotated[str, Path(description='需要删除的脑图ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    delete_mindmap = DeleteMindmapModel(mindmapIds=mindmap_ids)
    result = await MindmapService.delete_mindmap_services(query_db, delete_mindmap, current_user.user.user_id)
    logger.info(result.message)

    return ResponseUtil.success(msg=result.message)


@mindmap_controller.get(
    '/{mindmap_id}',
    summary='获取脑图详情接口',
    description='用于获取指定脑图的详细信息',
    response_model=DataResponseModel[MindmapModel],
    dependencies=[UserInterfaceAuthDependency('mindmap:mindmap:query')],
)
async def query_detail_mindmap(
    request: Request,
    mindmap_id: Annotated[int, Path(description='脑图ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapService.get_mindmap_detail_services(query_db, mindmap_id, current_user.user.user_id)
    logger.info(f'获取mindmap_id为{mindmap_id}的信息成功')

    return ResponseUtil.success(data=result)
