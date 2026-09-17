"""AI 脑图 Agent、任务、Artifact 与本地应用接口。"""

import asyncio
import json
import re
from collections.abc import AsyncGenerator
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import Body, Header, HTTPException, Path, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.log_annotation import Log
from common.annotation.rate_limit_annotation import ApiRateLimit, ApiRateLimitPreset
from common.aspect.db_seesion import DBSessionDependency
from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import CurrentUserDependency, PreAuthDependency
from common.constant import ApiNamespace
from common.enums import BusinessType
from common.router import APIRouterPro
from common.vo import DataResponseModel
from config.database import AsyncSessionLocal
from exceptions.exception import ServiceException
from module_admin.entity.vo.user_vo import CurrentUserModel
from module_mindmap.ai.document import MindmapArtifactError, validate_smm_artifact
from module_mindmap.dao.mindmap_ai_dao import MindmapAiDao
from module_mindmap.entity.do.mindmap_ai_do import MINDMAP_AI_EVENT_SEQUENCE_MAX
from module_mindmap.entity.vo.mindmap_ai_vo import (
    MindmapAiArtifactValidateModel,
    MindmapAiCloudApplyModel,
    MindmapAiCloudSaveModel,
    MindmapAiConnectorModel,
    MindmapAiConnectorUpdateModel,
    MindmapAiJobCreateModel,
    MindmapAiJobModel,
    MindmapAiJobRetryModel,
    MindmapAiLocalApplyAckModel,
    MindmapAiLocalUndoAckModel,
    MindmapAiMessageModel,
    MindmapAiProposalModel,
    MindmapAiResponseModel,
)
from module_mindmap.permissions import mindmap_permissions
from module_mindmap.service.mindmap_ai_metrics import record_mindmap_ai_event
from module_mindmap.service.mindmap_ai_service import (
    AI_DRAFT_PREVIEW_MAX_VERSION,
    TERMINAL_JOB_STATUSES,
    MindmapAiService,
    sanitize_mindmap_ai_event_payload,
)
from utils.response_util import ResponseUtil

IDEMPOTENCY_KEY_PATTERN = re.compile(r'^[A-Za-z0-9._:-]{8,100}$')
SSE_EVENT_TYPE_PATTERN = re.compile(r'^[a-z][a-z0-9_]{0,63}$')


def _parse_last_event_id(value: str | None) -> int:
    """把不可信 SSE 游标收敛到数据库 INTEGER 的安全范围。"""
    try:
        sequence = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return min(max(sequence, 0), MINDMAP_AI_EVENT_SEQUENCE_MAX)


def _artifact_content_disposition(title: str, *, draft: bool) -> str:
    """同时提供 ASCII fallback 与 RFC 5987 UTF-8 文件名，避免响应头编码失败。"""
    safe_title = re.sub(r'[^\w\u4e00-\u9fff.-]+', '-', title).strip('-.')[:80] or 'ai-mindmap'
    suffix = '.draft' if draft else ''
    download_name = f'{safe_title}{suffix}.smm'
    ascii_title = re.sub(r'[^A-Za-z0-9._-]+', '-', safe_title).strip('-.')[:80] or 'ai-mindmap'
    ascii_name = f'{ascii_title}{suffix}.smm'
    encoded_name = quote(download_name, safe='')
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded_name}'


mindmap_ai_controller = APIRouterPro(
    prefix='/mindmap/ai',
    order_num=21,
    tags=['脑图管理-AI Agent'],
    dependencies=[
        PreAuthDependency(),
        UserInterfaceAuthDependency('mindmap:ai:use'),
    ],
)

mindmap_ai_apply_controller = APIRouterPro(
    prefix='/mindmap/file',
    order_num=21,
    tags=['脑图管理-AI Agent'],
    dependencies=[
        PreAuthDependency(),
        UserInterfaceAuthDependency('mindmap:ai:use'),
    ],
)

