"""脑图版本历史服务层"""
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import CrudResponseModel, PageModel
from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_dao import MindmapDao
from module_mindmap.dao.mindmap_version_dao import MindmapVersionDao
from module_mindmap.entity.vo.mindmap_version_vo import (
    MindmapVersionModel,
    MindmapVersionSaveModel,
)
from module_mindmap.service.mindmap_document_service import MindmapDocumentService
from module_mindmap.service.mindmap_tag_portability import MindmapTagPortabilityService
from module_mindmap.service.simple_mind_document_codec import SCHEMA_VERSION
from utils.common_util import CamelCaseUtil
from utils.log_util import logger

# 草稿版本保留数量上限
MAX_DRAFT_VERSIONS = 10
DRAFT_MIN_INTERVAL_SECONDS = 60


def _apply_tag_snapshots(node_tree: dict, tag_snapshots: dict | None) -> dict:
    """仅为历史预览覆写标签定义，保留节点局部 placement/align。"""
    if not tag_snapshots:
        return node_tree
    tree = json.loads(json.dumps(node_tree, ensure_ascii=False))

    def walk(node: dict) -> None:
        data = node.get('data') if isinstance(node, dict) else None
        tags = data.get('tag') if isinstance(data, dict) else None
        if isinstance(tags, list):
            resolved = []
            for tag in tags:
                if not isinstance(tag, dict) or not tag.get('tagId'):
                    resolved.append(tag)
                    continue
                tag_key = str(tag['tagId'])
                scoped_key = (
                    f'{tag_key}:{tag["fieldId"]}:{tag["optionId"]}'
                    if tag.get('fieldId') and tag.get('optionId')
                    else tag_key
                )
                snapshot = tag_snapshots.get(scoped_key) or tag_snapshots.get(tag_key)
                if snapshot:
                    local = {key: tag[key] for key in ('placement', 'align', 'fieldId', 'optionId') if key in tag}
                    resolved.append({**snapshot, **local, 'style': dict(snapshot.get('style') or {})})
                else:
                    resolved.append(tag)
            data['tag'] = resolved
        for child in node.get('children') or []:
            if isinstance(child, dict):
                walk(child)

    walk(tree)
    return tree


async def _check_version_access(
    db: AsyncSession, mindmap_id: int, user_id: int, require_edit: bool = False,
) -> Any:
    """版本服务的统一权限检查代理"""
    from module_mindmap.service.mindmap_service import MindmapService  # noqa: PLC0415
    return await MindmapService.check_mindmap_access(db, mindmap_id, user_id, require_edit=require_edit)


