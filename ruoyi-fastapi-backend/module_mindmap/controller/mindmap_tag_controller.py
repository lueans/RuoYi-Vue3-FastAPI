"""脑图标签 Controller"""
from typing import Annotated, Literal

from fastapi import Path, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.log_annotation import Log
from common.aspect.db_seesion import DBSessionDependency
from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import CurrentUserDependency, PreAuthDependency
from common.enums import BusinessType
from common.router import APIRouterPro
from common.vo import DataResponseModel, ResponseBaseModel
from module_admin.entity.vo.user_vo import CurrentUserModel
from module_mindmap.entity.vo.mindmap_tag_vo import (
    MAX_MINDMAP_TAG_BATCH_IDS_TEXT_LENGTH,
    MAX_MINDMAP_TAG_CATEGORY_NAME_LENGTH,
    MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER,
    MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH,
    MINDMAP_TAG_BATCH_IDS_PATTERN,
    MINDMAP_TAG_SEARCH_KEYWORD_PATTERN,
    MindmapTagArchiveResultModel,
    MindmapTagCategoryCreateResultModel,
    MindmapTagCategoryListItemModel,
    MindmapTagCategoryMutationModel,
    MindmapTagCategoryReorderModel,
    MindmapTagModel,
    MindmapTagQueryModel,
    MindmapTagReplaceModel,
    MindmapTagSuggestionModel,
    MindmapTagSuggestionQueryModel,
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


# ──────────────────── 标签分组（兼容 category API） ────────────────────

@mindmap_tag_controller.get(
    '/categories',
    summary='获取标签分组列表',
    description='获取全局分组 + 当前用户私有分组',
    response_model=DataResponseModel[list[MindmapTagCategoryListItemModel]],
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:query')],
)
async def get_tag_categories(
    request: Request,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapTagService.get_categories(query_db, current_user.user.user_id)
    return ResponseUtil.success(data=result)


@mindmap_tag_controller.put(
    '/categories/order',
    summary='调整标签分组顺序',
    description='通过完整ID列表调整同一所有者范围内的标签分组顺序',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:edit')],
)
@Log(title='标签分组排序', business_type=BusinessType.UPDATE)
async def reorder_tag_categories(
    request: Request,
    model: MindmapTagCategoryReorderModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapTagService.reorder_categories(
        query_db, model, current_user.user.user_id,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


@mindmap_tag_controller.post(
    '/category',
    summary='新增标签分组',
    description='新增私有分组；管理员可显式创建全局分组',
    response_model=DataResponseModel[MindmapTagCategoryCreateResultModel],
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:add')],
)
@Log(title='标签分组', business_type=BusinessType.INSERT)
async def add_tag_category(
    request: Request,
    category_name: Annotated[
        str,
        Query(
            description='分组名称', alias='categoryName', min_length=1,
            max_length=MAX_MINDMAP_TAG_CATEGORY_NAME_LENGTH,
            pattern=MINDMAP_TAG_SEARCH_KEYWORD_PATTERN,
        ),
    ],
    sort_order: Annotated[
        int,
        Query(
            description='排序', alias='sortOrder',
            ge=-MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER,
            le=MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER,
        ),
    ] = 0,
    owner_scope: Annotated[
        Literal['mine', 'global'],
        Query(description='分组作用域', alias='ownerScope'),
    ] = 'mine',
    show_on_home: Annotated[
        bool,
        Query(description='是否在脑图标签首页直接展示', alias='showOnHome'),
    ] = False,
    selection_mode: Annotated[
        Literal['single', 'multiple'],
        Query(description='分组选择模式', alias='selectionMode'),
    ] = 'multiple',
    query_db: Annotated[AsyncSession, DBSessionDependency()] = ...,
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()] = ...,
) -> Response:
    model = MindmapTagCategoryMutationModel(
        name=category_name,
        sortOrder=sort_order,
        ownerScope=owner_scope,
        showOnHome=show_on_home,
        selectionMode=selection_mode,
    )
    result = await MindmapTagService.add_category(
        query_db, model, current_user.user.user_id, current_user.user.user_name,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message, data=result.result)


@mindmap_tag_controller.put(
    '/category',
    summary='修改标签分组',
    description='修改标签分组名称、排序、展示位置或选择模式',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:edit')],
)
@Log(title='标签分组', business_type=BusinessType.UPDATE)
async def update_tag_category(
    request: Request,
    category_id: Annotated[int, Query(description='分组ID', alias='categoryId', gt=0)],
    category_name: Annotated[
        str,
        Query(
            description='分组名称', alias='categoryName', min_length=1,
            max_length=MAX_MINDMAP_TAG_CATEGORY_NAME_LENGTH,
            pattern=MINDMAP_TAG_SEARCH_KEYWORD_PATTERN,
        ),
    ],
    sort_order: Annotated[
        int,
        Query(
            description='排序', alias='sortOrder',
            ge=-MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER,
            le=MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER,
        ),
    ] = 0,
    show_on_home: Annotated[
        bool | None,
        Query(description='是否在脑图标签首页直接展示', alias='showOnHome'),
    ] = None,
    selection_mode: Annotated[
        Literal['single', 'multiple'] | None,
        Query(description='分组选择模式', alias='selectionMode'),
    ] = None,
    query_db: Annotated[AsyncSession, DBSessionDependency()] = ...,
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()] = ...,
) -> Response:
    model = MindmapTagCategoryMutationModel(
        name=category_name,
        sortOrder=sort_order,
        showOnHome=show_on_home,
        selectionMode=selection_mode,
    )
    result = await MindmapTagService.update_category(
        query_db, category_id, model, current_user.user.user_id,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


@mindmap_tag_controller.delete(
    '/category/{category_id}',
    summary='删除标签分组',
    description='删除标签分组（分组下有标签时拒绝删除）',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:remove')],
)
@Log(title='标签分组', business_type=BusinessType.DELETE)
async def delete_tag_category(
    request: Request,
    category_id: Annotated[int, Path(description='分组ID', gt=0)],
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
    '/{tag_id}/impact',
    summary='获取标签影响范围',
    description='返回使用该标签的文件数、节点数和文件示例',
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:query')],
)
async def get_tag_impact(
    request: Request,
    tag_id: Annotated[int, Path(description='标签ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapTagService.get_tag_impact(
        query_db, tag_id, current_user.user.user_id,
    )
    return ResponseUtil.success(data=result)


@mindmap_tag_controller.get(
    '/{tag_id}/usages',
    summary='获取标签使用明细',
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:query')],
)
async def get_tag_usages(
    request: Request,
    tag_id: Annotated[int, Path(description='标签ID')],
    page_num: Annotated[int, Query(alias='pageNum', ge=1)] = 1,
    page_size: Annotated[int, Query(alias='pageSize', ge=1, le=100)] = 20,
    query_db: Annotated[AsyncSession, DBSessionDependency()] = ...,
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()] = ...,
) -> Response:
    result = await MindmapTagService.get_tag_usages(
        query_db, tag_id, current_user.user.user_id, page_num, page_size,
    )
    return ResponseUtil.success(model_content=result)


@mindmap_tag_controller.post(
    '/{tag_id}/disable',
    summary='停用标签',
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:edit')],
)
@Log(title='脑图标签', business_type=BusinessType.UPDATE)
async def disable_tag(
    request: Request,
    tag_id: Annotated[int, Path(description='标签ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapTagService.disable_tag(query_db, tag_id, current_user.user.user_id)
    return ResponseUtil.success(msg=result.message, data=result.result)


@mindmap_tag_controller.post(
    '/{tag_id}/replace',
    summary='全局替换标签',
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:edit')],
)
@Log(title='脑图标签', business_type=BusinessType.UPDATE)
async def replace_tag(
    request: Request,
    tag_id: Annotated[int, Path(description='源标签ID')],
    model: MindmapTagReplaceModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapTagService.replace_tag(
        query_db, tag_id, model.target_tag_id, current_user.user.user_id,
    )
    return ResponseUtil.success(msg=result.message, data=result.result)

@mindmap_tag_controller.get(
    '/list',
    summary='获取标签列表',
    description='分页查询标签（支持分组、状态、范围和关键词筛选）',
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:query')],
)
async def get_tag_list(
    request: Request,
    category_id: Annotated[
        int | None,
        Query(description='分组ID，0 表示未分组', alias='categoryId', ge=0),
    ] = None,
    status: Annotated[int | None, Query(description='状态:0启用 1停用 2归档', ge=0, le=2)] = None,
    keyword: Annotated[
        str | None,
        Query(
            description='关键词',
            max_length=MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH,
            pattern=MINDMAP_TAG_SEARCH_KEYWORD_PATTERN,
        ),
    ] = None,
    owner_scope: Annotated[str | None, Query(description='范围:all/mine/global', alias='ownerScope')] = 'all',
    page_num: Annotated[int, Query(description='页码', alias='pageNum')] = 1,
    page_size: Annotated[int, Query(description='每页数量', alias='pageSize')] = 20,
    query_db: Annotated[AsyncSession, DBSessionDependency()] = ...,
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()] = ...,
) -> Response:
    query = MindmapTagQueryModel(
        categoryId=category_id, status=status, keyword=keyword,
        ownerScope=owner_scope, pageNum=page_num, pageSize=page_size,
    )
    result = await MindmapTagService.get_tag_list(query_db, query, current_user.user.user_id)
    return ResponseUtil.success(model_content=result)


@mindmap_tag_controller.get(
    '/suggestions',
    summary='获取标签建议',
    description='用于编辑器按分组自动补全（全局+私有标签）',
    response_model=DataResponseModel[list[MindmapTagSuggestionModel]],
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:query')],
)
async def get_tag_suggestions(
    request: Request,
    keyword: Annotated[
        str | None,
        Query(
            description='搜索关键词',
            max_length=MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH,
            pattern=MINDMAP_TAG_SEARCH_KEYWORD_PATTERN,
        ),
    ] = None,
    query_db: Annotated[AsyncSession, DBSessionDependency()] = ...,
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()] = ...,
) -> Response:
    query = MindmapTagSuggestionQueryModel(keyword=keyword)
    result = await MindmapTagService.get_suggestions(
        query_db, current_user.user.user_id, query.keyword,
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
    return ResponseUtil.success(msg=result.message, data=result.result)


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
    summary='归档标签',
    description='批量归档标签；可显式解除当前节点绑定，历史版本快照保持不变',
    response_model=DataResponseModel[MindmapTagArchiveResultModel],
    dependencies=[UserInterfaceAuthDependency('mindmap:tag:remove')],
)
@Log(title='脑图标签', business_type=BusinessType.DELETE)
async def delete_tags(
    request: Request,
    tag_ids: Annotated[
        str,
        Path(
            description='标签ID，逗号分隔，最多100项',
            max_length=MAX_MINDMAP_TAG_BATCH_IDS_TEXT_LENGTH,
            pattern=MINDMAP_TAG_BATCH_IDS_PATTERN,
        ),
    ],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
    unbind: Annotated[bool, Query(description='是否先解除全部节点绑定')] = False,
) -> Response:
    result = await MindmapTagService.delete_tags(
        query_db, tag_ids, current_user.user.user_id, unbind=unbind,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)
