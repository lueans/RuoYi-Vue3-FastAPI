from datetime import datetime
from typing import Annotated

from fastapi import Header, Path, Query, Request, Response
from pydantic_validation_decorator import ValidateFields
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.log_annotation import Log
from common.aspect.db_seesion import DBSessionDependency
from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import CurrentUserDependency, PreAuthDependency
from common.enums import BusinessType
from common.router import APIRouterPro
from common.vo import DataResponseModel, PageResponseModel, ResponseBaseModel
from module_admin.entity.vo.user_vo import CurrentUserModel
from module_mindmap.entity.vo.mindmap_version_vo import (
    MindmapVersionSaveModel,
)
from module_mindmap.entity.vo.mindmap_vo import (
    DeleteMindmapModel,
    MindmapBatchStatusResultModel,
    MindmapBatchStatusUpdateModel,
    MindmapCollaborationResetModel,
    MindmapContentBatchModel,
    MindmapContentUpdateModel,
    MindmapGlobalNodeSearchItemModel,
    MindmapImportModel,
    MindmapListItemModel,
    MindmapMetadataUpdateModel,
    MindmapModel,
    MindmapPageQueryModel,
    MindmapRenameModel,
    MindmapRestoreResultModel,
    MindmapStatusUpdateModel,
    MindmapViewUpdateModel,
)
from module_mindmap.permissions import mindmap_permissions
from module_mindmap.service.mindmap_creation_service import (
    CREATION_REQUEST_ID_PATTERN,
    MAX_CREATION_REQUEST_ID_LENGTH,
    MIN_CREATION_REQUEST_ID_LENGTH,
)
from module_mindmap.service.mindmap_service import MindmapService
from module_mindmap.service.mindmap_version_service import MindmapVersionService
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
    response_model=PageResponseModel[MindmapListItemModel],
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('list'))],
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
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('add'))],
)
@ValidateFields(validate_model='add_mindmap')
@Log(title='脑图管理', business_type=BusinessType.INSERT)
async def add_mindmap(
    request: Request,
    model: MindmapModel,
    idempotency_key: Annotated[
        str,
        Header(
            alias='Idempotency-Key',
            min_length=MIN_CREATION_REQUEST_ID_LENGTH,
            max_length=MAX_CREATION_REQUEST_ID_LENGTH,
            pattern=CREATION_REQUEST_ID_PATTERN,
            description='同一创建意图重试时必须复用的幂等键',
        ),
    ],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    model.owner_id = current_user.user.user_id
    model.create_by = current_user.user.user_name
    model.create_time = datetime.now()
    model.update_by = current_user.user.user_name
    model.update_time = datetime.now()
    result = await MindmapService.add_mindmap_services(
        query_db,
        model,
        creation_request_id=idempotency_key,
        creation_operation='blank',
    )
    logger.info(result.message)

    return ResponseUtil.success(msg=result.message, data=result.result)


@mindmap_controller.put(
    '',
    summary='编辑脑图接口',
    description='用于编辑脑图元数据',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('edit'))],
)
@ValidateFields(validate_model='edit_mindmap')
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
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('edit'))],
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
    '/metadata',
    summary='更新脑图文件信息',
    description='更新当前脑图的名称和说明，不修改正文、权限或文件夹归属',
    response_model=DataResponseModel[MindmapMetadataUpdateModel],
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('edit'))],
)
@Log(title='脑图文件信息', business_type=BusinessType.UPDATE)
async def update_mindmap_metadata(
    request: Request,
    model: MindmapMetadataUpdateModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapService.update_mindmap_metadata_services(
        query_db,
        model,
        current_user.user.user_id,
        current_user.user.user_name,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message, data=result.result)


@mindmap_controller.put(
    '/status',
    summary='归档或恢复脑图',
    description='仅所有者可切换脑图归档状态；归档后文件只读',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('edit'))],
)
@Log(title='脑图归档', business_type=BusinessType.UPDATE)
async def update_mindmap_status(
    request: Request,
    model: MindmapStatusUpdateModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapService.update_mindmap_status_services(
        query_db,
        model,
        current_user.user.user_id,
        current_user.user.user_name,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message, data=result.result)


@mindmap_controller.put(
    '/status/batch',
    summary='批量归档或恢复脑图',
    description='仅所有者可批量切换脑图归档状态；请求集合原子校验，归档后文件只读',
    response_model=DataResponseModel[MindmapBatchStatusResultModel],
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('edit'))],
)
@Log(title='脑图批量归档', business_type=BusinessType.UPDATE)
async def batch_update_mindmap_status(
    request: Request,
    model: MindmapBatchStatusUpdateModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapService.batch_update_mindmap_status_services(
        query_db,
        model,
        current_user.user.user_id,
        current_user.user.user_name,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message, data=result.result)


@mindmap_controller.put(
    '/content',
    summary='更新脑图内容接口',
    description='用于自动保存脑图内容',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('edit'))],
)
async def update_mindmap_content(
    request: Request,
    model: MindmapContentUpdateModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapService.update_content_services(
        query_db,
        model,
        current_user.user.user_id,
        current_user.user.user_name,
    )
    logger.info(result.message)

    return ResponseUtil.success(msg=result.message, data=result.result)


@mindmap_controller.patch(
    '/file/{mindmap_id}/content/batch',
    summary='批量增量保存脑图内容',
    description='按文件修订号提交节点操作，支持幂等重试和节点级冲突检测',
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('edit'))],
)
async def update_mindmap_content_batch(
    request: Request,
    mindmap_id: Annotated[int, Path(description='脑图文件ID')],
    model: MindmapContentBatchModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapService.update_content_batch_services(
        query_db,
        mindmap_id,
        model,
        current_user.user.user_id,
        current_user.user.user_name,
    )
    return ResponseUtil.success(msg='保存成功', data=result)


@mindmap_controller.post(
    '/file/{mindmap_id}/collaboration/reset',
    summary='使用云端版本并重置协作基线',
    description='推进正文修订号并废弃旧 revision 的全部 Yjs 缓存，使所有协作者重新加载数据库正文',
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('edit'))],
)
async def reset_mindmap_collaboration(
    request: Request,
    mindmap_id: Annotated[int, Path(description='脑图文件ID')],
    model: MindmapCollaborationResetModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapService.reset_collaboration_state_services(
        query_db,
        mindmap_id,
        model,
        current_user.user.user_id,
    )
    return ResponseUtil.success(msg='已切换到云端版本', data=result)


@mindmap_controller.patch(
    '/file/{mindmap_id}/view',
    summary='保存脑图画布视图',
    description='以后写覆盖方式保存平移和缩放，不推进正文 contentRevision',
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('edit'))],
)
async def update_mindmap_view(
    request: Request,
    mindmap_id: Annotated[int, Path(description='脑图文件ID')],
    model: MindmapViewUpdateModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapService.update_view_services(
        query_db,
        mindmap_id,
        model,
        current_user.user.user_id,
    )
    return ResponseUtil.success(msg='视图已保存', data=result)


@mindmap_controller.get(
    '/file/{mindmap_id}/changes',
    summary='获取脑图增量变更',
    description='用于断线后按 contentRevision 补齐有序操作',
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('query'))],
)
async def get_mindmap_content_changes(
    request: Request,
    mindmap_id: Annotated[int, Path(description='脑图文件ID')],
    after_revision: Annotated[int, Query(alias='afterRevision', ge=0)],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapService.get_content_changes_services(
        query_db, mindmap_id, after_revision, current_user.user.user_id,
    )
    return ResponseUtil.success(data=result)


@mindmap_controller.get(
    '/nodes/search',
    summary='跨文件搜索脑图节点',
    description='搜索当前用户拥有或被授权访问的有效脑图节点，并返回所属文件和节点路径',
    response_model=PageResponseModel[MindmapGlobalNodeSearchItemModel],
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('query'))],
)
async def search_global_mindmap_nodes(
    request: Request,
    keyword: Annotated[str, Query(min_length=1, max_length=100)],
    page_num: Annotated[int, Query(alias='pageNum', ge=1)] = 1,
    page_size: Annotated[int, Query(alias='pageSize', ge=1, le=50)] = 20,
    query_db: Annotated[AsyncSession, DBSessionDependency()] = ...,
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()] = ...,
) -> Response:
    result = await MindmapService.search_global_nodes_services(
        query_db,
        current_user.user.user_id,
        keyword,
        page_num=page_num,
        page_size=page_size,
    )
    return ResponseUtil.success(model_content=result)


