"""脑图协作者服务层"""
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import CrudResponseModel
from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_collaborator_dao import MindmapCollaboratorDao
from module_mindmap.dao.mindmap_dao import MindmapDao
from module_mindmap.entity.vo.mindmap_collaborator_vo import (
    MindmapCollaboratorAddModel,
    MindmapCollaboratorModel,
    MindmapCollaboratorUpdateModel,
)
from utils.common_util import CamelCaseUtil


class MindmapCollaboratorService:
    """协作者服务层"""

    @classmethod
    async def add_collaborator(
        cls, db: AsyncSession, model: MindmapCollaboratorAddModel, operator_id: int,
    ) -> CrudResponseModel:
        """添加协作者"""
        mindmap = await MindmapDao.get_mindmap_by_id(db, model.mindmap_id)
        if not mindmap:
            raise ServiceException(message='思维导图不存在')
        if mindmap.owner_id != operator_id:
            raise ServiceException(message='只有脑图所有者可以添加协作者')
        if mindmap.owner_id == model.user_id:
            raise ServiceException(message='不能将所有者添加为协作者')

        if await MindmapCollaboratorDao.check_exists(db, model.mindmap_id, model.user_id):
            raise ServiceException(message='该用户已是协作者')

        try:
            await MindmapCollaboratorDao.add_collaborator(db, {
                'mindmap_id': model.mindmap_id,
                'user_id': model.user_id,
                'permission': model.permission,
                'created_by': operator_id,
                'created_time': datetime.now(),
            })
            await db.commit()
            return CrudResponseModel(is_success=True, message='协作者添加成功')
        except Exception as e:
            await db.rollback()
            raise e

    @classmethod
    async def get_collaborator_list(
        cls, db: AsyncSession, mindmap_id: int, user_id: int,
    ) -> list[MindmapCollaboratorModel]:
        """获取协作者列表"""
        mindmap = await MindmapDao.get_mindmap_by_id(db, mindmap_id)
        if not mindmap:
            raise ServiceException(message='思维导图不存在')
        if mindmap.owner_id != user_id:
            raise ServiceException(message='无权限查看')

        collabs = await MindmapCollaboratorDao.get_collaborators_by_mindmap(db, mindmap_id)
        return [
            MindmapCollaboratorModel(**CamelCaseUtil.transform_result(c))
            for c in collabs
        ]

    @classmethod
    async def update_permission(
        cls, db: AsyncSession, model: MindmapCollaboratorUpdateModel, operator_id: int,
    ) -> CrudResponseModel:
        """修改协作者权限"""
        collab = await MindmapCollaboratorDao.get_collaborator_by_id(db, model.id)
        if not collab:
            raise ServiceException(message='协作者记录不存在')

        mindmap = await MindmapDao.get_mindmap_by_id(db, collab.mindmap_id)
        if not mindmap or mindmap.owner_id != operator_id:
            raise ServiceException(message='无权限操作')

        try:
            await MindmapCollaboratorDao.update_permission(db, model.id, model.permission)
            await db.commit()
            return CrudResponseModel(is_success=True, message='权限修改成功')
        except Exception as e:
            await db.rollback()
            raise e

    @classmethod
    async def remove_collaborator(
        cls, db: AsyncSession, collab_id: int, operator_id: int,
    ) -> CrudResponseModel:
        """移除协作者"""
        collab = await MindmapCollaboratorDao.get_collaborator_by_id(db, collab_id)
        if not collab:
            raise ServiceException(message='协作者记录不存在')

        mindmap = await MindmapDao.get_mindmap_by_id(db, collab.mindmap_id)
        if not mindmap or mindmap.owner_id != operator_id:
            raise ServiceException(message='无权限操作')

        try:
            await MindmapCollaboratorDao.remove_collaborator(db, collab_id)
            await db.commit()
            return CrudResponseModel(is_success=True, message='协作者已移除')
        except Exception as e:
            await db.rollback()
            raise e

    @classmethod
    async def check_collaborator_access(
        cls, db: AsyncSession, mindmap_id: int, user_id: int, require_edit: bool = False,
    ) -> bool:
        """检查用户是否有协作者权限访问脑图

        :param require_edit: True 则要求编辑权限，False 只需查看权限
        :return: True=有权限, False=无权限
        """
        permission = await MindmapCollaboratorDao.get_collaborator_permission(db, mindmap_id, user_id)
        if permission is None:
            return False
        return not (require_edit and permission < 1)
