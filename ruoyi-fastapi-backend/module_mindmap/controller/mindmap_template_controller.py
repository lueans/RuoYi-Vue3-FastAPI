"""脑图模板 Controller"""
from typing import Annotated

from fastapi import Header, Path, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.log_annotation import Log
from common.aspect.db_seesion import DBSessionDependency
from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import CurrentUserDependency, PreAuthDependency
from common.enums import BusinessType
from common.router import APIRouterPro
from common.vo import ResponseBaseModel
from module_admin.entity.vo.user_vo import CurrentUserModel
from module_mindmap.entity.vo.mindmap_template_vo import (
    MindmapTemplatePublishModel,
    MindmapTemplateQueryModel,
)
from module_mindmap.permissions import mindmap_permissions
from module_mindmap.service.mindmap_creation_service import (
    CREATION_REQUEST_ID_PATTERN,
    MAX_CREATION_REQUEST_ID_LENGTH,
    MIN_CREATION_REQUEST_ID_LENGTH,
)
from module_mindmap.service.mindmap_template_service import MindmapTemplateService
from utils.log_util import logger
from utils.response_util import ResponseUtil

mindmap_template_controller = APIRouterPro(
    prefix='/mindmap/template',
    order_num=24,
    tags=['脑图模板'],
    dependencies=[PreAuthDependency(exclude_routes=[
        {'path': '/mindmap/template/list', 'methods': ['GET']},
        {'path': '/mindmap/template/categories', 'methods': ['GET']},
        {'path': '/mindmap/template/{template_id}', 'methods': ['GET']},
    ])],
)


# ──────────────────── 公开接口 ────────────────────

@mindmap_template_controller.get(
    '/list',
    summary='获取模板列表',
    description='公开接口，获取模板列表（分页）',
)
async def get_template_list(
    request: Request,
    category_id: Annotated[int | None, Query(alias='categoryId', description='分类ID', gt=0)] = None,
    keyword: Annotated[str | None, Query(description='关键词', max_length=200)] = None,
    page_num: Annotated[int, Query(alias='pageNum', description='页码', ge=1)] = 1,
    page_size: Annotated[int, Query(alias='pageSize', description='每页数量', ge=1, le=100)] = 20,
    query_db: Annotated[AsyncSession, DBSessionDependency()] = ...,
) -> Response:
    query = MindmapTemplateQueryModel(
        categoryId=category_id, keyword=keyword,
        pageNum=page_num, pageSize=page_size,
    )
    result = await MindmapTemplateService.get_template_list(query_db, query)
    return ResponseUtil.success(model_content=result)


@mindmap_template_controller.get(
    '/categories',
    summary='获取模板分类',
    description='公开接口，获取所有模板分类',
)
async def get_template_categories(
    request: Request,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    result = await MindmapTemplateService.get_categories(query_db)
    return ResponseUtil.success(data=result)


@mindmap_template_controller.get(
    '/{template_id}',
    summary='获取模板详情',
    description='公开接口，获取模板详情（含 node_tree）',
)
async def get_template_detail(
    request: Request,
    template_id: Annotated[int, Path(description='模板ID', gt=0)],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    result = await MindmapTemplateService.get_template_detail(query_db, template_id)
    return ResponseUtil.success(data=result)


# ──────────────────── 使用模板 ────────────────────

@mindmap_template_controller.post(
    '/use/{template_id}',
    summary='使用模板创建脑图',
    description='从模板复制创建一个新的脑图',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('add'))],
)
@Log(title='脑图模板', business_type=BusinessType.INSERT)
async def use_template(
    request: Request,
    template_id: Annotated[int, Path(description='模板ID', gt=0)],
    idempotency_key: Annotated[
        str,
        Header(
            alias='Idempotency-Key',
            min_length=MIN_CREATION_REQUEST_ID_LENGTH,
            max_length=MAX_CREATION_REQUEST_ID_LENGTH,
            pattern=CREATION_REQUEST_ID_PATTERN,
            description='同一模板创建意图重试时必须复用的幂等键',
        ),
    ],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapTemplateService.use_template(
        query_db,
        template_id,
        current_user.user.user_id,
        current_user.user.user_name,
        creation_request_id=idempotency_key,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message, data=result.result)


# ──────────────────── 管理接口（管理员） ────────────────────

@mindmap_template_controller.post(
    '',
    summary='发布模板',
    description='管理员发布模板（从现有脑图复制）',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:template:add')],
)
@Log(title='脑图模板', business_type=BusinessType.INSERT)
async def publish_template(
    request: Request,
    publish_model: MindmapTemplatePublishModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapTemplateService.publish_template(
        query_db, publish_model, current_user.user.user_name,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message, data=result.result)


@mindmap_template_controller.delete(
    '/{template_id}',
    summary='下架模板',
    description='管理员下架模板',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:template:remove')],
)
@Log(title='脑图模板', business_type=BusinessType.DELETE)
async def unpublish_template(
    request: Request,
    template_id: Annotated[int, Path(description='模板ID', gt=0)],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapTemplateService.unpublish_template(query_db, template_id)
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


@mindmap_template_controller.post(
    '/category',
    summary='新增模板分类',
    description='管理员新增模板分类',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:template:add')],
)
@Log(title='脑图模板分类', business_type=BusinessType.INSERT)
async def add_template_category(
    request: Request,
    category_name: Annotated[
        str,
        Query(alias='name', description='分类名称', min_length=1, max_length=100),
    ],
    sort_order: Annotated[int, Query(alias='sortOrder', description='排序', ge=0, le=9999)] = 0,
    query_db: Annotated[AsyncSession, DBSessionDependency()] = ...,
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()] = ...,
) -> Response:
    result = await MindmapTemplateService.add_category(query_db, category_name, sort_order)
    return ResponseUtil.success(msg=result.message)


@mindmap_template_controller.delete(
    '/category/{category_id}',
    summary='删除模板分类',
    description='管理员删除模板分类',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:template:remove')],
)
@Log(title='脑图模板分类', business_type=BusinessType.DELETE)
async def delete_template_category(
    request: Request,
    category_id: Annotated[int, Path(description='分类ID', gt=0)],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapTemplateService.delete_category(query_db, category_id)
    return ResponseUtil.success(msg=result.message)
