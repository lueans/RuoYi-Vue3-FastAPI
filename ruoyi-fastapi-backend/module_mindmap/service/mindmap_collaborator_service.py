"""脑图协作者服务层"""
from datetime import datetime

from sqlalchemy.exc import IntegrityError
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
from utils.log_util import logger


class MindmapCollaboratorService:
    """协作者服务层"""

    @classmethod
    async def add_collaborator(
        cls, db: AsyncSession, model: MindmapCollaboratorAddModel, operator_id: int,
    ) -> CrudResponseModel:
        """添加协作者"""
        mindmap = await MindmapDao.get_mindmap_for_update(db, model.mindmap_id)
        if not mindmap:
            await db.rollback()
            raise ServiceException(message='思维导图不存在')
        if mindmap.owner_id != operator_id:
            await db.rollback()
            raise ServiceException(message='只有脑图所有者可以添加协作者')
        if mindmap.status == 1:
            await db.rollback()
            raise ServiceException(message='脑图已归档，请恢复后再添加协作者')
        if mindmap.owner_id == model.user_id:
            await db.rollback()
            raise ServiceException(message='不能将所有者添加为协作者')
        if not await MindmapCollaboratorDao.is_active_user(db, model.user_id):
            await db.rollback()
            raise ServiceException(message='目标用户不存在或已停用')

        if await MindmapCollaboratorDao.check_exists(db, model.mindmap_id, model.user_id):
            await db.rollback()
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
        except IntegrityError as exc:
            await db.rollback()
            raise ServiceException(message='该用户已是协作者') from exc
        except Exception:
            await db.rollback()
            raise

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
    async def search_available_users(
        cls, db: AsyncSession, mindmap_id: int, keyword: str, operator_id: int,
    ) -> list[dict]:
        """搜索当前所有者可添加到指定脑图的用户。"""
        mindmap = await MindmapDao.get_mindmap_by_id(db, mindmap_id)
        if not mindmap:
            raise ServiceException(message='思维导图不存在')
        if mindmap.owner_id != operator_id:
            raise ServiceException(message='只有脑图所有者可以搜索协作者')

        normalized_keyword = keyword.strip()
        if not normalized_keyword:
            return []
        users = await MindmapCollaboratorDao.search_available_users(
            db,
            mindmap_id,
            mindmap.owner_id,
            normalized_keyword,
        )
        return [CamelCaseUtil.transform_result(user) for user in users]

    @classmethod
    async def update_permission(
        cls, db: AsyncSession, model: MindmapCollaboratorUpdateModel, operator_id: int,
    ) -> CrudResponseModel:
        """修改协作者权限"""
        collab = await MindmapCollaboratorDao.get_collaborator_by_id(db, model.id)
        if not collab:
            raise ServiceException(message='协作者记录不存在')

        mindmap = await MindmapDao.get_mindmap_for_update(db, collab.mindmap_id)
        if not mindmap or mindmap.owner_id != operator_id:
            await db.rollback()
            raise ServiceException(message='无权限操作')
        if collab.permission == model.permission:
            await db.rollback()
            return CrudResponseModel(is_success=True, message='权限未发生变化')
        if mindmap.status == 1 and model.permission == 1:
            await db.rollback()
            raise ServiceException(message='脑图已归档，请恢复后再授予编辑权限')
        mindmap_id = collab.mindmap_id
        target_user_id = collab.user_id

        try:
            await MindmapCollaboratorDao.update_permission(db, model.id, model.permission)
            await db.commit()
            if model.permission == 0:
                await cls._notify_access_revoked(
                    mindmap_id,
                    target_user_id,
                    '你的脑图权限已调整为只读，当前编辑会话已结束',
                )
            return CrudResponseModel(is_success=True, message='权限修改成功')
        except Exception:
            await db.rollback()
            raise

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
        mindmap_id = collab.mindmap_id
        target_user_id = collab.user_id

        try:
            await MindmapCollaboratorDao.remove_collaborator(db, collab_id)
            await db.commit()
            await cls._notify_access_revoked(
                mindmap_id,
                target_user_id,
                '你已被移出该脑图，当前编辑会话已结束',
            )
            return CrudResponseModel(is_success=True, message='协作者已移除')
        except Exception:
            await db.rollback()
            raise

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

    @staticmethod
    async def _notify_access_revoked(
        mindmap_id: int, user_id: int, message: str,
    ) -> None:
        """权限主数据已提交，实时通知失败只能降级，不能反向回滚。"""
        try:
            from module_mindmap.websocket.room_manager import room_manager  # noqa: PLC0415

            await room_manager.notify_and_disconnect_user(
                mindmap_id,
                user_id,
                {
                    'type': 'access_revoked',
                    'mindmapId': mindmap_id,
                    'message': message,
                },
            )
        except Exception as exc:
            logger.warning(
                f'断开失效协作者会话失败: mindmap_id={mindmap_id}, user_id={user_id}, error={exc}'
            )
