"""脑图结构化内容 DAO。"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, insert, or_, select

from module_mindmap.entity.do.mindmap_content_do import (
    MindmapAsset,
    MindmapChangeLog,
    MindmapGroup,
    MindmapGroupMember,
    MindmapNode,
    MindmapNodeTag,
    MindmapRelation,
    MindmapSummary,
)
from module_mindmap.entity.do.mindmap_tag_do import MindmapTag
from module_mindmap.service.simple_mind_document_codec import EncodedDocument

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

WRITE_BATCH_SIZE = 1_000


def _chunks(rows: list[dict[str, Any]], size: int = WRITE_BATCH_SIZE) -> list[list[dict[str, Any]]]:
    return [rows[index:index + size] for index in range(0, len(rows), size)]


def order_document_node_levels(nodes: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """按父子层级拓扑排序节点，供批量写入使用，并验证树结构完整性。"""
    if not nodes:
        return []
    by_uid: dict[str, dict[str, Any]] = {}
    children_by_parent: dict[str, list[dict[str, Any]]] = {}
    roots: list[dict[str, Any]] = []
    for row in nodes:
        node_uid = str(row.get('node_uid') or '')
        if not node_uid:
            raise ValueError('脑图节点缺少稳定 UID')
        if node_uid in by_uid:
            raise ValueError(f'脑图节点 UID 重复: {node_uid}')
        by_uid[node_uid] = row
        parent_uid = row.get('parent_uid')
        if parent_uid is None:
            roots.append(row)
        else:
            children_by_parent.setdefault(str(parent_uid), []).append(row)
    if len(roots) != 1:
        raise ValueError('脑图必须且只能包含一个根节点')
    missing_parents = set(children_by_parent) - set(by_uid)
    if missing_parents:
        raise ValueError(f'脑图节点缺失父节点: {sorted(missing_parents)[0]}')

    levels = []
    visited: set[str] = set()
    current = roots
    while current:
        levels.append(current)
        following = []
        for row in current:
            node_uid = str(row['node_uid'])
            if node_uid in visited:
                raise ValueError('脑图节点包含循环')
            visited.add(node_uid)
            following.extend(children_by_parent.get(node_uid, ()))
        current = following
    if len(visited) != len(nodes):
        raise ValueError('脑图节点包含循环或不可达节点')
    return levels


class MindmapContentDao:
    """结构化脑图内容的批量读写。"""

    @staticmethod
    async def _insert_nodes_by_level(
        db: AsyncSession,
        file_id: int,
        rows: list[dict[str, Any]],
        operator: str,
        now: datetime,
    ) -> dict[str, MindmapNode]:
        """按父子层级分块插入节点，并批量回读自增 ID。"""
        uid_to_node: dict[str, MindmapNode] = {}
        for level in order_document_node_levels(rows):
            values = [
                {
                    'file_id': file_id,
                    'node_uid': row['node_uid'],
                    'parent_id': uid_to_node[row['parent_uid']].id if row.get('parent_uid') else None,
                    'sort_order': row.get('sort_order', 0),
                    'text_content': row.get('text_content'),
                    'text_plain': row.get('text_plain'),
                    'text_format': row.get('text_format', 'plain'),
                    'is_expanded': 1 if row.get('is_expanded', True) else 0,
                    'direction': row.get('direction'),
                    'custom_left': row.get('custom_left'),
                    'custom_top': row.get('custom_top'),
                    'custom_text_width': row.get('custom_text_width'),
                    'content_data': row.get('content_data'),
                    'style_data': row.get('style_data'),
                    'extension_data': row.get('extension_data'),
                    'envelope_data': row.get('envelope_data'),
                    'payload_schema_version': row.get('payload_schema_version', 1),
                    'node_revision': 1,
                    'is_deleted': 0,
                    'create_by': operator,
                    'create_time': now,
                    'update_by': operator,
                    'update_time': now,
                }
                for row in level
            ]
            for batch in _chunks(values):
                await db.execute(insert(MindmapNode), batch)
                node_uids = [row['node_uid'] for row in batch]
                inserted = list((await db.execute(
                    select(MindmapNode).where(
                        MindmapNode.file_id == file_id,
                        MindmapNode.node_uid.in_(node_uids),
                    )
                )).scalars())
                uid_to_node.update({node.node_uid: node for node in inserted})
                if len(inserted) != len(batch):
                    raise RuntimeError('脑图节点批量写入后回读数量不一致')
        return uid_to_node

    @staticmethod
    async def _insert_node_tags(
        db: AsyncSession,
        file_id: int,
        rows: list[dict[str, Any]],
        uid_to_node: dict[str, MindmapNode],
        operator: str,
        now: datetime,
    ) -> None:
        """使用 executemany 批量写入标签绑定，避免高标签密度文档逐行往返。"""
        values = [
            {
                'file_id': file_id,
                'node_id': uid_to_node[row['node_uid']].id,
                'tag_id': row['tag_id'],
                'sort_order': row.get('sort_order', 0),
                'placement': row.get('placement'),
                'align': row.get('align'),
                'created_by': operator,
                'created_time': now,
            }
            for row in rows
            if row.get('tag_id') and row['node_uid'] in uid_to_node
        ]
        if values:
            await db.execute(insert(MindmapNodeTag), values)

    @classmethod
    async def has_nodes(cls, db: AsyncSession, file_id: int) -> bool:
        return (await db.execute(
            select(MindmapNode.id).where(
                MindmapNode.file_id == file_id,
                MindmapNode.is_deleted == 0,
            ).limit(1)
        )).first() is not None

    @classmethod
    async def get_node_revisions(cls, db: AsyncSession, file_id: int) -> dict[str, int]:
        rows = (await db.execute(select(
            MindmapNode.node_uid, MindmapNode.node_revision,
        ).where(
            MindmapNode.file_id == file_id,
            MindmapNode.is_deleted == 0,
        ))).all()
        return dict(rows)

    @classmethod
    async def delete_document(cls, db: AsyncSession, file_ids: list[int]) -> None:
        if not file_ids:
            return
        group_ids = list((await db.execute(
            select(MindmapGroup.id).where(MindmapGroup.file_id.in_(file_ids))
        )).scalars())
        if group_ids:
            await db.execute(delete(MindmapGroupMember).where(MindmapGroupMember.group_id.in_(group_ids)))
        for model in (
            MindmapNodeTag, MindmapRelation, MindmapSummary,
            MindmapGroup, MindmapAsset, MindmapNode, MindmapChangeLog,
        ):
            await db.execute(delete(model).where(model.file_id.in_(file_ids)))

    @classmethod
    async def replace_document(
        cls,
        db: AsyncSession,
        file_id: int,
        document: EncodedDocument,
        operator: str,
    ) -> dict[str, int]:
        """在当前事务内完整替换一个文件的结构化内容。"""
        await cls.delete_document(db, [file_id])
        now = datetime.now()
        uid_to_node = await cls._insert_nodes_by_level(
            db,
            file_id,
            document.nodes,
            operator,
            now,
        )

        await cls._insert_node_tags(db, file_id, document.node_tags, uid_to_node, operator, now)

        for row in document.relations:
            source = uid_to_node.get(row['source_uid'])
            target = uid_to_node.get(row['target_uid'])
            if not source or not target:
                continue
            db.add(MindmapRelation(
                relation_uid=row['relation_uid'],
                file_id=file_id,
                relation_type=row.get('relation_type', 'associative_line'),
                source_node_id=source.id,
                target_node_id=target.id,
                text=row.get('text'),
                control_data=row.get('control_data'),
                style_data=row.get('style_data'),
                sort_order=row.get('sort_order', 0),
                revision=1,
                create_time=now,
                update_time=now,
            ))

        for row in document.summaries:
            owner = uid_to_node.get(row['owner_uid'])
            if not owner:
                continue
            db.add(MindmapSummary(
                summary_uid=row['summary_uid'],
                file_id=file_id,
                owner_node_id=owner.id,
                start_child_id=uid_to_node.get(row.get('start_child_uid')).id
                if uid_to_node.get(row.get('start_child_uid')) else None,
                end_child_id=uid_to_node.get(row.get('end_child_uid')).id
                if uid_to_node.get(row.get('end_child_uid')) else None,
                content_data=row.get('payload'),
                style_data=None,
                extension_data=None,
                sort_order=row.get('sort_order', 0),
                revision=1,
                create_time=now,
                update_time=now,
            ))

        for row in document.groups:
            parent = uid_to_node.get(row.get('parent_uid'))
            members = [uid_to_node[uid] for uid in row.get('member_uids', []) if uid in uid_to_node]
            if not parent or not members:
                continue
            payload = row.get('payload') or {}
            group = MindmapGroup(
                group_uid=row['group_uid'],
                file_id=file_id,
                parent_node_id=parent.id,
                group_type=row.get('group_type', 'outer_frame'),
                text=payload.get('text'),
                style_data=payload.get('style'),
                extension_data=payload,
                revision=1,
                create_time=now,
                update_time=now,
            )
            db.add(group)
            await db.flush()
            for order, node in enumerate(members):
                db.add(MindmapGroupMember(group_id=group.id, node_id=node.id, sort_order=order))

        for row in document.assets:
            db.add(MindmapAsset(
                file_id=file_id,
                asset_key=row['asset_key'],
                asset_type=row.get('asset_type', 'image'),
                storage_type=row.get('storage_type', 'url'),
                uri=row.get('uri'),
                object_key=row.get('object_key'),
                mime_type=row.get('mime_type'),
                size=row.get('size'),
                sha256=row.get('sha256'),
                metadata_json=row.get('metadata'),
                create_time=now,
            ))

        await db.flush()
        return {
            'root_node_id': uid_to_node[document.root_uid].id if document.root_uid in uid_to_node else None,
            'node_count': len(uid_to_node),
        }

    @staticmethod
    def _apply_values(model: Any, values: dict[str, Any]) -> bool:
        changed = False
        for key, value in values.items():
            if getattr(model, key) != value:
                setattr(model, key, value)
                changed = True
        return changed

    @classmethod
    async def sync_document(
        cls,
        db: AsyncSession,
        file_id: int,
        document: EncodedDocument,
        operator: str,
    ) -> dict[str, Any]:
        """增量物化完整文档，保留已有节点和关系的稳定数据库主键。"""
        now = datetime.now()
        existing_nodes = list((await db.execute(
            select(MindmapNode).where(MindmapNode.file_id == file_id)
        )).scalars())
        uid_to_node = {node.node_uid: node for node in existing_nodes}
        changed_nodes: list[dict[str, Any]] = []

        desired_uids = {row['node_uid'] for row in document.nodes}
        for level in order_document_node_levels(document.nodes):
            for row in level:
                parent_uid = row.get('parent_uid')
                node = uid_to_node.get(row['node_uid'])
                is_new = node is None
                if is_new:
                    node = MindmapNode(
                        file_id=file_id,
                        node_uid=row['node_uid'],
                        node_revision=1,
                        create_by=operator,
                        create_time=now,
                    )
                    db.add(node)
                    uid_to_node[row['node_uid']] = node
                values = {
                    'parent_id': uid_to_node[parent_uid].id if parent_uid else None,
                    'sort_order': row.get('sort_order', 0),
                    'text_content': row.get('text_content'),
                    'text_plain': row.get('text_plain'),
                    'text_format': row.get('text_format', 'plain'),
                    'is_expanded': 1 if row.get('is_expanded', True) else 0,
                    'direction': row.get('direction'),
                    'custom_left': row.get('custom_left'),
                    'custom_top': row.get('custom_top'),
                    'custom_text_width': row.get('custom_text_width'),
                    'content_data': row.get('content_data'),
                    'style_data': row.get('style_data'),
                    'extension_data': row.get('extension_data'),
                    'envelope_data': row.get('envelope_data'),
                    'payload_schema_version': row.get('payload_schema_version', 1),
                    'is_deleted': 0,
                    'deleted_time': None,
                }
                changed = cls._apply_values(node, values)
                if is_new:
                    node.update_by = operator
                    node.update_time = now
                    changed_nodes.append({'nodeUid': node.node_uid, 'nodeRevision': 1, 'action': 'create'})
                elif changed:
                    node.node_revision = (node.node_revision or 1) + 1
                    node.update_by = operator
                    node.update_time = now
                    changed_nodes.append({
                        'nodeUid': node.node_uid,
                        'nodeRevision': node.node_revision,
                        'action': 'update',
                    })
            await db.flush()

        for node in existing_nodes:
            if node.node_uid not in desired_uids and not node.is_deleted:
                node.is_deleted = 1
                node.deleted_time = now
                node.node_revision = (node.node_revision or 1) + 1
                node.update_by = operator
                node.update_time = now
                changed_nodes.append({
                    'nodeUid': node.node_uid,
                    'nodeRevision': node.node_revision,
                    'action': 'delete',
                })

        # 标签绑定没有独立 revision，按当前物化结果重建；节点主键保持不变。
        await db.execute(delete(MindmapNodeTag).where(MindmapNodeTag.file_id == file_id))
        await cls._insert_node_tags(db, file_id, document.node_tags, uid_to_node, operator, now)

        await cls._sync_relations(db, file_id, document, uid_to_node, now)
        await cls._sync_summaries(db, file_id, document, uid_to_node, now)
        await cls._sync_groups(db, file_id, document, uid_to_node, now)
        await cls._sync_assets(db, file_id, document, now)
        await db.flush()
        root = uid_to_node.get(document.root_uid)
        return {
            'root_node_id': root.id if root else None,
            'node_count': len(desired_uids),
            'changed_nodes': changed_nodes,
        }

    @classmethod
    async def _sync_relations(
        cls, db: AsyncSession, file_id: int, document: EncodedDocument,
        uid_to_node: dict[str, MindmapNode], now: datetime,
    ) -> None:
        existing = list((await db.execute(
            select(MindmapRelation).where(MindmapRelation.file_id == file_id)
        )).scalars())
        by_uid = {row.relation_uid: row for row in existing}
        desired = {row['relation_uid'] for row in document.relations}
        for row in document.relations:
            source = uid_to_node.get(row['source_uid'])
            target = uid_to_node.get(row['target_uid'])
            if not source or not target:
                continue
            model = by_uid.get(row['relation_uid'])
            if not model:
                model = MindmapRelation(
                    file_id=file_id, relation_uid=row['relation_uid'], revision=1, create_time=now,
                )
                db.add(model)
            changed = cls._apply_values(model, {
                'relation_type': row.get('relation_type', 'associative_line'),
                'source_node_id': source.id,
                'target_node_id': target.id,
                'text': row.get('text'),
                'control_data': row.get('control_data'),
                'style_data': row.get('style_data'),
                'sort_order': row.get('sort_order', 0),
            })
            if model.id and changed:
                model.revision = (model.revision or 1) + 1
            if changed:
                model.update_time = now
        obsolete = [row.id for row in existing if row.relation_uid not in desired]
        if obsolete:
            await db.execute(delete(MindmapRelation).where(MindmapRelation.id.in_(obsolete)))

    @classmethod
    async def _sync_summaries(
        cls, db: AsyncSession, file_id: int, document: EncodedDocument,
        uid_to_node: dict[str, MindmapNode], now: datetime,
    ) -> None:
        existing = list((await db.execute(
            select(MindmapSummary).where(MindmapSummary.file_id == file_id)
        )).scalars())
        by_uid = {row.summary_uid: row for row in existing}
        desired = {row['summary_uid'] for row in document.summaries}
        for row in document.summaries:
            owner = uid_to_node.get(row['owner_uid'])
            if not owner:
                continue
            model = by_uid.get(row['summary_uid'])
            if not model:
                model = MindmapSummary(
                    file_id=file_id, summary_uid=row['summary_uid'], revision=1, create_time=now,
                )
                db.add(model)
            start = uid_to_node.get(row.get('start_child_uid'))
            end = uid_to_node.get(row.get('end_child_uid'))
            changed = cls._apply_values(model, {
                'owner_node_id': owner.id,
                'start_child_id': start.id if start else None,
                'end_child_id': end.id if end else None,
                'content_data': row.get('payload') or {},
                'style_data': None,
                'extension_data': None,
                'sort_order': row.get('sort_order', 0),
            })
            if model.id and changed:
                model.revision = (model.revision or 1) + 1
            if changed:
                model.update_time = now
        obsolete = [row.id for row in existing if row.summary_uid not in desired]
        if obsolete:
            await db.execute(delete(MindmapSummary).where(MindmapSummary.id.in_(obsolete)))

    @classmethod
    async def _sync_groups(
        cls, db: AsyncSession, file_id: int, document: EncodedDocument,
        uid_to_node: dict[str, MindmapNode], now: datetime,
    ) -> None:
        existing = list((await db.execute(
            select(MindmapGroup).where(MindmapGroup.file_id == file_id)
        )).scalars())
        by_uid = {row.group_uid: row for row in existing}
        existing_group_ids = [row.id for row in existing]
        existing_members = list((await db.execute(
            select(MindmapGroupMember)
            .where(MindmapGroupMember.group_id.in_(existing_group_ids))
            .order_by(MindmapGroupMember.group_id, MindmapGroupMember.sort_order)
        )).scalars()) if existing_group_ids else []
        member_ids_by_group: dict[int, list[int]] = {}
        for member in existing_members:
            member_ids_by_group.setdefault(member.group_id, []).append(member.node_id)
        desired = {row['group_uid'] for row in document.groups}
        obsolete_ids = [row.id for row in existing if row.group_uid not in desired]
        if obsolete_ids:
            await db.execute(delete(MindmapGroupMember).where(MindmapGroupMember.group_id.in_(obsolete_ids)))
            await db.execute(delete(MindmapGroup).where(MindmapGroup.id.in_(obsolete_ids)))
        for row in document.groups:
            parent = uid_to_node.get(row.get('parent_uid'))
            members = [uid_to_node[uid] for uid in row.get('member_uids', []) if uid in uid_to_node]
            if not parent or not members:
                continue
            payload = row.get('payload') or {}
            model = by_uid.get(row['group_uid'])
            is_new = model is None
            if is_new:
                model = MindmapGroup(
                    file_id=file_id, group_uid=row['group_uid'], revision=1, create_time=now,
                )
                db.add(model)
                await db.flush()
            changed = cls._apply_values(model, {
                'parent_node_id': parent.id,
                'group_type': row.get('group_type', 'outer_frame'),
                'text': payload.get('text'),
                'style_data': payload.get('style'),
                'extension_data': payload,
            })
            desired_member_ids = [node.id for node in members]
            membership_changed = member_ids_by_group.get(model.id, []) != desired_member_ids
            if not is_new and (changed or membership_changed):
                model.revision = (model.revision or 1) + 1
            if changed or membership_changed:
                model.update_time = now
            if membership_changed:
                await db.execute(delete(MindmapGroupMember).where(MindmapGroupMember.group_id == model.id))
                for order, node in enumerate(members):
                    db.add(MindmapGroupMember(group_id=model.id, node_id=node.id, sort_order=order))

    @classmethod
    async def _sync_assets(
        cls, db: AsyncSession, file_id: int, document: EncodedDocument, now: datetime,
    ) -> None:
        existing = list((await db.execute(
            select(MindmapAsset).where(MindmapAsset.file_id == file_id)
        )).scalars())
        by_key = {row.asset_key: row for row in existing}
        desired = {row['asset_key'] for row in document.assets}
        for row in document.assets:
            model = by_key.get(row['asset_key'])
            if not model:
                model = MindmapAsset(file_id=file_id, asset_key=row['asset_key'], create_time=now)
                db.add(model)
            cls._apply_values(model, {
                'asset_type': row.get('asset_type', 'image'),
                'storage_type': row.get('storage_type', 'url'),
                'uri': row.get('uri'),
                'object_key': row.get('object_key'),
                'mime_type': row.get('mime_type'),
                'size': row.get('size'),
                'sha256': row.get('sha256'),
                'metadata_json': row.get('metadata'),
            })
        obsolete = [row.id for row in existing if row.asset_key not in desired]
        if obsolete:
            await db.execute(delete(MindmapAsset).where(MindmapAsset.id.in_(obsolete)))

    @classmethod
    async def get_change_by_mutation(
        cls, db: AsyncSession, file_id: int, client_mutation_id: str,
    ) -> MindmapChangeLog | None:
        return (await db.execute(select(MindmapChangeLog).where(
            MindmapChangeLog.file_id == file_id,
            MindmapChangeLog.client_mutation_id == client_mutation_id,
        ))).scalars().first()

    @classmethod
    async def get_changes_after(
        cls, db: AsyncSession, file_id: int, after_revision: int, limit: int = 500,
    ) -> list[MindmapChangeLog]:
        return list((await db.execute(
            select(MindmapChangeLog)
            .where(MindmapChangeLog.file_id == file_id, MindmapChangeLog.revision > after_revision)
            .order_by(MindmapChangeLog.revision)
            .limit(limit)
        )).scalars())

    @classmethod
    async def load_document(  # noqa: PLR0912, PLR0915
        cls, db: AsyncSession, file_id: int,
    ) -> EncodedDocument | None:
        node_models = list((await db.execute(
            select(MindmapNode).where(
                MindmapNode.file_id == file_id,
                MindmapNode.is_deleted == 0,
            ).order_by(MindmapNode.parent_id, MindmapNode.sort_order, MindmapNode.id)
        )).scalars())
        if not node_models:
            return None

        id_to_uid = {node.id: node.node_uid for node in node_models}
        if any(
            node.parent_id is not None and node.parent_id not in id_to_uid
            for node in node_models
        ):
            raise ValueError('脑图节点引用不存在或已删除的父节点')
        nodes = [{
            'node_uid': node.node_uid,
            'parent_uid': id_to_uid.get(node.parent_id),
            'sort_order': node.sort_order,
            'text_content': node.text_content,
            'text_plain': node.text_plain,
            'text_format': node.text_format,
            'is_expanded': bool(node.is_expanded),
            'direction': node.direction,
            'custom_left': node.custom_left,
            'custom_top': node.custom_top,
            'custom_text_width': node.custom_text_width,
            'content_data': node.content_data,
            'style_data': node.style_data,
            'extension_data': node.extension_data,
            'envelope_data': node.envelope_data,
            'payload_schema_version': node.payload_schema_version,
        } for node in node_models]

        tag_rows = (await db.execute(
            select(MindmapNodeTag, MindmapTag)
            .join(MindmapTag, MindmapTag.id == MindmapNodeTag.tag_id)
            .where(MindmapNodeTag.file_id == file_id)
            .order_by(MindmapNodeTag.node_id, MindmapNodeTag.sort_order)
        )).all()
        node_tags = []
        for binding, tag in tag_rows:
            resolved = {
                'tagId': tag.id,
                'uuid': tag.uuid,
                'tagKey': tag.tag_key,
                'text': tag.name,
                'style': dict(tag.style or {}),
                'status': tag.status,
                'definitionRevision': tag.definition_revision,
            }
            node_tags.append({
                'node_uid': id_to_uid.get(binding.node_id),
                'sort_order': binding.sort_order,
                'placement': binding.placement,
                'align': binding.align,
                'resolved': resolved,
            })

        relation_models = list((await db.execute(
            select(MindmapRelation).where(MindmapRelation.file_id == file_id)
        )).scalars())
        relations = [{
            'relation_uid': row.relation_uid,
            'relation_type': row.relation_type,
            'source_uid': id_to_uid.get(row.source_node_id),
            'target_uid': id_to_uid.get(row.target_node_id),
            'text': row.text,
            'control_data': row.control_data,
            'style_data': row.style_data,
            'sort_order': row.sort_order,
        } for row in relation_models]

        summary_models = list((await db.execute(
            select(MindmapSummary).where(MindmapSummary.file_id == file_id)
        )).scalars())
        if any(
            (row.start_child_id is not None and row.start_child_id not in id_to_uid)
            or (row.end_child_id is not None and row.end_child_id not in id_to_uid)
            for row in summary_models
        ):
            raise ValueError('脑图概要范围引用不存在或已删除的节点')
        summaries = [{
            'summary_uid': row.summary_uid,
            'owner_uid': id_to_uid.get(row.owner_node_id),
            'start_child_uid': id_to_uid.get(row.start_child_id),
            'end_child_uid': id_to_uid.get(row.end_child_id),
            'payload': row.content_data or {},
            'sort_order': row.sort_order,
        } for row in summary_models]

        group_models = list((await db.execute(
            select(MindmapGroup).where(MindmapGroup.file_id == file_id)
        )).scalars())
        group_ids = [group.id for group in group_models]
        member_models = list((await db.execute(
            select(MindmapGroupMember)
            .where(MindmapGroupMember.group_id.in_(group_ids))
            .order_by(MindmapGroupMember.group_id, MindmapGroupMember.sort_order)
        )).scalars()) if group_ids else []
        members_by_group: dict[int, list[MindmapGroupMember]] = {}
        for member in member_models:
            members_by_group.setdefault(member.group_id, []).append(member)
        groups = []
        for group in group_models:
            members = members_by_group.get(group.id, [])
            payload = dict(group.extension_data or {})
            if group.text is not None:
                payload['text'] = group.text
            if group.style_data is not None:
                payload['style'] = group.style_data
            groups.append({
                'group_uid': group.group_uid,
                'parent_uid': id_to_uid.get(group.parent_node_id),
                'group_type': group.group_type,
                'payload': payload,
                'member_uids': [id_to_uid.get(member.node_id) for member in members],
            })

        asset_models = list((await db.execute(
            select(MindmapAsset).where(MindmapAsset.file_id == file_id)
        )).scalars())
        assets = [{
            'asset_key': row.asset_key,
            'asset_type': row.asset_type,
            'storage_type': row.storage_type,
            'uri': row.uri,
            'object_key': row.object_key,
            'mime_type': row.mime_type,
            'size': row.size,
            'sha256': row.sha256,
            'metadata': row.metadata_json,
        } for row in asset_models]

        root = next((node for node in node_models if node.parent_id is None), node_models[0])
        return EncodedDocument(
            nodes=nodes,
            node_tags=node_tags,
            relations=relations,
            summaries=summaries,
            groups=groups,
            assets=assets,
            root_uid=root.node_uid,
        )

    @classmethod
    async def find_tag(
        cls, db: AsyncSession, *, tag_id: int | None = None, tag_uuid: str | None = None,
    ) -> MindmapTag | None:
        conditions = []
        if tag_id:
            conditions.append(MindmapTag.id == tag_id)
        if tag_uuid:
            conditions.append(MindmapTag.uuid == tag_uuid)
        if not conditions:
            return None
        return (await db.execute(select(MindmapTag).where(or_(*conditions)))).scalars().first()