mindmap_ai_admin_controller = APIRouterPro(
    prefix='/mindmap/ai/admin',
    order_num=21,
    tags=['脑图管理-AI Agent 管理'],
    dependencies=[
        PreAuthDependency(),
        UserInterfaceAuthDependency('mindmap:ai:admin'),
    ],
)


@mindmap_ai_controller.get('/agents', summary='查询可用的脑图 AI Agent')
async def list_mindmap_agents(
    request: Request,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
    intent: Annotated[str | None, Query(max_length=32)] = None,
    input_type: Annotated[str | None, Query(alias='inputType', max_length=32)] = None,
) -> Response:
    return ResponseUtil.success(data=await MindmapAiService.list_agents(
        query_db,
        current_user.user.user_id,
        intent,
        input_type,
    ))


@mindmap_ai_admin_controller.get(
    '/connectors',
    summary='查询 AI 脑图 Agent Connector 配置',
    response_model=DataResponseModel[list[MindmapAiConnectorModel]],
)
async def list_mindmap_ai_connectors(
    request: Request,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    return ResponseUtil.success(data=await MindmapAiService.list_connectors(query_db))


@mindmap_ai_admin_controller.patch(
    '/connectors/{agent_key}',
    summary='更新 AI 脑图 Agent Connector 配置',
    response_model=DataResponseModel[MindmapAiConnectorModel],
)
@Log(title='AI 脑图 Agent Connector', business_type=BusinessType.UPDATE)
async def update_mindmap_ai_connector(
    request: Request,
    agent_key: Annotated[str, Path(pattern=r'^[a-z][a-z0-9_]{1,63}$')],
    model: MindmapAiConnectorUpdateModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    return ResponseUtil.success(data=await MindmapAiService.update_connector(
        query_db,
        agent_key,
        model,
        current_user.user.user_name,
    ))


@mindmap_ai_admin_controller.post(
    '/connectors/{agent_key}/health-check',
    summary='执行 AI 脑图 Agent 健康检查',
    response_model=DataResponseModel[MindmapAiConnectorModel],
)
@Log(title='AI 脑图 Agent 健康检查', business_type=BusinessType.OTHER)
async def health_check_mindmap_ai_connector(
    request: Request,
    agent_key: Annotated[str, Path(pattern=r'^[a-z][a-z0-9_]{1,63}$')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    return ResponseUtil.success(data=await MindmapAiService.health_check_connector(
        query_db,
        agent_key,
        current_user.user.user_name,
    ))


@mindmap_ai_admin_controller.post(
    '/connectors/{agent_key}/conformance',
    summary='校验 AI 脑图 Agent Adapter 合同',
    response_model=DataResponseModel[MindmapAiConnectorModel],
)
@Log(title='AI 脑图 Agent 一致性检查', business_type=BusinessType.OTHER)
async def conformance_mindmap_ai_connector(
    request: Request,
    agent_key: Annotated[str, Path(pattern=r'^[a-z][a-z0-9_]{1,63}$')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    return ResponseUtil.success(data=await MindmapAiService.conformance_connector(
        query_db,
        agent_key,
        current_user.user.user_name,
    ))


@mindmap_ai_controller.post(
    '/jobs',
    summary='创建 AI 脑图任务',
    response_model=DataResponseModel[MindmapAiJobModel],
)
@ApiRateLimit(namespace=ApiNamespace.AI_CHAT_SEND, preset=ApiRateLimitPreset.USER_INTERACTIVE_HIGH_FREQ)
async def create_mindmap_ai_job(
    request: Request,
    model: MindmapAiJobCreateModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
    idempotency_key: Annotated[str, Header(alias='Idempotency-Key', min_length=8, max_length=100)],
) -> Response:
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
        raise ServiceException(message='幂等键格式无效')
    result = await MindmapAiService.create_job(query_db, model, current_user.user.user_id, idempotency_key)
    return ResponseUtil.success(data=result)


@mindmap_ai_controller.get(
    '/jobs/reconcile',
    summary='按幂等键恢复已创建的 AI 脑图任务',
    response_model=DataResponseModel[MindmapAiJobModel],
)
async def reconcile_mindmap_ai_job_attempt(
    request: Request,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
    idempotency_key: Annotated[str, Header(alias='Idempotency-Key', min_length=8, max_length=100)],
) -> Response:
    """Recover a committed job after the original create response was lost.

    The key stays in a header so it is not copied into URL/access logs. Lookup is
    always scoped to the authenticated owner and intentionally exposes neither
    the stored request payload nor its fingerprint.
    """
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
        raise ServiceException(message='幂等键格式无效')
    result = await MindmapAiService.reconcile_job_attempt(
        query_db,
        current_user.user.user_id,
        idempotency_key,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='AI 脑图任务不存在',
        )
    return ResponseUtil.success(
        data=result,
        headers={'Cache-Control': 'private, no-store'},
    )


@mindmap_ai_controller.get(
    '/jobs/{job_id}',
    summary='查询 AI 脑图任务',
    response_model=DataResponseModel[MindmapAiJobModel],
)
async def get_mindmap_ai_job(
    request: Request,
    job_id: Annotated[str, Path(min_length=36, max_length=36)],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    return ResponseUtil.success(
        data=await MindmapAiService.get_job(query_db, job_id, current_user.user.user_id),
    )


@mindmap_ai_controller.get(
    '/sessions',
    summary='分页查询 AI 脑图会话',
    response_model=DataResponseModel[dict[str, Any]],
)
async def list_mindmap_ai_sessions(
    request: Request,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    page: Annotated[int, Query(ge=1)] = 1,
) -> Response:
    return ResponseUtil.success(
        data=await MindmapAiService.list_sessions(
            query_db,
            current_user.user.user_id,
            page=page,
            limit=limit,
        ),
        headers={'Cache-Control': 'private, no-store'},
    )


@mindmap_ai_controller.get(
    '/sessions/{session_id}',
    summary='读取 AI 脑图会话交互记录',
    response_model=DataResponseModel[dict[str, Any]],
)
async def get_mindmap_ai_session_timeline(
    request: Request,
    session_id: Annotated[str, Path(min_length=36, max_length=36)],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    return ResponseUtil.success(
        data=await MindmapAiService.get_session_timeline(
            query_db,
            session_id,
            current_user.user.user_id,
        ),
    )


@mindmap_ai_controller.get(
    '/responses/{response_id}',
    summary='读取 AI 讨论模式文字答复',
    response_model=DataResponseModel[MindmapAiResponseModel],
)
async def get_mindmap_ai_response(
    request: Request,
    response_id: Annotated[str, Path(min_length=36, max_length=36)],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    return ResponseUtil.success(
        data=await MindmapAiService.get_response(
            query_db,
            response_id,
            current_user.user.user_id,
        ),
        headers={
            'Cache-Control': 'private, no-store',
            'X-Content-Type-Options': 'nosniff',
        },
    )


@mindmap_ai_controller.delete(
    '/sessions/{session_id}',
    summary='删除 AI 脑图会话及其生成数据',
)
@Log(title='AI 脑图会话', business_type=BusinessType.DELETE)
async def delete_mindmap_ai_session(
    request: Request,
    session_id: Annotated[str, Path(min_length=36, max_length=36)],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    return ResponseUtil.success(
        data=await MindmapAiService.delete_session(
            query_db,
            session_id,
            current_user.user.user_id,
        ),
    )


@mindmap_ai_controller.get(
    '/jobs/{job_id}/draft',
    summary='读取 AI 脑图实时草稿快照',
    response_model=DataResponseModel[dict[str, Any]],
)
async def get_mindmap_ai_job_draft(
    request: Request,
    job_id: Annotated[str, Path(min_length=36, max_length=36)],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
    version: Annotated[int | None, Query(ge=0, le=AI_DRAFT_PREVIEW_MAX_VERSION)] = None,
) -> Response:
    preview = await MindmapAiService.get_job_draft_preview(
        query_db,
        job_id,
        current_user.user.user_id,
        version=version,
    )
    return ResponseUtil.success(
        data=preview,
        headers={
            'Cache-Control': 'private, no-store',
            'X-Mindmap-AI-Preview-Version': str(preview.get('operationCursor') or 0),
        },
    )


@mindmap_ai_controller.post(
    '/jobs/{job_id}/messages',
    summary='基于 AI 结果或当前本地/云端正文继续一轮调整',
    response_model=DataResponseModel[MindmapAiJobModel],
)
@ApiRateLimit(namespace=ApiNamespace.AI_CHAT_SEND, preset=ApiRateLimitPreset.USER_INTERACTIVE_HIGH_FREQ)
async def continue_mindmap_ai_job(
    request: Request,
    job_id: Annotated[str, Path(min_length=36, max_length=36)],
    model: MindmapAiMessageModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
    idempotency_key: Annotated[str, Header(alias='Idempotency-Key', min_length=8, max_length=100)],
) -> Response:
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
        raise ServiceException(message='幂等键格式无效')
    return ResponseUtil.success(data=await MindmapAiService.create_followup_job(
        query_db,
        job_id,
        model,
        current_user.user.user_id,
        idempotency_key,
    ))


@mindmap_ai_controller.post(
    '/jobs/{job_id}/retry',
    summary='重试失败的 AI 脑图任务并创建新轮次',
    response_model=DataResponseModel[MindmapAiJobModel],
)
@ApiRateLimit(namespace=ApiNamespace.AI_CHAT_SEND, preset=ApiRateLimitPreset.USER_INTERACTIVE_HIGH_FREQ)
async def retry_mindmap_ai_job(
    request: Request,
    job_id: Annotated[str, Path(min_length=36, max_length=36)],
    model: MindmapAiJobRetryModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
    idempotency_key: Annotated[str, Header(alias='Idempotency-Key', min_length=8, max_length=100)],
) -> Response:
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
        raise ServiceException(message='幂等键格式无效')
    return ResponseUtil.success(data=await MindmapAiService.retry_job(
        query_db,
        job_id,
        model,
        current_user.user.user_id,
        idempotency_key,
    ))


async def _event_stream(
    request: Request,
    job_id: str,
    user_id: int,
    after_sequence: int,
) -> AsyncGenerator[str, None]:
    cursor = after_sequence
    idle_cycles = 0
    while True:
        if await request.is_disconnected():
            return
        chunks: list[tuple[int, str]] = []
        async with AsyncSessionLocal() as db:
            job = await MindmapAiDao.get_job(db, job_id, user_id)
            if job is None:
                return
            events = await MindmapAiDao.list_events(db, job_id, cursor)
            for event in events:
                try:
                    raw_payload = json.loads(event.payload_json)
                except (TypeError, json.JSONDecodeError):
                    raw_payload = {}
                event_type = (
                    event.event_type
                    if SSE_EVENT_TYPE_PATTERN.fullmatch(event.event_type or '')
                    else 'agent_event'
                )
                data = {
                    'sequence': event.sequence,
                    'eventType': event_type,
                    'payload': sanitize_mindmap_ai_event_payload(raw_payload),
                    'createdTime': event.created_time.isoformat(),
                }
                try:
                    encoded_data = json.dumps(data, ensure_ascii=False, allow_nan=False)
                except (TypeError, ValueError):
                    data['payload'] = {}
                    encoded_data = json.dumps(data, ensure_ascii=False, allow_nan=False)
                chunks.append((
                    event.sequence,
                    f'id: {event.sequence}\nevent: {event_type}\ndata: {encoded_data}\n\n',
                ))
            terminal = job.status in TERMINAL_JOB_STATUSES
        # Do not suspend the generator at a network-facing yield while a database
        # session is open. A slow SSE client must not retain a pooled connection.
        for sequence, chunk in chunks:
            cursor = sequence
            yield chunk
        if terminal and not events:
            return
        if not events:
            idle_cycles += 1
            if idle_cycles % 30 == 0:
                yield ': keepalive\n\n'
            await asyncio.sleep(0.5)
        else:
            idle_cycles = 0


@mindmap_ai_controller.get('/jobs/{job_id}/events', summary='订阅 AI 脑图任务事件')
async def stream_mindmap_ai_job_events(
    request: Request,
    job_id: Annotated[str, Path(min_length=36, max_length=36)],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
    last_event_id: Annotated[str | None, Header(alias='Last-Event-ID')] = None,
) -> StreamingResponse:
    user_id = current_user.user.user_id
    # 预检必须在 StreamingResponse 启流前完成，同时不能把请求级数据库连接
    # 占用到整段长连接结束。
    async with AsyncSessionLocal() as db:
        job = await MindmapAiDao.get_job(db, job_id, user_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='AI 脑图任务不存在',
        )
    after_sequence = _parse_last_event_id(last_event_id)
    return StreamingResponse(
        _event_stream(request, job_id, user_id, after_sequence),
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache, no-transform',
            'X-Accel-Buffering': 'no',
        },
    )


@mindmap_ai_controller.post(
    '/jobs/{job_id}/cancel',
    summary='取消 AI 脑图任务',
    response_model=DataResponseModel[MindmapAiJobModel],
)
async def cancel_mindmap_ai_job(
    request: Request,
    job_id: Annotated[str, Path(min_length=36, max_length=36)],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    return ResponseUtil.success(
        data=await MindmapAiService.cancel_job(query_db, job_id, current_user.user.user_id),
    )


@mindmap_ai_controller.get('/artifacts/{artifact_id}/download', summary='下载 AI 脑图 SMM v2 文件')
async def download_mindmap_ai_artifact(
    request: Request,
    artifact_id: Annotated[str, Path(min_length=36, max_length=36)],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    record, artifact = await MindmapAiService.get_artifact(query_db, artifact_id, current_user.user.user_id)
    record_mindmap_ai_event('artifact_downloaded')
    return Response(
        content=json.dumps(artifact, ensure_ascii=False, separators=(',', ':')).encode('utf-8'),
        media_type='application/json',
        headers={
            'Content-Disposition': _artifact_content_disposition(
                record.title,
                draft=record.validation_status == 'draft',
            ),
            'X-Content-Type-Options': 'nosniff',
            'X-Mindmap-Document-Hash': record.document_hash,
        },
    )


@mindmap_ai_controller.post('/artifacts/validate', summary='校验 SMM v2 文件')
async def validate_mindmap_ai_artifact(
    request: Request,
    model: Annotated[MindmapAiArtifactValidateModel, Body()],
) -> Response:
    try:
        artifact, summary = validate_smm_artifact(model.artifact, require_passed=model.require_passed)
    except MindmapArtifactError as exc:
        # This endpoint validates a client-supplied artifact. A structural
        # violation therefore belongs to the input contract; AI_OUTPUT_INVALID
        # is reserved for an Agent result that fails after generation.
        error_code = 'AI_INPUT_INVALID' if exc.code == 'AI_OUTPUT_INVALID' else exc.code
        raise ServiceException(data={'errorCode': error_code}, message=str(exc)) from exc
    return ResponseUtil.success(data={
        'documentHash': artifact['manifest']['documentHash'],
        'validation': artifact['manifest']['validation'],
        'summary': summary,
    })


@mindmap_ai_controller.post('/proposals/{proposal_id}/prepare-local-apply', summary='准备本地原子应用包')
async def prepare_mindmap_ai_local_apply(
    request: Request,
    proposal_id: Annotated[str, Path(min_length=36, max_length=36)],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    return ResponseUtil.success(
        data=await MindmapAiService.prepare_local_apply(query_db, proposal_id, current_user.user.user_id),
    )


@mindmap_ai_controller.get(
    '/proposals/{proposal_id}',
    summary='查询 AI 脑图提案与差异摘要',
    response_model=DataResponseModel[MindmapAiProposalModel],
)
async def get_mindmap_ai_proposal(
    request: Request,
    proposal_id: Annotated[str, Path(min_length=36, max_length=36)],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    return ResponseUtil.success(
        data=await MindmapAiService.get_proposal(query_db, proposal_id, current_user.user.user_id),
    )


@mindmap_ai_controller.post('/proposals/{proposal_id}/ack-local-apply', summary='确认本地提案已原子应用')
async def ack_mindmap_ai_local_apply(
    request: Request,
    proposal_id: Annotated[str, Path(min_length=36, max_length=36)],
    model: MindmapAiLocalApplyAckModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    return ResponseUtil.success(
        data=await MindmapAiService.ack_local_apply(
            query_db, proposal_id, current_user.user.user_id, model,
        ),
    )


@mindmap_ai_controller.post('/proposals/{proposal_id}/ack-local-undo', summary='确认本地提案已原子撤销')
async def ack_mindmap_ai_local_undo(
    request: Request,
    proposal_id: Annotated[str, Path(min_length=36, max_length=36)],
    model: MindmapAiLocalUndoAckModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    return ResponseUtil.success(
        data=await MindmapAiService.ack_local_undo(
            query_db, proposal_id, current_user.user.user_id, model,
        ),
    )


@mindmap_ai_controller.post(
    '/artifacts/{artifact_id}/save-cloud',
    summary='把 AI Artifact 另存为云端脑图',
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('add'))],
)
async def save_mindmap_ai_artifact_cloud(
    request: Request,
    artifact_id: Annotated[str, Path(min_length=36, max_length=36)],
    model: MindmapAiCloudSaveModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
    idempotency_key: Annotated[str, Header(alias='Idempotency-Key', min_length=16, max_length=100)],
) -> Response:
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
        raise ServiceException(message='幂等键格式无效')
    return ResponseUtil.success(data=await MindmapAiService.save_artifact_cloud(
        query_db,
        artifact_id,
        current_user.user.user_id,
        current_user.user.user_name,
        model,
        idempotency_key,
    ))


@mindmap_ai_apply_controller.post(
    '/{mindmap_id}/ai/proposals/{proposal_id}/apply',
    summary='原子应用 AI 提案到云端脑图',
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('edit'))],
)
async def apply_mindmap_ai_cloud_proposal(
    request: Request,
    mindmap_id: Annotated[int, Path(gt=0)],
    proposal_id: Annotated[str, Path(min_length=36, max_length=36)],
    model: MindmapAiCloudApplyModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
    idempotency_key: Annotated[str, Header(alias='Idempotency-Key', min_length=16, max_length=100)],
) -> Response:
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
        raise ServiceException(message='幂等键格式无效')
    return ResponseUtil.success(data=await MindmapAiService.apply_cloud_proposal(
        query_db,
        mindmap_id,
        proposal_id,
        current_user.user.user_id,
        current_user.user.user_name,
        model,
        idempotency_key,
    ))


@mindmap_ai_apply_controller.post(
    '/{mindmap_id}/ai/proposals/{proposal_id}/undo',
    summary='在无后续协作修改时撤销云端 AI 提案',
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('edit'))],
)
async def undo_mindmap_ai_cloud_proposal(
    request: Request,
    mindmap_id: Annotated[int, Path(gt=0)],
    proposal_id: Annotated[str, Path(min_length=36, max_length=36)],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
    idempotency_key: Annotated[str, Header(alias='Idempotency-Key', min_length=16, max_length=100)],
) -> Response:
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
        raise ServiceException(message='幂等键格式无效')
    return ResponseUtil.success(data=await MindmapAiService.undo_cloud_proposal(
        query_db,
        mindmap_id,
        proposal_id,
        current_user.user.user_id,
        current_user.user.user_name,
        idempotency_key,
    ))
