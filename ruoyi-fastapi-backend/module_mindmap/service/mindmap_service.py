import json
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import CrudResponseModel, PageModel
from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_dao import MindmapDao
from module_mindmap.entity.vo.mindmap_vo import (
    DeleteMindmapModel,
    MindmapContentUpdateModel,
    MindmapModel,
    MindmapPageQueryModel,
    MindmapRenameModel,
)
from utils.common_util import CamelCaseUtil
from utils.log_util import logger


class MindmapService:
    """思维导图模块服务层"""

    @classmethod
    async def get_mindmap_list_services(
        cls, query_db: AsyncSession, query_object: MindmapPageQueryModel, is_page: bool = True
    ) -> PageModel | list[dict[str, Any]]:
        """获取思维导图列表"""
        return await MindmapDao.get_mindmap_list(query_db, query_object, is_page)

    @classmethod
    async def get_mindmap_detail_services(cls, query_db: AsyncSession, mindmap_id: int, user_id: int) -> MindmapModel:
        """获取思维导图详细信息（含所有权校验）"""
        mindmap = await MindmapDao.get_mindmap_by_id(query_db, mindmap_id)
        if not mindmap:
            raise ServiceException(message='思维导图不存在')
        if mindmap.owner_id != user_id:
            # 检查是否为协作者 (lazy import to avoid circular dependency)
            from module_mindmap.service.mindmap_collaborator_service import MindmapCollaboratorService  # noqa: PLC0415
            is_collaborator = await MindmapCollaboratorService.check_collaborator_access(
                query_db, mindmap_id, user_id, require_edit=False,
            )
            if not is_collaborator:
                raise ServiceException(message='无访问权限')

        result_dict = CamelCaseUtil.transform_result(mindmap)
        if isinstance(result_dict.get('nodeTree'), str):
            result_dict['nodeTree'] = json.loads(result_dict['nodeTree'])
        if isinstance(result_dict.get('node_tree'), str):
            result_dict['node_tree'] = json.loads(result_dict['node_tree'])
        return MindmapModel(**result_dict)

    @classmethod
    async def add_mindmap_services(cls, query_db: AsyncSession, page_object: MindmapModel) -> CrudResponseModel:
        """新增思维导图"""
        # Check name uniqueness
        is_unique = await MindmapDao.check_name_unique(
            query_db, page_object.name, page_object.owner_id
        )
        if not is_unique:
            raise ServiceException(message=f'新增思维导图{page_object.name}失败，名称已存在')

        # Serialize node_tree to JSON string for LONGTEXT storage
        insert_data = page_object.model_dump(exclude_none=True)
        if isinstance(insert_data.get('node_tree'), dict):
            insert_data['node_tree'] = json.dumps(insert_data['node_tree'], ensure_ascii=False)
        # Remove id if present (auto-generated)
        insert_data.pop('id', None)

        try:
            await MindmapDao.add_mindmap_dao(query_db, insert_data)
            await query_db.commit()
            return CrudResponseModel(is_success=True, message='新增成功')
        except Exception as e:
            await query_db.rollback()
            raise e

    @classmethod
    async def edit_mindmap_services(
        cls, query_db: AsyncSession, page_object: MindmapModel, user_id: int,
    ) -> CrudResponseModel:
        """编辑思维导图元数据（名称、描述、封面等）"""
        mindmap = await MindmapDao.get_mindmap_by_id(query_db, page_object.id)
        if not mindmap:
            raise ServiceException(message='思维导图不存在')
        if mindmap.owner_id != user_id:
            raise ServiceException(message='无编辑权限')

        if page_object.name and page_object.name != mindmap.name:
            is_unique = await MindmapDao.check_name_unique(
                query_db, page_object.name, mindmap.owner_id, exclude_id=page_object.id
            )
            if not is_unique:
                raise ServiceException(message=f'修改思维导图失败，名称{page_object.name}已存在')

        try:
            update_data = page_object.model_dump(exclude_unset=True, exclude={'node_tree', 'view_data'})
            await MindmapDao.edit_mindmap_dao(query_db, update_data)
            await query_db.commit()
            return CrudResponseModel(is_success=True, message='更新成功')
        except Exception as e:
            await query_db.rollback()
            raise e

    @classmethod
    async def update_content_services(
        cls, query_db: AsyncSession, page_object: MindmapContentUpdateModel, user_id: int
    ) -> CrudResponseModel:
        """更新思维导图内容（自动保存端点）"""
        mindmap = await MindmapDao.get_mindmap_by_id(query_db, page_object.id)
        if not mindmap:
            raise ServiceException(message='思维导图不存在')

        # Check ownership or collaborator permission
        if mindmap.owner_id != user_id:
            # 检查是否为有编辑权限的协作者 (lazy import to avoid circular dependency)
            from module_mindmap.service.mindmap_collaborator_service import MindmapCollaboratorService  # noqa: PLC0415
            is_collaborator = await MindmapCollaboratorService.check_collaborator_access(
                query_db, page_object.id, user_id, require_edit=True,
            )
            if not is_collaborator:
                raise ServiceException(message='无编辑权限')

        # Serialize node_tree to JSON string
        update_data = {
            'update_by': str(user_id),
            'update_time': datetime.now(),
        }
        if page_object.node_tree:
            update_data['node_tree'] = json.dumps(page_object.node_tree, ensure_ascii=False)
        if page_object.view_data:
            update_data['view_data'] = page_object.view_data
        if page_object.layout:
            update_data['layout'] = page_object.layout
        if page_object.theme:
            update_data['theme'] = page_object.theme

        try:
            await MindmapDao.update_content_dao(query_db, page_object.id, update_data)
            await query_db.commit()

            # 自动创建草稿版本
            try:
                from module_mindmap.service.mindmap_version_service import MindmapVersionService  # noqa: PLC0415
                await MindmapVersionService.create_draft_version(
                    query_db, page_object.id,
                    node_tree=page_object.node_tree,
                    view_data=page_object.view_data,
                    layout=page_object.layout,
                    theme=page_object.theme,
                    created_by=str(user_id),
                )
            except Exception as e:
                logger.warning(f'创建草稿版本失败: {e}')

            return CrudResponseModel(is_success=True, message='保存成功')
        except Exception as e:
            await query_db.rollback()
            raise e

    @classmethod
    async def rename_mindmap_services(
        cls, query_db: AsyncSession, page_object: MindmapRenameModel, user_id: int
    ) -> CrudResponseModel:
        """重命名思维导图"""
        mindmap = await MindmapDao.get_mindmap_by_id(query_db, page_object.id)
        if not mindmap:
            raise ServiceException(message='思维导图不存在')
        if mindmap.owner_id != user_id:
            raise ServiceException(message='无编辑权限')

        is_unique = await MindmapDao.check_name_unique(
            query_db, page_object.name, mindmap.owner_id, exclude_id=page_object.id
        )
        if not is_unique:
            raise ServiceException(message=f'名称{page_object.name}已存在')

        try:
            await MindmapDao.edit_mindmap_dao(query_db, {
                'id': page_object.id,
                'name': page_object.name,
                'update_time': datetime.now(),
            })
            await query_db.commit()
            return CrudResponseModel(is_success=True, message='重命名成功')
        except Exception as e:
            await query_db.rollback()
            raise e

    @classmethod
    async def delete_mindmap_services(
        cls, query_db: AsyncSession, page_object: DeleteMindmapModel, user_id: int
    ) -> CrudResponseModel:
        """删除思维导图（含所有权校验）"""
        if not page_object.mindmap_ids:
            raise ServiceException(message='传入思维导图ID为空')

        id_list = [int(i) for i in page_object.mindmap_ids.split(',') if i.strip()]

        # 逐个校验所有权
        for mindmap_id in id_list:
            mindmap = await MindmapDao.get_mindmap_by_id(query_db, mindmap_id)
            if mindmap and mindmap.owner_id != user_id:
                raise ServiceException(message=f'无权限删除脑图ID={mindmap_id}')

        try:
            await MindmapDao.batch_delete_mindmap_dao(query_db, id_list)
            await query_db.commit()
            return CrudResponseModel(is_success=True, message='删除成功')
        except Exception as e:
            await query_db.rollback()
            raise e

    @classmethod
    async def copy_mindmap_services(
        cls, query_db: AsyncSession, mindmap_id: int, user_id: int
    ) -> CrudResponseModel:
        """复制思维导图"""
        source = await MindmapDao.get_mindmap_by_id(query_db, mindmap_id)
        if not source:
            raise ServiceException(message='源思维导图不存在')

        # Parse node_tree from string (stored as LONGTEXT) to dict
        source_tree = source.node_tree
        if isinstance(source_tree, str):
            source_tree = json.loads(source_tree) if source_tree else {}

        # Create copy with new name
        copy_model = MindmapModel(
            name=f'{source.name} (副本)',
            description=source.description,
            owner_id=user_id,
            layout=source.layout,
            theme=source.theme,
            node_tree=source_tree,
            view_data=source.view_data,
            cover_image=source.cover_image,
        )

        return await cls.add_mindmap_services(query_db, copy_model)
