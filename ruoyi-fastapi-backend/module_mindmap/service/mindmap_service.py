import json
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import CrudResponseModel, PageModel
from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_dao import MindmapDao
from module_mindmap.dao.mindmap_folder_dao import MindmapFolderDao
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
    async def check_mindmap_access(
        cls, db: AsyncSession, mindmap_id: int, user_id: int, require_edit: bool = False,
    ):
        """统一的脑图访问权限检查

        检查用户是否为脑图所有者，或是否有协作者权限。

        :param db: 数据库会话
        :param mindmap_id: 脑图ID
        :param user_id: 用户ID
        :param require_edit: True 则要求编辑权限，False 只需查看权限
        :return: 脑图记录
        :raises ServiceException: 无权限时抛出
        """
        mindmap = await MindmapDao.get_mindmap_by_id(db, mindmap_id)
        if not mindmap:
            raise ServiceException(message='思维导图不存在')

        # 所有者拥有所有权限
        if mindmap.owner_id == user_id:
            return mindmap

        # 检查协作者权限
        from module_mindmap.service.mindmap_collaborator_service import MindmapCollaboratorService  # noqa: PLC0415
        is_collaborator = await MindmapCollaboratorService.check_collaborator_access(
            db, mindmap_id, user_id, require_edit=require_edit,
        )
        if not is_collaborator:
            raise ServiceException(
                message='无编辑权限' if require_edit else '无访问权限'
            )
        return mindmap

    @classmethod
    async def get_mindmap_list_services(
        cls, query_db: AsyncSession, query_object: MindmapPageQueryModel, is_page: bool = True
    ) -> PageModel | list[dict[str, Any]]:
        """获取思维导图列表"""
        return await MindmapDao.get_mindmap_list(query_db, query_object, is_page)

    @classmethod
    async def get_mindmap_detail_services(cls, query_db: AsyncSession, mindmap_id: int, user_id: int) -> MindmapModel:
        """获取思维导图详细信息（含所有权校验）"""
        mindmap = await cls.check_mindmap_access(query_db, mindmap_id, user_id, require_edit=False)

        result_dict = CamelCaseUtil.transform_result(mindmap)
        if isinstance(result_dict.get('nodeTree'), str):
            result_dict['nodeTree'] = json.loads(result_dict['nodeTree'])
        if isinstance(result_dict.get('node_tree'), str):
            result_dict['node_tree'] = json.loads(result_dict['node_tree'])
        return MindmapModel(**result_dict)

    @classmethod
    async def add_mindmap_services(cls, query_db: AsyncSession, page_object: MindmapModel) -> CrudResponseModel:
        """新增思维导图"""
        # Serialize node_tree to JSON string for LONGTEXT storage
        insert_data = page_object.model_dump(exclude_none=True)
        if isinstance(insert_data.get('node_tree'), dict):
            insert_data['node_tree'] = json.dumps(insert_data['node_tree'], ensure_ascii=False)
        # Remove id if present (auto-generated)
        insert_data.pop('id', None)

        # 校验文件夹归属
        if insert_data.get('folder_id'):
            folder = await MindmapFolderDao.get_folder_by_id(query_db, insert_data['folder_id'])
            if not folder or folder.owner_id != insert_data['owner_id']:
                raise ServiceException(message='目标文件夹不存在或无权限')

        try:
            new_mindmap = await MindmapDao.add_mindmap_dao(query_db, insert_data)
            # flush() 后主键 ID 立即可用，在 commit 前获取
            new_id = new_mindmap.id
            await query_db.commit()
            return CrudResponseModel(is_success=True, message='新增成功', result={'id': new_id})
        except Exception as e:
            await query_db.rollback()
            raise e

    @classmethod
    async def edit_mindmap_services(
        cls, query_db: AsyncSession, page_object: MindmapModel, user_id: int,
    ) -> CrudResponseModel:
        """编辑思维导图元数据（名称、描述、封面等）"""
        await cls.check_mindmap_access(query_db, page_object.id, user_id, require_edit=True)

        try:
            # 防御性排除：特权字段（owner_id、审计字段、版本计数等）禁止客户端修改，
            # 防止 Mass Assignment 攻击导致所有权劫持或数据篡改
            update_data = page_object.model_dump(
                exclude_unset=True,
                exclude={
                    'node_tree', 'view_data',       # 大内容字段，由 auto-save 端点单独处理
                    'owner_id',                      # 所有权：只能由 add_mindmap 设置
                    'is_template', 'status',         # 管理员控制的状态标记
                    'version_count', 'last_version_id',  # 由版本服务维护
                    'create_by', 'create_time',      # 审计字段：创建时一次性写入
                    'folder_id',                     # 文件夹归属：仅通过 /mindmap/move 端点修改
                },
            )
            # id 保留在 update_data 中供 DAO 的 WHERE 子句使用，不会被 SET 覆盖
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
        await cls.check_mindmap_access(query_db, page_object.id, user_id, require_edit=True)

        # Serialize node_tree to JSON string
        update_data = {
            'update_by': str(user_id),
            'update_time': datetime.now(),
        }
        if page_object.node_tree is not None:
            update_data['node_tree'] = json.dumps(page_object.node_tree, ensure_ascii=False)
        if page_object.view_data is not None:
            update_data['view_data'] = page_object.view_data
        if page_object.layout is not None:
            update_data['layout'] = page_object.layout
        if page_object.theme is not None:
            update_data['theme'] = page_object.theme

        try:
            await MindmapDao.update_content_dao(query_db, page_object.id, update_data)

            # 自动创建草稿版本（在同一事务中，统一提交）
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

            # 统一提交：内容更新 + 草稿版本创建
            await query_db.commit()

            return CrudResponseModel(is_success=True, message='保存成功')
        except Exception as e:
            await query_db.rollback()
            raise e

    @classmethod
    async def rename_mindmap_services(
        cls, query_db: AsyncSession, page_object: MindmapRenameModel, user_id: int
    ) -> CrudResponseModel:
        """重命名思维导图"""
        await cls.check_mindmap_access(query_db, page_object.id, user_id, require_edit=True)

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
        """删除思维导图（含所有权校验和关联数据级联清理）"""
        if not page_object.mindmap_ids:
            raise ServiceException(message='传入思维导图ID为空')

        id_list = [int(i) for i in page_object.mindmap_ids.split(',') if i.strip()]

        # 逐个校验所有权
        for mindmap_id in id_list:
            mindmap = await MindmapDao.get_mindmap_by_id(query_db, mindmap_id)
            if mindmap and mindmap.owner_id != user_id:
                raise ServiceException(message=f'无权限删除脑图ID={mindmap_id}')

        try:
            # 级联清理关联数据
            from sqlalchemy import delete as sa_delete  # noqa: PLC0415
            from module_mindmap.entity.do.mindmap_version_do import MindmapVersion  # noqa: PLC0415
            from module_mindmap.entity.do.mindmap_share_do import MindmapShare  # noqa: PLC0415
            from module_mindmap.entity.do.mindmap_collaborator_do import MindmapCollaborator  # noqa: PLC0415
            from module_mindmap.entity.do.mindmap_ws_state_do import MindmapWsState  # noqa: PLC0415

            for model in (MindmapVersion, MindmapShare, MindmapCollaborator, MindmapWsState):
                await query_db.execute(
                    sa_delete(model).where(model.mindmap_id.in_(id_list))
                )

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
        source = await cls.check_mindmap_access(query_db, mindmap_id, user_id, require_edit=False)

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
