"""脑图版本历史服务层"""
import json
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
from utils.common_util import CamelCaseUtil

# 草稿版本保留数量上限
MAX_DRAFT_VERSIONS = 10


class MindmapVersionService:
    """版本历史服务层"""

    @classmethod
    async def create_draft_version(
        cls, db: AsyncSession, mindmap_id: int, node_tree: dict,
        view_data: dict | None, layout: str | None, theme: dict | None,
        created_by: str,
    ) -> None:
        """创建草稿版本（自动保存时调用），清理超出上限的旧草稿"""
        version_number = await MindmapVersionDao.get_next_version_number(db, mindmap_id)

        # 序列化 node_tree
        node_tree_str = json.dumps(node_tree, ensure_ascii=False) if isinstance(node_tree, dict) else node_tree

        await MindmapVersionDao.add_version(db, {
            'mindmap_id': mindmap_id,
            'version_number': version_number,
            'version_type': 0,  # 草稿
            'name': None,
            'node_tree': node_tree_str,
            'view_data': view_data,
            'layout': layout,
            'theme': theme,
            'created_by': created_by,
            'created_time': datetime.now(),
        })

        # 清理旧草稿
        await MindmapVersionDao.delete_old_drafts(db, mindmap_id, keep_count=MAX_DRAFT_VERSIONS)
        await db.commit()

    @classmethod
    async def create_formal_version(
        cls, db: AsyncSession, model: MindmapVersionSaveModel, user_id: int, user_name: str,
    ) -> CrudResponseModel:
        """创建正式版本（Ctrl+S 手动保存时调用）"""
        # 验证脑图存在
        mindmap = await MindmapDao.get_mindmap_by_id(db, model.mindmap_id)
        if not mindmap:
            raise ServiceException(message='思维导图不存在')
        if mindmap.owner_id != user_id:
            raise ServiceException(message='无权限操作')

        version_number = await MindmapVersionDao.get_next_version_number(db, model.mindmap_id)

        # 读取当前脑图数据作为快照
        node_tree = mindmap.node_tree
        if isinstance(node_tree, str):
            node_tree_str = node_tree
        else:
            node_tree_str = json.dumps(node_tree, ensure_ascii=False)

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
        # 验证脑图所有权
        mindmap = await MindmapDao.get_mindmap_by_id(db, mindmap_id)
        if not mindmap:
            raise ServiceException(message='思维导图不存在')
        if mindmap.owner_id != user_id:
            raise ServiceException(message='无访问权限')

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

        # 验证脑图所有权
        mindmap = await MindmapDao.get_mindmap_by_id(db, version.mindmap_id)
        if not mindmap or mindmap.owner_id != user_id:
            raise ServiceException(message='无访问权限')

        result_dict = CamelCaseUtil.transform_result(version)
        if isinstance(result_dict.get('node_tree'), str):
            result_dict['node_tree'] = json.loads(result_dict['node_tree'])
        return MindmapVersionModel(**result_dict)

    @classmethod
    async def restore_version_services(
        cls, db: AsyncSession, version_id: int, user_id: int, user_name: str,
    ) -> CrudResponseModel:
        """回滚到指定版本"""
        version = await MindmapVersionDao.get_version_by_id(db, version_id)
        if not version:
            raise ServiceException(message='版本不存在')

        mindmap = await MindmapDao.get_mindmap_by_id(db, version.mindmap_id)
        if not mindmap:
            raise ServiceException(message='思维导图不存在')
        if mindmap.owner_id != user_id:
            raise ServiceException(message='无权限操作')

        try:
            # 将版本的 node_tree 写回主表
            update_data = {
                'id': version.mindmap_id,
                'node_tree': version.node_tree,
                'view_data': version.view_data,
                'layout': version.layout,
                'theme': version.theme,
                'update_by': user_name,
                'update_time': datetime.now(),
            }
            await MindmapDao.edit_mindmap_dao(db, update_data)

            # 创建一个正式版本记录（标记这是回滚操作）
            version_number = await MindmapVersionDao.get_next_version_number(db, version.mindmap_id)
            await MindmapVersionDao.add_version(db, {
                'mindmap_id': version.mindmap_id,
                'version_number': version_number,
                'version_type': 1,
                'name': f'回滚自版本 {version.version_number}',
                'node_tree': version.node_tree,
                'view_data': version.view_data,
                'layout': version.layout,
                'theme': version.theme,
                'created_by': user_name,
                'created_time': datetime.now(),
            })

            await MindmapDao.increment_version_count(db, version.mindmap_id)
            await db.commit()
            return CrudResponseModel(is_success=True, message='版本回滚成功')
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

        mindmap = await MindmapDao.get_mindmap_by_id(db, version.mindmap_id)
        if not mindmap or mindmap.owner_id != user_id:
            raise ServiceException(message='无权限操作')

        try:
            await MindmapVersionDao.delete_version(db, version_id)
            await db.commit()
            return CrudResponseModel(is_success=True, message='版本删除成功')
        except Exception as e:
            await db.rollback()
            raise e