@mindmap_controller.get(
    '/file/{mindmap_id}/nodes/search',
    summary='搜索脑图节点',
    description='按节点文本和统一标签筛选结构化节点',
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('query'))],
)
async def search_mindmap_nodes(
    request: Request,
    mindmap_id: Annotated[int, Path(description='脑图文件ID')],
    keyword: Annotated[str | None, Query(max_length=200)] = None,
    tag_id: Annotated[int | None, Query(alias='tagId', gt=0)] = None,
    page_num: Annotated[int, Query(alias='pageNum', ge=1)] = 1,
    page_size: Annotated[int, Query(alias='pageSize', ge=1, le=100)] = 20,
    query_db: Annotated[AsyncSession, DBSessionDependency()] = ...,
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()] = ...,
) -> Response:
    result = await MindmapService.search_nodes_services(
        query_db, mindmap_id, current_user.user.user_id,
        keyword=keyword, tag_id=tag_id, page_num=page_num, page_size=page_size,
    )
    return ResponseUtil.success(model_content=result)


@mindmap_controller.post(
    '/copy/{mindmap_id}',
    summary='复制脑图接口',
    description='用于复制指定脑图',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('add'))],
)
@Log(title='脑图管理', business_type=BusinessType.INSERT)
async def copy_mindmap(
    request: Request,
    mindmap_id: Annotated[int, Path(description='需要复制的脑图ID')],
    idempotency_key: Annotated[
        str,
        Header(
            alias='Idempotency-Key',
            min_length=MIN_CREATION_REQUEST_ID_LENGTH,
            max_length=MAX_CREATION_REQUEST_ID_LENGTH,
            pattern=CREATION_REQUEST_ID_PATTERN,
            description='同一复制意图重试时必须复用的幂等键',
        ),
    ],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapService.copy_mindmap_services(
        query_db,
        mindmap_id,
        current_user.user.user_id,
        creation_request_id=idempotency_key,
    )
    logger.info(result.message)

    return ResponseUtil.success(msg=result.message, data=result.result)


@mindmap_controller.post(
    '/import',
    summary='导入脑图接口',
    description='用于从localStorage导入脑图',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('add'))],
)
@Log(title='脑图管理', business_type=BusinessType.INSERT)
async def import_mindmap(
    request: Request,
    import_model: MindmapImportModel,
    idempotency_key: Annotated[
        str,
        Header(
            alias='Idempotency-Key',
            min_length=MIN_CREATION_REQUEST_ID_LENGTH,
            max_length=MAX_CREATION_REQUEST_ID_LENGTH,
            pattern=CREATION_REQUEST_ID_PATTERN,
            description='同一导入意图重试时必须复用的幂等键',
        ),
    ],
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
        document_data=import_model.document_data,
        create_by=current_user.user.user_name,
        create_time=datetime.now(),
        update_by=current_user.user.user_name,
        update_time=datetime.now(),
    )
    result = await MindmapService.add_mindmap_services(
        query_db,
        mindmap_model,
        creation_request_id=idempotency_key,
        creation_operation='import',
    )
    logger.info(result.message)

    return ResponseUtil.success(msg=result.message, data=result.result)