class MindmapVersionService:
    """版本历史服务层"""

    @classmethod
    async def create_draft_version(
        cls, db: AsyncSession, mindmap_id: int, node_tree: dict,
        view_data: dict | None, layout: str | None, theme: dict | None,
        created_by: str,
    ) -> None:
        """创建草稿版本（自动保存时调用），清理超出上限的旧草稿"""
        latest_draft = await MindmapVersionDao.get_latest_draft(db, mindmap_id)
        if (
            latest_draft
            and latest_draft.created_time
            and (datetime.now() - latest_draft.created_time).total_seconds() < DRAFT_MIN_INTERVAL_SECONDS
        ):
            return
        version_number = await MindmapVersionDao.get_next_version_number(db, mindmap_id)

        # 序列化 node_tree
        node_tree_str = json.dumps(node_tree, ensure_ascii=False) if isinstance(node_tree, dict) else node_tree
        tag_snapshots = await MindmapDocumentService.get_tag_snapshots(
            db, mindmap_id, node_tree=node_tree if isinstance(node_tree, dict) else None,
        )

        await MindmapVersionDao.add_version(db, {
            'mindmap_id': mindmap_id,
            'version_number': version_number,
            'version_type': 0,  # 草稿
            'name': None,
            'node_tree': node_tree_str,
            'view_data': view_data,
            'layout': layout,
            'theme': theme,
            'snapshot_schema_version': 2,
            'tag_snapshots': tag_snapshots,
            'created_by': created_by,
            'created_time': datetime.now(),
        })

        # 清理旧草稿
        await MindmapVersionDao.delete_old_drafts(db, mindmap_id, keep_count=MAX_DRAFT_VERSIONS)
        # 注意：不在此处 commit，由调用方统一提交以保证事务原子性
        await db.flush()

    @classmethod
    async def create_formal_version(
        cls, db: AsyncSession, model: MindmapVersionSaveModel, user_id: int, user_name: str,
    ) -> CrudResponseModel:
        """创建正式版本（Ctrl+S 手动保存时调用）"""
        # 编辑权限检查已锁定文件行，后续版本号分配和计数更新共享该锁。
        mindmap = await _check_version_access(db, model.mindmap_id, user_id, require_edit=True)
        version_number = await MindmapVersionDao.get_next_version_number(db, model.mindmap_id)

        # 结构化节点表是持久化主数据；node_tree 仅在迁移期作为回退快照。
        node_tree = (
            await MindmapDocumentService.load_tree(db, model.mindmap_id, required=True)
            if getattr(mindmap, 'schema_version', 1) >= SCHEMA_VERSION
            else mindmap.node_tree
        )
        node_tree_str = node_tree if isinstance(node_tree, str) else json.dumps(node_tree, ensure_ascii=False)
        tag_snapshots = await MindmapDocumentService.get_tag_snapshots(
            db, model.mindmap_id, node_tree=node_tree if isinstance(node_tree, dict) else None,
        )

        try:
            await MindmapVersionDao.add_version(db, {
                'mindmap_id': model.mindmap_id,
                'version_number': version_number,
                'version_type': 1,  # 正式
                'name': model.name or f'版本 {version_number}',
                'node_tree': node_tree_str,
                'view_data': mindmap.view_data,
                'layout': mindmap.layout,
                'theme': mindmap.theme,
                'snapshot_schema_version': 2,
                'tag_snapshots': tag_snapshots,
                'created_by': user_name,
                'created_time': datetime.now(),
            })

            # 递增主表 version_count
            await MindmapDao.increment_version_count(db, model.mindmap_id)
            await db.commit()
            return CrudResponseModel(is_success=True, message='正式版本创建成功')
        except Exception as e:
            await db.rollback()
            raise e

    @classmethod
    async def get_version_list_services(
        cls, db: AsyncSession, mindmap_id: int, version_type: int | None = None,
        page_num: int = 1, page_size: int = 20, user_id: int = 0,
    ) -> PageModel:
        """获取版本列表（不含 node_tree 大字段）"""
        await _check_version_access(db, mindmap_id, user_id, require_edit=False)

        return await MindmapVersionDao.get_version_list(
            db, mindmap_id, version_type, page_num, page_size,
        )

    @classmethod
    async def get_version_detail_services(
        cls, db: AsyncSession, version_id: int, user_id: int,
    ) -> MindmapVersionModel:
        """获取版本详情（含完整 node_tree）"""
        version = await MindmapVersionDao.get_version_by_id(db, version_id)
        if not version:
            raise ServiceException(message='版本不存在')

        # 验证脑图访问权限
        await _check_version_access(db, version.mindmap_id, user_id, require_edit=False)

        result_dict = CamelCaseUtil.transform_result(version)
        if isinstance(result_dict.get('nodeTree'), str):
            result_dict['nodeTree'] = json.loads(result_dict['nodeTree'])
        if isinstance(result_dict.get('node_tree'), str):
            result_dict['node_tree'] = json.loads(result_dict['node_tree'])
        snapshots = result_dict.get('tagSnapshots') or result_dict.get('tag_snapshots')
        tree = result_dict.get('nodeTree') or result_dict.get('node_tree')
        if isinstance(tree, dict) and snapshots:
            preview_tree = _apply_tag_snapshots(tree, snapshots)
            result_dict['nodeTree'] = preview_tree
            result_dict['node_tree'] = preview_tree
        return MindmapVersionModel(**result_dict)

    @classmethod
    async def restore_version_services(
        cls, db: AsyncSession, version_id: int, user_id: int, user_name: str,
    ) -> CrudResponseModel:
        """回滚到指定版本"""
        version = await MindmapVersionDao.get_version_by_id(db, version_id)
        if not version:
            raise ServiceException(message='版本不存在')

        # 恢复版本需要编辑权限
        # 编辑权限检查已锁定文件行，恢复与其他版本写操作按文件串行。
        mindmap = await _check_version_access(db, version.mindmap_id, user_id, require_edit=True)

        try:
            # 同步恢复结构化内容；全局标签定义不随版本回滚。
            restored_tree = version.node_tree
            if isinstance(restored_tree, str):
                restored_tree = json.loads(restored_tree)
            restored_tree = await MindmapTagPortabilityService.prepare_tree_for_owner(
                db,
                restored_tree,
                target_owner_id=mindmap.owner_id,
                allow_disabled_references=True,
            )
            restored_tree_str = json.dumps(restored_tree, ensure_ascii=False)
            await MindmapDao.edit_mindmap_dao(db, {
                'id': version.mindmap_id,
                'node_tree': restored_tree_str,
                'view_data': version.view_data,
                'layout': version.layout,
                'theme': version.theme,
                'update_by': user_name,
                'update_time': datetime.now(),
            })
            metadata = await MindmapDocumentService.persist_tree_incremental(
                db,
                version.mindmap_id,
                restored_tree,
                owner_id=mindmap.owner_id,
                operator=user_name,
                allow_disabled_bindings=True,
            )
            changed_nodes = metadata.pop('changed_nodes', [])
            new_content_revision = mindmap.content_revision + 1
            await MindmapDao.edit_mindmap_dao(db, {
                'id': version.mindmap_id,
                **metadata,
                'content_revision': new_content_revision,
            })

            from module_mindmap.entity.do.mindmap_content_do import MindmapChangeLog  # noqa: PLC0415
            mutation_id = f'restore-{version_id}-{uuid.uuid4()}'
            db.add(MindmapChangeLog(
                file_id=version.mindmap_id,
                base_revision=mindmap.content_revision,
                revision=new_content_revision,
                client_mutation_id=mutation_id,
                operations=[{'type': 'document.restore', 'payload': {'versionId': version_id}}],
                result_data={
                    'contentRevision': new_content_revision,
                    'clientMutationId': mutation_id,
                    'changedNodes': changed_nodes,
                },
                created_by=user_name,
                created_time=datetime.now(),
            ))

            # 创建一个正式版本记录（标记这是回滚操作）
            version_number = await MindmapVersionDao.get_next_version_number(db, version.mindmap_id)
            await MindmapVersionDao.add_version(db, {
                'mindmap_id': version.mindmap_id,
                'version_number': version_number,
                'version_type': 1,
                'name': f'回滚自版本 {version.version_number}',
                'node_tree': restored_tree_str,
                'view_data': version.view_data,
                'layout': version.layout,
                'theme': version.theme,
                'snapshot_schema_version': 2,
                'tag_snapshots': await MindmapDocumentService.get_tag_snapshots(db, version.mindmap_id),
                'created_by': user_name,
                'created_time': datetime.now(),
            })

            await MindmapDao.increment_version_count(db, version.mindmap_id)
            await db.commit()
            try:
                from module_mindmap.websocket.room_manager import room_manager  # noqa: PLC0415

                room_manager.set_content_revision(version.mindmap_id, new_content_revision)
                await room_manager.broadcast(version.mindmap_id, {
                    'type': 'document_reset',
                    'contentRevision': new_content_revision,
                    'clientMutationId': mutation_id,
                })
            except Exception as exc:
                logger.warning(f'广播版本恢复 revision 失败: {exc}')
            return CrudResponseModel(
                is_success=True,
                message='版本回滚成功',
                result={'contentRevision': new_content_revision},
            )
        except Exception as e:
            await db.rollback()
            raise e

    @classmethod
    async def delete_version_services(
        cls, db: AsyncSession, version_id: int, user_id: int,
    ) -> CrudResponseModel:
        """删除指定版本（仅允许删除正式版本）"""
        version = await MindmapVersionDao.get_version_by_id(db, version_id)
        if not version:
            raise ServiceException(message='版本不存在')
        if version.version_type == 0:
            raise ServiceException(message='草稿版本不允许手动删除')

        # 编辑权限检查返回的文件记录已通过 FOR UPDATE 锁定。所有版本写操作
        # 因而统一遵循“文件锁 → 版本锁”，避免死锁并串行维护 version_count。
        await _check_version_access(db, version.mindmap_id, user_id, require_edit=True)

        try:
            # 再次锁定并读取版本记录，避免两个并发删除都基于同一旧快照
            # 扣减 version_count。
            locked_version = await MindmapVersionDao.get_version_for_update(db, version_id)
            if not locked_version or locked_version.mindmap_id != version.mindmap_id:
                raise ServiceException(message='版本不存在或已被删除')
            if locked_version.version_type == 0:
                raise ServiceException(message='草稿版本不允许手动删除')

            await MindmapVersionDao.delete_version(db, version_id)
            await MindmapDao.decrement_version_count(db, locked_version.mindmap_id)
            await db.commit()
            return CrudResponseModel(is_success=True, message='版本删除成功')
        except Exception as e:
            await db.rollback()
            raise e
