"""脑图标签 Controller"""
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
from module_mindmap.entity.vo.mindmap_tag_vo import (
    MindmapTagModel,
    MindmapTagQueryModel,
)
from module_mindmap.service.mindmap_tag_service import MindmapTagService
from utils.log_util import logger
from utils.response_util import ResponseUtil

mindmap_tag_controller = APIRouterPro(
    prefix='/mindmap/tag',
    order_num=25,
    tags=['脑图标签'],
    dependencies=[PreAuthDependency()],
)


# ──────────────────── 标签分类 ────────────────────

@mindmap_tag_controller.get(
    '/categories',
    summary='获取标签分类列表',
    description='获取全局分类 + 当前用户私有分类',
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:query')],
)
async def get_tag_categories(
    request: Request,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapTagService.get_categories(query_db, current_user.user.user_id)
    return ResponseUtil.success(data=result)


@mindmap_tag_controller.post(
    '/category',
    summary='新增标签分类',
    description='新增标签分类（私有分类）',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:add')],
)
@Log(title='标签分类', business_type=BusinessType.INSERT)
async def add_tag_category(
    request: Request,
    category_name: Annotated[str, Query(description='分类名称', alias='categoryName', min_length=1, max_length=100)],
    sort_order: Annotated[int, Query(description='排序', alias='sortOrder')] = 0,
    query_db: Annotated[AsyncSession, DBSessionDependency()] = ...,
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()] = ...,
) -> Response:
    result = await MindmapTagService.add_category(
        query_db, category_name, current_user.user.user_id, current_user.user.user_name, sort_order,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


@mindmap_tag_controller.put(
    '/category',
    summary='修改标签分类',
    description='修改标签分类名称或排序',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:edit')],
)
@Log(title='标签分类', business_type=BusinessType.UPDATE)
async def update_tag_category(
    request: Request,
    category_id: Annotated[int, Query(description='分类ID', alias='categoryId')],
    category_name: Annotated[str, Query(description='分类名称', alias='categoryName', min_length=1, max_length=100)],
    sort_order: Annotated[int, Query(description='排序', alias='sortOrder')] = 0,
    query_db: Annotated[AsyncSession, DBSessionDependency()] = ...,
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()] = ...,
) -> Response:
    result = await MindmapTagService.update_category(
        query_db, category_id, category_name, sort_order, current_user.user.user_id,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


@mindmap_tag_controller.delete(
    '/category/{category_id}',
    summary='删除标签分类',
    description='删除标签分类（分类下有标签时拒绝删除）',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:remove')],
)
@Log(title='标签分类', business_type=BusinessType.DELETE)
async def delete_tag_category(
    request: Request,
    category_id: Annotated[int, Path(description='分类ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapTagService.delete_category(
        query_db, category_id, current_user.user.user_id,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


# ──────────────────── 标签 CRUD ────────────────────

@mindmap_tag_controller.get(
    '/list',
    summary='获取标签列表',
    description='分页查询标签（支持分类筛选、关键字搜索、范围筛选）',
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:query')],
)
async def get_tag_list(
    request: Request,
    category_id: Annotated[int | None, Query(description='分类ID', alias='categoryId')] = None,
    keyword: Annotated[str | None, Query(description='关键词')] = None,
    owner_scope: Annotated[str | None, Query(description='范围:all/mine/global', alias='ownerScope')] = 'all',
    page_num: Annotated[int, Query(description='页码', alias='pageNum')] = 1,
    page_size: Annotated[int, Query(description='每页数量', alias='pageSize')] = 20,
    query_db: Annotated[AsyncSession, DBSessionDependency()] = ...,
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()] = ...,
) -> Response:
    query = MindmapTagQueryModel(
        categoryId=category_id, keyword=keyword,
        ownerScope=owner_scope, pageNum=page_num, pageSize=page_size,
    )
    result = await MindmapTagService.get_tag_list(query_db, query, current_user.user.user_id)
    return ResponseUtil.success(model_content=result)


@mindmap_tag_controller.get(
    '/suggestions',
    summary='获取标签建议',
    description='用于编辑器自动补全（全局+私有标签）',
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:query')],
)
async def get_tag_suggestions(
    request: Request,
    keyword: Annotated[str | None, Query(description='搜索关键词')] = None,
    query_db: Annotated[AsyncSession, DBSessionDependency()] = ...,
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()] = ...,
) -> Response:
    result = await MindmapTagService.get_suggestions(
        query_db, current_user.user.user_id, keyword,
    )
    return ResponseUtil.success(data=result)


@mindmap_tag_controller.get(
    '/{tag_id}',
    summary='获取标签详情',
    description='获取单个标签的完整信息',
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:query')],
)
async def get_tag_detail(
    request: Request,
    tag_id: Annotated[int, Path(description='标签ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapTagService.get_tag_detail(
        query_db, tag_id, current_user.user.user_id,
    )
    return ResponseUtil.success(data=result)


@mindmap_tag_controller.post(
    '',
    summary='新增标签',
    description='新增标签（自动生成 UUID）',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:add')],
)
@Log(title='脑图标签', business_type=BusinessType.INSERT)
async def add_tag(
    request: Request,
    model: MindmapTagModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapTagService.add_tag(
        query_db, model, current_user.user.user_id, current_user.user.user_name,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


@mindmap_tag_controller.put(
    '',
    summary='修改标签',
    description='修改标签信息',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:edit')],
)
@Log(title='脑图标签', business_type=BusinessType.UPDATE)
async def update_tag(
    request: Request,
    model: MindmapTagModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapTagService.update_tag(
        query_db, model, current_user.user.user_id,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


@mindmap_tag_controller.delete(
    '/{tag_ids}',
    summary='删除标签',
    description='批量删除标签（逗号分隔ID）',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:remove')],
)
@Log(title='脑图标签', business_type=BusinessType.DELETE)
async def delete_tags(
    request: Request,
    tag_ids: Annotated[str, Path(description='标签ID，逗号分隔')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapTagService.delete_tags(
        query_db, tag_ids, current_user.user.user_id,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)
