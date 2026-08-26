"""脑图评论 Controller。"""
from typing import Annotated, Literal

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
from module_mindmap.entity.vo.mindmap_comment_vo import (
    MindmapCommentCreateModel,
    MindmapCommentReplyModel,
    MindmapCommentStatusModel,
)
from module_mindmap.permissions import mindmap_permissions
from module_mindmap.service.mindmap_comment_service import (
    COMMENT_REQUEST_ID_PATTERN,
    MAX_COMMENT_REQUEST_ID_LENGTH,
    MIN_COMMENT_REQUEST_ID_LENGTH,
    MindmapCommentService,
)
from utils.response_util import ResponseUtil

mindmap_comment_controller = APIRouterPro(
    prefix='/mindmap/comment',
    order_num=24,
    tags=['脑图评论'],
    dependencies=[PreAuthDependency()],
)


@mindmap_comment_controller.get(
    '/list/{mindmap_id}',
    summary='获取脑图评论线程',
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('query'))],
)
async def list_comments(
    request: Request,
    mindmap_id: Annotated[int, Path(gt=0, description='脑图ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
    status: Annotated[Literal['open', 'resolved', 'all'], Query(description='线程状态')] = 'open',
    node_uid: Annotated[str | None, Query(alias='nodeUid', max_length=64)] = None,
    page_num: Annotated[int, Query(alias='pageNum', ge=1)] = 1,
    page_size: Annotated[int, Query(alias='pageSize', ge=1, le=100)] = 50,
) -> Response:
    result = await MindmapCommentService.list_threads(
        query_db,
        mindmap_id,
        current_user.user.user_id,
        status=status,
        node_uid=node_uid,
        page_num=page_num,
        page_size=page_size,
    )
    return ResponseUtil.success(data=result)


@mindmap_comment_controller.post(
    '',
    summary='创建节点评论',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('query'))],
)
@Log(title='脑图评论', business_type=BusinessType.INSERT)
async def create_comment(
    request: Request,
    model: MindmapCommentCreateModel,
    idempotency_key: Annotated[
        str,
        Header(
            alias='Idempotency-Key',
            min_length=MIN_COMMENT_REQUEST_ID_LENGTH,
            max_length=MAX_COMMENT_REQUEST_ID_LENGTH,
            pattern=COMMENT_REQUEST_ID_PATTERN,
            description='同一评论写入重试时必须复用的幂等键',
        ),
    ],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapCommentService.create_thread(
        query_db, model, current_user.user.user_id, idempotency_key,
    )
    return ResponseUtil.success(data=result, msg='评论已发布')


@mindmap_comment_controller.post(
    '/{thread_id}/reply',
    summary='回复评论线程',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('query'))],
)
@Log(title='脑图评论', business_type=BusinessType.INSERT)
async def reply_comment(
    request: Request,
    thread_id: Annotated[int, Path(gt=0, description='评论线程ID')],
    model: MindmapCommentReplyModel,
    idempotency_key: Annotated[
        str,
        Header(
            alias='Idempotency-Key',
            min_length=MIN_COMMENT_REQUEST_ID_LENGTH,
            max_length=MAX_COMMENT_REQUEST_ID_LENGTH,
            pattern=COMMENT_REQUEST_ID_PATTERN,
            description='同一回复写入重试时必须复用的幂等键',
        ),
    ],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapCommentService.reply_thread(
        query_db, thread_id, model, current_user.user.user_id, idempotency_key,
    )
    return ResponseUtil.success(data=result, msg='回复已发布')


@mindmap_comment_controller.put(
    '/{thread_id}/status',
    summary='解决或重新打开评论线程',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('query'))],
)
@Log(title='脑图评论', business_type=BusinessType.UPDATE)
async def update_comment_status(
    request: Request,
    thread_id: Annotated[int, Path(gt=0, description='评论线程ID')],
    model: MindmapCommentStatusModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    await MindmapCommentService.set_thread_status(
        query_db, thread_id, model.resolved, current_user.user.user_id,
    )
    return ResponseUtil.success(msg='评论状态已更新')


@mindmap_comment_controller.delete(
    '/message/{comment_id}',
    summary='删除评论消息',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('query'))],
)
@Log(title='脑图评论', business_type=BusinessType.DELETE)
async def delete_comment(
    request: Request,
    comment_id: Annotated[int, Path(gt=0, description='评论消息ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapCommentService.delete_comment(
        query_db, comment_id, current_user.user.user_id,
    )
    return ResponseUtil.success(data=result, msg='评论已删除')
