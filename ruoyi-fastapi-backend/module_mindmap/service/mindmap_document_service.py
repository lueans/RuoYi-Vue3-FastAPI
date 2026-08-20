"""脑图结构化文档持久化服务。"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import case, func, or_, select, update

from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_content_dao import MindmapContentDao
from module_mindmap.entity.do.mindmap_content_do import MindmapNode, MindmapNodeTag
from module_mindmap.entity.do.mindmap_tag_do import MindmapTag
from module_mindmap.entity.do.mindmap_tag_field_do import MindmapTagField, MindmapTagFieldOption
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


def resolve_option_tag_styles(
    tag_style: dict[str, Any] | None,
    field_style: dict[str, Any] | None,
    option_fill: str | None,
    option_color: str | None,
    inherited_style: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """拆分字段继承值和标签自身覆盖值，并返回最终渲染样式。"""
    own_style = dict(tag_style or {})
    for key, value in (inherited_style or field_style or {}).items():
        if own_style.get(key) == value:
            own_style.pop(key, None)
    if option_fill is not None:
        own_style['fill'] = option_fill
    else:
        own_style.pop('fill', None)
    if option_color is not None:
        own_style['color'] = option_color
    else:
        own_style.pop('color', None)
    resolved_style = dict(field_style or {})
    resolved_style.update(own_style)
    return own_style, resolved_style


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
                    'tagId', 'uuid', 'tagKey', 'text', 'style', 'status', 'definitionRevision',
                )
                if key in tag
            }
            snapshot['style'] = dict(snapshot.get('style') or {})
            tag_key = str(tag['tagId'])
            snapshots.setdefault(tag_key, snapshot)
            if tag.get('fieldId') and tag.get('optionId'):
                snapshots[f'{tag_key}:{tag["fieldId"]}:{tag["optionId"]}'] = snapshot
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
    ) -> dict[str, Any]:
        encoded = SimpleMindDocumentCodec.encode(root)
        existing_bindings = await cls._load_existing_tag_bindings(db, file_id)
        old_tag_ids = set((await db.execute(
            select(MindmapNodeTag.tag_id).where(MindmapNodeTag.file_id == file_id).distinct()
        )).scalars())
        await cls._resolve_tag_bindings(
            db, encoded.node_tags, owner_id, operator, existing_bindings,
            allow_disabled_bindings,
        )
        new_tag_ids = {row['tag_id'] for row in encoded.node_tags if row.get('tag_id')}
        metadata = await MindmapContentDao.replace_document(db, file_id, encoded, operator)
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
        existing_bindings = await cls._load_existing_tag_bindings(db, file_id)
        old_tag_ids = set((await db.execute(
            select(MindmapNodeTag.tag_id).where(MindmapNodeTag.file_id == file_id).distinct()
        )).scalars())
        await cls._resolve_tag_bindings(
            db, encoded.node_tags, owner_id, operator, existing_bindings,
            allow_disabled_bindings,
        )
        new_tag_ids = {row['tag_id'] for row in encoded.node_tags if row.get('tag_id')}
        metadata = await MindmapContentDao.sync_document(db, file_id, encoded, operator)
        await cls._refresh_tag_usage(db, old_tag_ids | new_tag_ids)
        return {
            **metadata,
            'schema_version': SCHEMA_VERSION,
            'engine_name': 'simple-mind-map',
            'engine_version': ENGINE_VERSION,
        }

    @classmethod
    async def load_tree(
        cls, db: AsyncSession, file_id: int, *, required: bool = False,
    ) -> dict[str, Any] | None:
        try:
            document = await MindmapContentDao.load_document(db, file_id)
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
    async def get_inherited_tag_styles(
        cls, db: AsyncSession, tag_ids: set[int],
    ) -> dict[int, dict[str, Any]]:
        """批量返回标签关联字段的默认样式；一个标签异常关联多字段时稳定取首项。"""
        if not tag_ids:
            return {}
        rows = (await db.execute(
            select(MindmapTagFieldOption.tag_id, MindmapTagField.style)
            .join(MindmapTagField, MindmapTagField.id == MindmapTagFieldOption.field_id)
            .where(MindmapTagFieldOption.tag_id.in_(tag_ids))
            .order_by(MindmapTagFieldOption.id)
        )).all()
        inherited: dict[int, dict[str, Any]] = {}
        for tag_id, style in rows:
            if tag_id is not None:
                inherited.setdefault(tag_id, dict(style or {}))
        return inherited

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
        tag_ids = set((await db.execute(
            select(MindmapNodeTag.tag_id)
            .where(MindmapNodeTag.file_id.in_(file_ids))
            .distinct()
        )).scalars())
        await MindmapContentDao.delete_document(db, file_ids)
        await cls._refresh_tag_usage(db, tag_ids)

    @classmethod
    async def sync_option_tag_definition(
        cls, db: AsyncSession, option_id: int, operator: str,
        inherited_style: dict[str, Any] | None = None,
    ) -> tuple[MindmapTag | None, list[int], dict[str, Any]]:
        """确保字段选项关联统一标签，并同步名称与视觉样式。"""
        tag = await cls._resolve_single_tag(db, {'optionId': option_id}, 0, operator, {})
        if not tag:
            return None, [], {}
        option_row = (await db.execute(
            select(MindmapTagFieldOption, MindmapTagField)
            .join(MindmapTagField, MindmapTagField.id == MindmapTagFieldOption.field_id)
            .where(MindmapTagFieldOption.id == option_id)
        )).first()
        if not option_row:
            return None, [], {}
        option, field_model = option_row
        # mindmap_tag.style 只保存标签自身覆盖值。兼容旧数据时，移除过去
        # 物化进标签且仍等于字段默认值的属性，避免字段更新被旧副本遮蔽。
        style, resolved_style = resolve_option_tag_styles(
            tag.style,
            field_model.style,
            option.fill,
            option.color,
            inherited_style,
        )
        new_revision = (tag.definition_revision or 1) + 1
        await db.execute(update(MindmapTag).where(MindmapTag.id == tag.id).values(
            name=option.name,
            style=style or None,
            definition_revision=new_revision,
            update_by=operator,
            updated_time=datetime.now(),
        ))
        tag.name = option.name
        tag.style = style or None
        tag.definition_revision = new_revision
        affected_file_ids = list((await db.execute(
            select(MindmapNodeTag.file_id)
            .where(MindmapNodeTag.tag_id == tag.id)
            .distinct()
        )).scalars())
        return tag, affected_file_ids, resolved_style

    @classmethod
    async def _resolve_tag_bindings(
        cls,
        db: AsyncSession,
        bindings: list[dict[str, Any]],
        owner_id: int,
        operator: str,
        existing_bindings: set[tuple[str, int]],
        allow_disabled_bindings: bool,
    ) -> None:
        cache, option_map = await cls._prefetch_tag_binding_context(db, bindings)
        deduplicated: list[dict[str, Any]] = []
        seen: set[tuple[str, int]] = set()
        for binding in bindings:
            tag = await cls._resolve_single_tag(db, binding.get('raw'), owner_id, operator, cache)
            if not tag:
                continue
            raw = binding.get('raw') if isinstance(binding.get('raw'), dict) else {}
            if raw.get('tagId') or raw.get('id'):
                cache[f'id:{raw.get("tagId") or raw.get("id")}'] = tag
            if raw.get('uuid'):
                cache[f'uuid:{raw["uuid"]}'] = tag
            if raw.get('optionId'):
                cache[f'option:{raw["optionId"]}'] = tag
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
        cls._enrich_field_bindings(deduplicated, option_map, owner_id)
        bindings[:] = deduplicated

    @staticmethod
    def _enrich_field_bindings(
        bindings: list[dict[str, Any]],
        option_map: dict[int, tuple[MindmapTagFieldOption, MindmapTagField]],
        owner_id: int,
    ) -> None:
        """校验字段选项所有权和单选约束，并补齐结构化外键。"""
        selected_by_node_field: dict[tuple[str, int], set[int]] = {}
        for binding in bindings:
            raw = binding.get('raw') if isinstance(binding.get('raw'), dict) else {}
            option_id = raw.get('optionId')
            if not option_id:
                continue
            normalized_option_id = _optional_int(option_id)
            option_row = option_map.get(normalized_option_id) if normalized_option_id is not None else None
            if not option_row:
                raise ValueError(f'标签字段选项不存在: {option_id}')
            option, field_model = option_row
            if field_model.owner_id not in (0, owner_id):
                raise ValueError(f'标签字段“{field_model.name}”对当前文件不可见')
            if option.tag_id != binding['tag_id']:
                raise ValueError(f'字段选项 {option_id} 与标签 {binding["tag_id"]} 不匹配')
            if raw.get('fieldId') and int(raw['fieldId']) != option.field_id:
                raise ValueError(f'字段选项 {option_id} 不属于字段 {raw["fieldId"]}')
            binding['field_id'] = option.field_id
            binding['option_id'] = option.id
            key = (binding['node_uid'], option.field_id)
            selected_by_node_field.setdefault(key, set()).add(option.id)
            if field_model.select_mode == 'single' and len(selected_by_node_field[key]) > 1:
                raise ValueError(f'节点 {binding["node_uid"]} 的单选字段“{field_model.name}”存在多个选项')

    @staticmethod
    async def _load_existing_tag_bindings(
        db: AsyncSession,
        file_id: int,
    ) -> set[tuple[str, int]]:
        rows = (await db.execute(
            select(MindmapNode.node_uid, MindmapNodeTag.tag_id)
            .join(MindmapNodeTag, MindmapNodeTag.node_id == MindmapNode.id)
            .where(
                MindmapNode.file_id == file_id,
                MindmapNode.is_deleted == 0,
            )
        )).all()
        return {(str(node_uid), tag_id) for node_uid, tag_id in rows}

    @staticmethod
    async def _prefetch_tag_binding_context(
        db: AsyncSession,
        bindings: list[dict[str, Any]],
    ) -> tuple[dict[str, MindmapTag], dict[int, tuple[MindmapTagFieldOption, MindmapTagField]]]:
        """一次预取标签和字段选项，避免大文档保存时逐标签查询。"""
        cache: dict[str, MindmapTag] = {}
        raw_dicts = [
            binding['raw']
            for binding in bindings
            if isinstance(binding.get('raw'), dict)
        ]
        option_ids = {
            option_id
            for raw in raw_dicts
            if (option_id := _optional_int(raw.get('optionId'))) is not None
        }
        option_rows = (await db.execute(
            select(MindmapTagFieldOption, MindmapTagField)
            .join(MindmapTagField, MindmapTagField.id == MindmapTagFieldOption.field_id)
            .where(MindmapTagFieldOption.id.in_(option_ids))
        )).all() if option_ids else []
        option_map = {option.id: (option, field_model) for option, field_model in option_rows}
        tag_ids = {
            tag_id
            for raw in raw_dicts
            if (tag_id := _optional_int(raw.get('tagId') or raw.get('id'))) is not None
        }
        tag_ids.update(option.tag_id for option, _field in option_rows if option.tag_id)
        tag_uuids = {str(raw['uuid']) for raw in raw_dicts if raw.get('uuid')}
        tag_conditions = []
        if tag_ids:
            tag_conditions.append(MindmapTag.id.in_(tag_ids))
        if tag_uuids:
            tag_conditions.append(MindmapTag.uuid.in_(tag_uuids))
        prefetched_tags = list((await db.execute(
            select(MindmapTag).where(or_(*tag_conditions))
        )).scalars()) if tag_conditions else []
        for tag in prefetched_tags:
            cache[f'id:{tag.id}'] = tag
            if tag.uuid:
                cache[f'uuid:{tag.uuid}'] = tag
        for option, _field in option_rows:
            if option.tag_id and (tag := cache.get(f'id:{option.tag_id}')):
                cache[f'option:{option.id}'] = tag
        return cache, option_map

    @classmethod
    async def _resolve_single_tag(  # noqa: PLR0912
        cls,
        db: AsyncSession,
        raw: Any,
        owner_id: int,
        operator: str,
        cache: dict[str, MindmapTag],
    ) -> MindmapTag | None:
        raw_dict = raw if isinstance(raw, dict) else {}
        tag_id = raw_dict.get('tagId') or raw_dict.get('id')
        tag_uuid = raw_dict.get('uuid')
        cache_key = f'id:{tag_id}' if tag_id else f'uuid:{tag_uuid}' if tag_uuid else ''
        if cache_key and cache_key in cache:
            return cache[cache_key]
        tag = await MindmapContentDao.find_tag(db, tag_id=tag_id, tag_uuid=tag_uuid)
        if tag:
            if cache_key:
                cache[cache_key] = tag
            return tag
        if tag_id or tag_uuid:
            identifier = tag_id or tag_uuid
            raise ValueError(f'标签不存在: {identifier}')

        option_id = raw_dict.get('optionId')
        if option_id:
            option_cache_key = f'option:{option_id}'
            if option_cache_key in cache:
                return cache[option_cache_key]
            option_row = (await db.execute(
                select(MindmapTagFieldOption, MindmapTagField)
                .join(MindmapTagField, MindmapTagField.id == MindmapTagFieldOption.field_id)
                .where(MindmapTagFieldOption.id == option_id)
            )).first()
            if option_row:
                option, field_model = option_row
                if option.tag_id:
                    tag = await MindmapContentDao.find_tag(db, tag_id=option.tag_id)
                    if tag:
                        return tag
                tag_key = f'field_{field_model.field_key}_{option.option_key}'[:100]
                tag = (await db.execute(select(MindmapTag).where(
                    MindmapTag.owner_id == field_model.owner_id,
                    MindmapTag.tag_key == tag_key,
                ))).scalars().first()
                if not tag:
                    style = {}
                    if option.fill is not None:
                        style['fill'] = option.fill
                    if option.color is not None:
                        style['color'] = option.color
                    tag = MindmapTag(
                        uuid=str(uuid.uuid4()),
                        tag_key=tag_key,
                        name=option.name,
                        category_id=None,
                        owner_id=field_model.owner_id,
                        style=style or None,
                        description=f'由标签字段“{field_model.name}”选项迁移生成',
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
                option.tag_id = tag.id
                await db.flush()
                cache[option_cache_key] = tag
                return tag

        name = raw_dict.get('text') if raw_dict else raw
        if name is None or not str(name).strip():
            return None
        name = str(name).strip()[:200]
        tag_key = build_custom_tag_key(name)
        cache_key = f'key:{owner_id}:{tag_key}'
        if cache_key in cache:
            return cache[cache_key]
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
                func.count(MindmapNodeTag.id),
                func.count(func.distinct(MindmapNodeTag.file_id)),
            )
            .where(MindmapNodeTag.tag_id.in_(tag_ids))
            .group_by(MindmapNodeTag.tag_id)
        )).all()
        counts = {tag_id: (node_count, file_count) for tag_id, node_count, file_count in rows}
        node_counts = {tag_id: counts.get(tag_id, (0, 0))[0] for tag_id in tag_ids}
        file_counts = {tag_id: counts.get(tag_id, (0, 0))[1] for tag_id in tag_ids}
        await db.execute(
            update(MindmapTag)
            .where(MindmapTag.id.in_(tag_ids))
            .values(
                usage_node_count=case(node_counts, value=MindmapTag.id, else_=0),
                usage_file_count=case(file_counts, value=MindmapTag.id, else_=0),
            )
        )