@mindmap_controller.delete(
    '/trash/{mindmap_ids}',
    summary='永久删除回收站脑图',
    description='永久删除回收站中的脑图及其内容、版本和访问配置，不可恢复',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('remove'))],
)
@Log(title='脑图回收站', business_type=BusinessType.DELETE)
async def permanently_delete_mindmap(
    request: Request,
    mindmap_ids: Annotated[str, Path(description='需要永久删除的脑图ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapService.permanently_delete_mindmap_services(
        query_db,
        DeleteMindmapModel(mindmapIds=mindmap_ids),
        current_user.user.user_id,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


@mindmap_controller.put(
    '/trash/restore/{mindmap_ids}',
    summary='恢复回收站脑图',
    description='恢复回收站中的脑图；原目录已删除时恢复到根目录',
    response_model=DataResponseModel[MindmapRestoreResultModel],
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('edit'))],
)
@Log(title='脑图回收站', business_type=BusinessType.UPDATE)
async def restore_mindmap(
    request: Request,
    mindmap_ids: Annotated[str, Path(description='需要恢复的脑图ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapService.restore_mindmap_services(
        query_db,
        DeleteMindmapModel(mindmapIds=mindmap_ids),
        current_user.user.user_id,
        current_user.user.user_name,
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message, data=result.result)


@mindmap_controller.delete(
    '/{mindmap_ids}',
    summary='将脑图移入回收站',
    description='暂停分享与协作访问并保留全部关联数据，以便后续恢复',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('remove'))],
)
@Log(title='脑图管理', business_type=BusinessType.DELETE)
async def delete_mindmap(
    request: Request,
    mindmap_ids: Annotated[str, Path(description='需要删除的脑图ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    delete_model = DeleteMindmapModel(mindmapIds=mindmap_ids)
    result = await MindmapService.delete_mindmap_services(
        query_db,
        delete_model,
        current_user.user.user_id,
        current_user.user.user_name,
    )
    logger.info(result.message)

    return ResponseUtil.success(msg=result.message)


@mindmap_controller.get(
    '/{mindmap_id}',
    summary='获取脑图详情接口',
    description='用于获取指定脑图的详细信息',
    response_model=DataResponseModel[MindmapModel],
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('query'))],
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


# ──────────────────── 版本历史 ────────────────────

@mindmap_controller.get(
    '/version/list/{mindmap_id}',
    summary='获取版本列表',
    description='获取脑图的版本历史列表（不含 node_tree 大字段）',
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('query'))],
)
async def get_version_list(
    request: Request,
    mindmap_id: Annotated[int, Path(description='脑图ID')],
    version_type: Annotated[int | None, Query(description='版本类型: 0=草稿 1=正式')] = None,
    page_num: Annotated[int, Query(description='页码')] = 1,
    page_size: Annotated[int, Query(description='每页数量')] = 20,
    query_db: Annotated[AsyncSession, DBSessionDependency()] = ...,
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()] = ...,
) -> Response:
    result = await MindmapVersionService.get_version_list_services(
        query_db, mindmap_id, version_type, page_num, page_size,
        user_id=current_user.user.user_id,
    )
    return ResponseUtil.success(model_content=result)


