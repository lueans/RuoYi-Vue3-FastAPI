"""Read-only template discovery uses the same owner/collaborator access as maps."""

from typing import Any

from sqlalchemy import Select, String, and_, case, cast, exists, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import PageModel
from exceptions.exception import ServiceException
from module_admin.entity.do.user_do import SysUser
from module_mindmap.ai.document import MindmapArtifactError
from module_mindmap.ai.template_profile import TEMPLATE_PROFILE_STORAGE_KEY, build_template_profile
from module_mindmap.dao.mindmap_dao import MindmapDao
from module_mindmap.entity.do.mindmap_collaborator_do import MindmapCollaborator
from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.entity.do.mindmap_folder_do import MindmapFolder
from module_mindmap.entity.vo.mindmap_ai_template_vo import (
    MindmapAiTemplateDetailModel,
    MindmapAiTemplateSummaryModel,
)
from module_mindmap.service.mindmap_ai_tag_catalog import load_ai_tag_catalog
from module_mindmap.service.mindmap_folder_service import MAX_FOLDER_DEPTH
from module_mindmap.service.mindmap_service import MindmapService
from utils.page_util import PageUtil

TEMPLATE_FOLDER_NAMES = ('模版', '模板')
MAX_TEMPLATE_PATH_LENGTH = MAX_FOLDER_DEPTH * 103


class MindmapAiTemplateService:
    @classmethod
    async def freeze_request_template(cls, db: AsyncSession, request: Any, user_id: int) -> None:
        """Resolve once after idempotency lookup; persistence owns the snapshot."""
        request._template_profile = None
        selected = next((item for item in request.attachments if item.purpose == 'template'), None)
        if selected is None or selected.template_source is None:
            return  # Older turns have only untrusted format guidance.
        source = selected.template_source
        detail = await cls.get_template(db, source.mindmap_id, user_id)
        if detail['contentRevision'] != source.content_revision:
            raise ServiceException(message='模版已更新，请重新选择后发送')
        target_id = request.source.mindmap_id if request.execution_mode == 'direct' or request.target == 'proposal' else None
        catalog = await load_ai_tag_catalog(db, user_id, mindmap_id=target_id)
        try:
            request._template_profile = build_template_profile(detail, allowed_tag_ids={tag['tagId'] for tag in catalog})
        except MindmapArtifactError as exc:
            raise ServiceException(data={'errorCode': 'AI_INPUT_INVALID'}, message=str(exc)) from exc

    @staticmethod
    def frozen_request_payload(request: Any, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        result = dict(payload if payload is not None else request.model_dump(by_alias=True, exclude_none=True))
        # A public body cannot supply this key: models ignore it and this helper
        # always replaces it with the private server attribute.
        result.pop(TEMPLATE_PROFILE_STORAGE_KEY, None)
        if request._template_profile is not None:
            result[TEMPLATE_PROFILE_STORAGE_KEY] = request._template_profile
        return result

    @staticmethod
    def _query(user_id: int, keyword: str | None = None) -> Select:
        # Walk only intact active directory trees, never through deleted parents,
        # orphaned rows, foreign owners, cycles or excessive legacy depth.
        folders = select(
            MindmapFolder.id,
            MindmapFolder.owner_id,
            literal(1).label('depth'),
            cast(case(
                (MindmapFolder.name.in_(TEMPLATE_FOLDER_NAMES), MindmapFolder.name),
                else_=literal(''),
            ), String(MAX_TEMPLATE_PATH_LENGTH)).label('template_path'),
        ).where(
            MindmapFolder.parent_id == 0,
            MindmapFolder.del_flag == '0',
        ).cte('ai_template_folders', recursive=True)
        folders = folders.union_all(select(
            MindmapFolder.id,
            MindmapFolder.owner_id,
            folders.c.depth + 1,
            cast(case(
                (MindmapFolder.name.in_(TEMPLATE_FOLDER_NAMES), MindmapFolder.name),
                (folders.c.template_path != '', folders.c.template_path + ' / ' + MindmapFolder.name),
                else_=literal(''),
            ), String(MAX_TEMPLATE_PATH_LENGTH)),
        ).join(folders, and_(
            MindmapFolder.parent_id == folders.c.id,
            MindmapFolder.owner_id == folders.c.owner_id,
        )).where(MindmapFolder.del_flag == '0', folders.c.depth < MAX_FOLDER_DEPTH))
        query = select(
            Mindmap.id, Mindmap.name, Mindmap.description, Mindmap.folder_id,
            MindmapFolder.name.label('folder_name'), folders.c.template_path.label('folder_path'),
            SysUser.nick_name.label('owner_name'), Mindmap.node_count, Mindmap.status,
            Mindmap.content_revision, Mindmap.update_time,
        ).join(folders, and_(
            folders.c.id == Mindmap.folder_id,
            folders.c.owner_id == Mindmap.owner_id,
        )).join(MindmapFolder, MindmapFolder.id == Mindmap.folder_id).outerjoin(
            SysUser, SysUser.user_id == Mindmap.owner_id,
        ).where(
            folders.c.template_path != '',
            Mindmap.del_flag == '0', Mindmap.status.in_((0, 1)),
            or_(Mindmap.owner_id == user_id, exists(select(MindmapCollaborator.id).where(
                MindmapCollaborator.mindmap_id == Mindmap.id,
                MindmapCollaborator.user_id == user_id,
            ))),
        )
        pattern = MindmapDao._literal_contains_pattern((keyword or '').strip())
        if pattern:
            query = query.where(or_(
                Mindmap.name.ilike(pattern, escape='\\'),
                Mindmap.description.ilike(pattern, escape='\\'),
            ))
        return query.order_by(Mindmap.update_time.desc(), Mindmap.id.desc())

    @classmethod
    async def list_templates(
        cls, db: AsyncSession, user_id: int, keyword: str | None = None,
        page_num: int = 1, page_size: int = 20,
    ) -> PageModel:
        result = await PageUtil.paginate(db, cls._query(user_id, keyword), page_num, page_size, True)
        result.rows = [MindmapAiTemplateSummaryModel.model_validate(row).model_dump(by_alias=True)
            for row in result.rows]
        return result

    @classmethod
    async def get_template(cls, db: AsyncSession, mindmap_id: int, user_id: int) -> dict[str, Any]:
        row = (await db.execute(cls._query(user_id).where(Mindmap.id == mindmap_id))).mappings().first()
        if row is None:
            raise ServiceException(message='模版不存在、已移出模版文件夹或无查看权限')
        # Reuse the canonical access check and structured tree loader. In schema
        # v2 the old ORM node_tree column is not the authoritative content.
        detail = await MindmapService.get_mindmap_detail_services(db, mindmap_id, user_id)
        if detail.status not in (0, 1) or detail.folder_id != row['folder_id']:
            raise ServiceException(message='模版状态已变更，请刷新后重新选择')
        if detail.content_state != 'ready':
            raise ServiceException(message='模版内容暂时无法读取，请稍后重试')
        result = dict(row)
        result.update(name=detail.name, content_revision=detail.content_revision, status=detail.status,
            node_tree=detail.node_tree, layout=detail.layout, theme=detail.theme)
        return MindmapAiTemplateDetailModel.model_validate(result).model_dump(by_alias=True)
