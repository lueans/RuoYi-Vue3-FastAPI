"""脑图标签字段 Controller"""
from typing import Annotated

from fastapi import Path, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.log_annotation import Log
from common.aspect.db_seesion import DBSessionDependency
from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import CurrentUserDependency, PreAuthDependency
from common.enums import BusinessType
from common.router import APIRouterPro
from common.vo import ResponseBaseModel
from module_admin.entity.vo.user_vo import CurrentUserModel
from module_mindmap.entity.vo.mindmap_tag_field_vo import (
    TagFieldModel,
    TagFieldOptionModel,
    TagFieldOptionSortModel,
)
from module_mindmap.service.mindmap_tag_field_service import MindmapTagFieldService
from utils.log_util import logger
from utils.response_util import ResponseUtil

mindmap_tag_field_controller = APIRouterPro(
    prefix='/mindmap/tag-field',
    order_num=26,
    tags=['脑图标签字段'],
    dependencies=[PreAuthDependency()],
)


# ──────────────────── 字段 CRUD ────────────────────

@mindmap_tag_field_controller.get(
    '/list',
    summary='获取字段列表',
    description='获取全局字段 + 当前用户私有字段',
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:query')],
)
async def get_tag_fields(
    request: Request,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapTagFieldService.get_fields(query_db, current_user.user.user_id)
    return ResponseUtil.success(data=result)


@mindmap_tag_field_controller.get(
    '/suggestions',
    summary='获取字段搜索建议',
    description='侧边栏面板使用，按字段分组返回匹配的选项',
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:query')],
)
async def get_tag_field_suggestions(
    request: Request,
    keyword: Annotated[str | None, Query(description='搜索关键词')] = None,
    query_db: Annotated[AsyncSession, DBSessionDependency()] = ...,
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()] = ...,
) -> Response:
    result = await MindmapTagFieldService.get_suggestions(
        query_db, current_user.user.user_id, keyword,
    )
    return ResponseUtil.success(data=result)


@mindmap_tag_field_controller.get(
    '/{field_id}',
    summary='获取字段详情',
    description='获取字段信息及选项列表',
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:query')],
)
async def get_tag_field_detail(
    request: Request,
    field_id: Annotated[int, Path(description='字段ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapTagFieldService.get_field_detail(
        query_db, field_id, current_user.user.user_id,
    )
    return ResponseUtil.success(data=result)


@mindmap_tag_field_controller.post(
    '',
    summary='新增字段',
    description='新增标签字段',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:add')],
)
@Log(title='标签字段', business_type=BusinessType.INSERT)
async def add_tag_field(
    request: Request,
    model: TagFieldModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapTagFieldService.add_field(
        query_db, model, current_user.user.user_id, current_user.user.user_name,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


@mindmap_tag_field_controller.put(
    '',
    summary='修改字段',
    description='修改标签字段信息',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:edit')],
)
@Log(title='标签字段', business_type=BusinessType.UPDATE)
async def update_tag_field(
    request: Request,
    model: TagFieldModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapTagFieldService.update_field(
        query_db, model, current_user.user.user_id,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


@mindmap_tag_field_controller.delete(
    '/{field_id}',
    summary='删除字段',
    description='删除字段及其所有选项',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:remove')],
)
@Log(title='标签字段', business_type=BusinessType.DELETE)
async def delete_tag_field(
    request: Request,
    field_id: Annotated[int, Path(description='字段ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapTagFieldService.delete_field(
        query_db, field_id, current_user.user.user_id,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


# ──────────────────── 选项 CRUD ────────────────────

@mindmap_tag_field_controller.post(
    '/option',
    summary='新增选项',
    description='为字段新增选项',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:add')],
)
@Log(title='标签选项', business_type=BusinessType.INSERT)
async def add_tag_field_option(
    request: Request,
    model: TagFieldOptionModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapTagFieldService.add_option(
        query_db, model, current_user.user.user_id,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


@mindmap_tag_field_controller.put(
    '/option',
    summary='修改选项',
    description='修改字段选项信息',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:edit')],
)
@Log(title='标签选项', business_type=BusinessType.UPDATE)
async def update_tag_field_option(
    request: Request,
    model: TagFieldOptionModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapTagFieldService.update_option(
        query_db, model, current_user.user.user_id,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


@mindmap_tag_field_controller.delete(
    '/option/{option_id}',
    summary='删除选项',
    description='删除字段选项',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:remove')],
)
@Log(title='标签选项', business_type=BusinessType.DELETE)
async def delete_tag_field_option(
    request: Request,
    option_id: Annotated[int, Path(description='选项ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapTagFieldService.delete_option(
        query_db, option_id, current_user.user.user_id,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


@mindmap_tag_field_controller.put(
    '/option/sort/{field_id}',
    summary='批量更新选项排序',
    description='批量更新字段选项的排序顺序',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:edit')],
)
@Log(title='标签选项排序', business_type=BusinessType.UPDATE)
async def batch_update_option_sort(
    request: Request,
    field_id: Annotated[int, Path(description='字段ID')],
    sort_list: list[TagFieldOptionSortModel],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapTagFieldService.batch_update_option_sort(
        query_db, field_id, sort_list, current_user.user.user_id,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)