@mindmap_controller.get(
    '/version/{version_id}',
    summary='获取版本详情',
    description='获取单个版本的完整数据（含 node_tree）',
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('query'))],
)
async def get_version_detail(
    request: Request,
    version_id: Annotated[int, Path(description='版本ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapVersionService.get_version_detail_services(
        query_db, version_id, current_user.user.user_id,
    )
    return ResponseUtil.success(data=result)


@mindmap_controller.post(
    '/version/restore/{version_id}',
    summary='回滚到指定版本',
    description='将脑图恢复到指定版本的状态',
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('edit'))],
)
@Log(title='脑图版本', business_type=BusinessType.UPDATE)
async def restore_version(
    request: Request,
    version_id: Annotated[int, Path(description='版本ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapVersionService.restore_version_services(
        query_db, version_id, current_user.user.user_id, current_user.user.user_name,
    )
    return ResponseUtil.success(msg=result.message, data=result.result)


@mindmap_controller.post(
    '/version/save',
    summary='创建正式版本',
    description='手动创建一个正式版本快照',
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('edit'))],
)
@Log(title='脑图版本', business_type=BusinessType.INSERT)
async def save_formal_version(
    request: Request,
    save_model: MindmapVersionSaveModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapVersionService.create_formal_version(
        query_db, save_model, current_user.user.user_id, current_user.user.user_name,
    )
    return ResponseUtil.success(msg=result.message)


@mindmap_controller.delete(
    '/version/{version_id}',
    summary='删除版本',
    description='删除指定版本（仅正式版本可删除）',
    dependencies=[UserInterfaceAuthDependency(mindmap_permissions('edit'))],
)
@Log(title='脑图版本', business_type=BusinessType.DELETE)
async def delete_version(
    request: Request,
    version_id: Annotated[int, Path(description='版本ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapVersionService.delete_version_services(
        query_db, version_id, current_user.user.user_id,
    )
    return ResponseUtil.success(msg=result.message)
