"""脑图结构化文档持久化服务。"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, case, or_, select, update

from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_content_dao import MindmapContentDao
from module_mindmap.dao.mindmap_tag_dao import MindmapTagDao
from module_mindmap.entity.do.mindmap_content_do import MindmapNode, MindmapNodeTag
from module_mindmap.entity.do.mindmap_tag_do import MindmapTag
from module_mindmap.service.mindmap_marker_tags import promote_legacy_marker_tags
from module_mindmap.service.mindmap_tag_identity import build_custom_tag_key
from module_mindmap.service.simple_mind_document_codec import (
    ENGINE_VERSION,
    SCHEMA_VERSION,
    SimpleMindDocumentCodec,
)
from utils.log_util import logger

STRUCTURED_CONTENT_CORRUPT_MESSAGE = '脑图结构化内容损坏，请联系管理员修复'

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and value != '' else None
    except (TypeError, ValueError):
        return None


def validate_tag_binding_access(
    tag: MindmapTag,
    owner_id: int,
    is_existing: bool,
    allow_disabled: bool = False,
) -> None:
    """校验文件可见标签，并允许原节点继续保留已停用标签。"""
    if tag.owner_id not in (0, owner_id):
        raise ValueError(f'标签“{tag.name}”不属于当前文件所有者')
    if tag.status == 1 and (is_existing or allow_disabled):
        return
    if tag.status != 0 and not is_existing:
        raise ValueError(f'标签“{tag.name}”已停用或归档，不能新增绑定')


def collect_tag_snapshots(node_tree: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """从已解析文档冻结标签定义，保留字段继承后的最终样式。"""
    root = node_tree.get('root') if isinstance(node_tree, dict) and node_tree.get('root') else node_tree
    if not isinstance(root, dict):
        return {}
    snapshots: dict[str, dict[str, Any]] = {}
    stack = [root]
    while stack:
        node = stack.pop()
        data = node.get('data') if isinstance(node, dict) else None
        for tag in (data.get('tag') if isinstance(data, dict) else []) or []:
            if not isinstance(tag, dict) or not tag.get('tagId'):
                continue
            snapshot = {
                key: tag[key]
                for key in (
                    'tagId', 'categoryId', 'uuid', 'tagKey', 'text', 'style', 'status',
                    'definitionRevision',
                )
                if key in tag
            }
            snapshot['style'] = dict(snapshot.get('style') or {})
            tag_key = str(tag['tagId'])
            snapshots.setdefault(tag_key, snapshot)
        stack.extend(child for child in (node.get('children') or []) if isinstance(child, dict))
    return snapshots


class MindmapDocumentService:
    """协调编解码、标签主数据和结构化表的事务写入。"""

    @classmethod
    async def persist_tree(
        cls,
        db: AsyncSession,
        file_id: int,
        root: dict[str, Any],
        owner_id: int,
        operator: str,
        allow_disabled_bindings: bool = False,
        *,
        for_update: bool = False,
    ) -> dict[str, Any]:
        encoded = SimpleMindDocumentCodec.encode(root)
        await promote_legacy_marker_tags(db, encoded)
        old_tag_ids, new_tag_ids = await cls._lock_and_resolve_tag_bindings(
            db,
            file_id,
            encoded.node_tags,
            owner_id,
            operator,
            allow_disabled_bindings,
        )
        metadata = await MindmapContentDao.replace_document(
            db,
            file_id,
            encoded,
            operator,
            for_update=for_update,
        )
        await cls._refresh_tag_usage(db, old_tag_ids | new_tag_ids)
        return {
            **metadata,
            'schema_version': SCHEMA_VERSION,
            'engine_name': 'simple-mind-map',
            'engine_version': ENGINE_VERSION,
        }

    @classmethod
    async def persist_tree_incremental(
        cls,
        db: AsyncSession,
        file_id: int,
        root: dict[str, Any],
        owner_id: int,
        operator: str,
        allow_disabled_bindings: bool = False,
    ) -> dict[str, Any]:
        """增量物化文档并保留节点、关系等已有主键。"""
        encoded = SimpleMindDocumentCodec.encode(root)
        await promote_legacy_marker_tags(db, encoded)
        old_tag_ids, new_tag_ids = await cls._lock_and_resolve_tag_bindings(
            db,
            file_id,
            encoded.node_tags,
            owner_id,
            operator,
            allow_disabled_bindings,
        )
        metadata = await MindmapContentDao.sync_document(
            db,
            file_id,
            encoded,
            operator,
            for_update=True,
        )
        await cls._refresh_tag_usage(db, old_tag_ids | new_tag_ids)
        return {
            **metadata,
            'schema_version': SCHEMA_VERSION,
            'engine_name': 'simple-mind-map',
            'engine_version': ENGINE_VERSION,
        }

    @classmethod
    async def load_tree(
        cls,
        db: AsyncSession,
        file_id: int,
        *,
        required: bool = False,
        for_update: bool = False,
    ) -> dict[str, Any] | None:
        try:
            document = await MindmapContentDao.load_document(
                db,
                file_id,
                for_update=for_update,
            )
            if not document:
                if required:
                    logger.error(f'脑图结构化内容完整性校验失败: file_id={file_id}, reason=节点记录不存在')
                    raise ServiceException(message=STRUCTURED_CONTENT_CORRUPT_MESSAGE)
                return None
            return SimpleMindDocumentCodec.decode(document)
        except ValueError as exc:
            logger.error(f'脑图结构化内容完整性校验失败: file_id={file_id}, reason={exc}')
            raise ServiceException(message=STRUCTURED_CONTENT_CORRUPT_MESSAGE) from exc

    @classmethod
    async def get_tag_snapshots(
        cls, db: AsyncSession, file_id: int, node_tree: dict[str, Any] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """冻结文件当前实际引用的标签定义，用于历史预览。"""
        snapshots = collect_tag_snapshots(node_tree or await cls.load_tree(db, file_id))
        if snapshots:
            return snapshots
        # 兼容尚未物化结构化内容的旧文件。
        tags = list((await db.execute(
            select(MindmapTag)
            .join(MindmapNodeTag, MindmapNodeTag.tag_id == MindmapTag.id)
            .where(MindmapNodeTag.file_id == file_id)
            .distinct()
        )).scalars())
        return {
            str(tag.id): {
                'tagId': tag.id,
                'categoryId': tag.category_id,
                'uuid': tag.uuid,
                'tagKey': tag.tag_key,
                'text': tag.name,
                'style': tag.style or {},
                'status': tag.status,
                'definitionRevision': tag.definition_revision,
            }
            for tag in tags
        }

    @classmethod
    async def delete_files(cls, db: AsyncSession, file_ids: list[int]) -> None:
        """删除结构化内容并同步标签使用量缓存。"""
        if not file_ids:
            return
        tag_id_query = (
            select(MindmapNodeTag.tag_id)
            .where(MindmapNodeTag.file_id.in_(file_ids))
            .order_by(MindmapNodeTag.tag_id.asc(), MindmapNodeTag.id.asc())
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        tag_ids = set((await db.execute(tag_id_query)).scalars())
        # 调用方已按 file_id 锁定 Mindmap。删除绑定前继续按 tag_id 锁定
        # 标签，和正文保存、标签治理保持统一的 Mindmap -> Tag -> binding 锁序。
        await MindmapTagDao.get_tags_by_ids(db, tag_ids, for_update=True)
        await MindmapContentDao.delete_document(db, file_ids, for_update=True)
        await cls._refresh_tag_usage(db, tag_ids)

    @classmethod
    async def _lock_and_resolve_tag_bindings(
        cls,
        db: AsyncSession,
        file_id: int,
        bindings: list[dict[str, Any]],
        owner_id: int,
        operator: str,
        allow_disabled_bindings: bool,
    ) -> tuple[set[int], set[int]]:
        """锁定旧、新标签后再校验绑定，阻断治理与正文保存的 TOCTOU。"""
        existing_bindings = await cls._load_existing_tag_bindings(
            db,
            file_id,
            for_update=True,
        )
        old_tag_query = (
            select(MindmapNodeTag.tag_id)
            .where(MindmapNodeTag.file_id == file_id)
            .order_by(MindmapNodeTag.tag_id.asc(), MindmapNodeTag.id.asc())
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        old_tag_ids = set((await db.execute(old_tag_query)).scalars())
        locked_context = await cls._prefetch_tag_binding_context(
            db,
            bindings,
            owner_id=owner_id,
            additional_tag_ids=old_tag_ids,
            for_update=True,
        )
        await cls._resolve_tag_bindings(
            db,
            bindings,
            owner_id,
            operator,
            existing_bindings,
            allow_disabled_bindings,
            cache=locked_context,
            context_locked=True,
        )
        new_tag_ids = {row['tag_id'] for row in bindings if row.get('tag_id')}
        return old_tag_ids, new_tag_ids

    @classmethod
    async def _resolve_tag_bindings(
        cls,
        db: AsyncSession,
        bindings: list[dict[str, Any]],
        owner_id: int,
        operator: str,
        existing_bindings: set[tuple[str, int]],
        allow_disabled_bindings: bool,
        *,
        cache: dict[str, MindmapTag] | None = None,
        context_locked: bool = False,
    ) -> None:
        if cache is None:
            cache = await cls._prefetch_tag_binding_context(db, bindings)
        deduplicated: list[dict[str, Any]] = []
        seen: set[tuple[str, int]] = set()
        for binding in bindings:
            tag = await cls._resolve_single_tag(
                db,
                binding.get('raw'),
                owner_id,
                operator,
                cache,
                context_locked=context_locked,
            )
            if not tag:
                continue
            raw = binding.get('raw') if isinstance(binding.get('raw'), dict) else {}
            if raw.get('tagId') or raw.get('id'):
                cache[f'id:{raw.get("tagId") or raw.get("id")}'] = tag
            if raw.get('uuid'):
                cache[f'uuid:{raw["uuid"]}'] = tag
            key = (binding['node_uid'], tag.id)
            validate_tag_binding_access(
                tag,
                owner_id,
                key in existing_bindings,
                allow_disabled=allow_disabled_bindings,
            )
            if key in seen:
                continue
            seen.add(key)
            binding['tag_id'] = tag.id
            deduplicated.append(binding)
        bindings[:] = deduplicated

    @staticmethod
    async def _load_existing_tag_bindings(
        db: AsyncSession,
        file_id: int,
        *,
        for_update: bool = False,
    ) -> set[tuple[str, int]]:
        query = (
            select(MindmapNode.node_uid, MindmapNodeTag.tag_id)
            .join(MindmapNodeTag, MindmapNodeTag.node_id == MindmapNode.id)
            .where(
                MindmapNode.file_id == file_id,
                MindmapNode.is_deleted == 0,
            )
            .order_by(MindmapNode.id.asc(), MindmapNodeTag.id.asc())
        )
        if for_update:
            query = query.with_for_update(read=True).execution_options(populate_existing=True)
        rows = (await db.execute(query)).all()
        return {(str(node_uid), tag_id) for node_uid, tag_id in rows}

    @staticmethod
    async def _prefetch_tag_binding_context(
        db: AsyncSession,
        bindings: list[dict[str, Any]],
        *,
        owner_id: int | None = None,
        additional_tag_ids: set[int] | None = None,
        for_update: bool = False,
    ) -> dict[str, MindmapTag]:
        """一次预取标签，避免大文档保存时逐标签查询。"""
        cache: dict[str, MindmapTag] = {}
        raw_values = [binding.get('raw') for binding in bindings]
        raw_dicts = [raw for raw in raw_values if isinstance(raw, dict)]
        tag_ids = set(additional_tag_ids or ()) | {
            tag_id
            for raw in raw_dicts
            if (tag_id := _optional_int(raw.get('tagId') or raw.get('id'))) is not None
        }
        tag_uuids = {str(raw['uuid']) for raw in raw_dicts if raw.get('uuid')}
        custom_names = {
            str(name).strip()[:200]
            for raw in raw_values
            if (
                (
                    isinstance(raw, dict)
                    and not (raw.get('tagId') or raw.get('id') or raw.get('uuid'))
                    and (name := raw.get('text')) is not None
                )
                or (not isinstance(raw, dict) and (name := raw) is not None)
            )
            and str(name).strip()
        }
        custom_tag_keys = {build_custom_tag_key(name) for name in custom_names}
        tag_conditions = []
        if tag_ids:
            tag_conditions.append(MindmapTag.id.in_(tag_ids))
        if tag_uuids:
            tag_conditions.append(MindmapTag.uuid.in_(tag_uuids))
        if owner_id is not None and custom_tag_keys:
            tag_conditions.append(and_(
                MindmapTag.owner_id == owner_id,
                MindmapTag.tag_key.in_(custom_tag_keys),
            ))
        if tag_conditions:
            query = (
                select(MindmapTag)
                .where(or_(*tag_conditions))
                .order_by(MindmapTag.id.asc())
            )
            if for_update:
                query = query.with_for_update().execution_options(populate_existing=True)
            prefetched_tags = list((await db.execute(query)).scalars())
        else:
            prefetched_tags = []
        for tag in prefetched_tags:
            cache[f'id:{tag.id}'] = tag
            if tag.uuid:
                cache[f'uuid:{tag.uuid}'] = tag
            cache[f'key:{tag.owner_id}:{tag.tag_key}'] = tag
        return cache

    @classmethod
    async def _resolve_single_tag(
        cls,
        db: AsyncSession,
        raw: Any,
        owner_id: int,
        operator: str,
        cache: dict[str, MindmapTag],
        *,
        context_locked: bool = False,
    ) -> MindmapTag | None:
        raw_dict = raw if isinstance(raw, dict) else {}
        tag_id = raw_dict.get('tagId') or raw_dict.get('id')
        tag_uuid = raw_dict.get('uuid')
        if not tag_id and not tag_uuid and (
            raw_dict.get('optionId') or raw_dict.get('fieldId')
        ):
            raise ValueError(
                '检测到旧版标签草稿缺少 tagId，请使用云端版本后重新编辑'
            )
        cache_key = f'id:{tag_id}' if tag_id else f'uuid:{tag_uuid}' if tag_uuid else ''
        if cache_key and cache_key in cache:
            return cache[cache_key]
        if context_locked and (tag_id or tag_uuid):
            identifier = tag_id or tag_uuid
            raise ValueError(f'标签不存在: {identifier}')
        tag = await MindmapContentDao.find_tag(db, tag_id=tag_id, tag_uuid=tag_uuid)
        if tag:
            if cache_key:
                cache[cache_key] = tag
            return tag
        if tag_id or tag_uuid:
            identifier = tag_id or tag_uuid
            raise ValueError(f'标签不存在: {identifier}')

        name = raw_dict.get('text') if raw_dict else raw
        if name is None or not str(name).strip():
            return None
        name = str(name).strip()[:200]
        tag_key = build_custom_tag_key(name)
        cache_key = f'key:{owner_id}:{tag_key}'
        if cache_key in cache:
            return cache[cache_key]
        tag = None
        if not context_locked:
            tag = (await db.execute(select(MindmapTag).where(
                MindmapTag.owner_id == owner_id,
                MindmapTag.tag_key == tag_key,
            ))).scalars().first()
        if not tag:
            style = raw_dict.get('style') if isinstance(raw_dict.get('style'), dict) else None
            tag = MindmapTag(
                uuid=str(uuid.uuid4()),
                tag_key=tag_key,
                name=name,
                category_id=None,
                owner_id=owner_id,
                style=style,
                description='由脑图节点自定义标签迁移生成',
                status=0,
                definition_revision=1,
                usage_node_count=0,
                usage_file_count=0,
                created_by=operator,
                created_time=datetime.now(),
                updated_time=datetime.now(),
                update_by=operator,
            )
            db.add(tag)
            await db.flush()
        cache[cache_key] = tag
        return tag

    @classmethod
    async def _refresh_tag_usage(cls, db: AsyncSession, tag_ids: set[int]) -> None:
        if not tag_ids:
            return
        rows = (await db.execute(
            select(
                MindmapNodeTag.tag_id,
                MindmapNodeTag.file_id,
            )
            .where(MindmapNodeTag.tag_id.in_(tag_ids))
            .order_by(
                MindmapNodeTag.tag_id.asc(),
                MindmapNodeTag.file_id.asc(),
                MindmapNodeTag.id.asc(),
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )).all()
        node_counts: dict[int, int] = {}
        file_ids_by_tag: dict[int, set[int]] = {}
        for tag_id, file_id in rows:
            node_counts[tag_id] = node_counts.get(tag_id, 0) + 1
            file_ids_by_tag.setdefault(tag_id, set()).add(file_id)
        file_counts = {
            tag_id: len(file_ids_by_tag.get(tag_id, set()))
            for tag_id in tag_ids
        }
        await db.execute(
            update(MindmapTag)
            .where(MindmapTag.id.in_(tag_ids))
            .values(
                usage_node_count=case(node_counts, value=MindmapTag.id, else_=0),
                usage_file_count=case(file_counts, value=MindmapTag.id, else_=0),
            )
        )
