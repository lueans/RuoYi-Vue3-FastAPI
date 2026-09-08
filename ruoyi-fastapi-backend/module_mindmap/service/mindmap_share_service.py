"""脑图分享链接服务层"""
import json
import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import CrudResponseModel
from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_collaborator_dao import MindmapCollaboratorDao
from module_mindmap.dao.mindmap_dao import MindmapDao
from module_mindmap.dao.mindmap_share_dao import MindmapShareDao
from module_mindmap.entity.vo.mindmap_share_vo import (
    MindmapShareCreateModel,
    MindmapShareJoinModel,
    MindmapShareModel,
)
from module_mindmap.service.mindmap_document_service import MindmapDocumentService
from module_mindmap.service.simple_mind_document_codec import SCHEMA_VERSION

SHARE_TOKEN_PATTERN = re.compile(r'^[0-9a-f]{32}$')


def normalize_share_expire_time(value: datetime | None) -> datetime | None:
    """将带时区的浏览器时间转换为数据库使用的本地无时区时间。"""
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone().replace(tzinfo=None)
    return value


def validate_active_share(share: Any) -> None:
    """校验公开查看与编辑邀请共同使用的链接生命周期。"""
    if not share:
        raise ServiceException(message='分享链接不存在')
    if not share.is_active:
        raise ServiceException(message='分享链接已失效')
    if share.share_type not in (0, 1):
        raise ServiceException(message='分享链接类型无效')
    expire_time = normalize_share_expire_time(share.expire_time)
    if expire_time and expire_time <= datetime.now():
        raise ServiceException(message='分享链接已过期')


class MindmapShareService:
    """分享链接服务层"""

    @classmethod
    async def create_share_link(
        cls, db: AsyncSession, model: MindmapShareCreateModel, user_id: int,
    ) -> CrudResponseModel:
        """创建分享链接"""
        expire_time = normalize_share_expire_time(model.expire_time)
        if expire_time is not None and expire_time <= datetime.now():
            raise ServiceException(message='分享链接过期时间必须晚于当前时间')
        # 验证脑图所有权
        mindmap = await MindmapShareDao.get_mindmap_ownership_snapshot(
            db,
            model.mindmap_id,
            for_update=True,
        )
        if not mindmap:
            await db.rollback()
            raise ServiceException(message='思维导图不存在')
        if mindmap.owner_id != user_id:
            await db.rollback()
            raise ServiceException(message='无权限操作')
        if mindmap.status == 1:
            await db.rollback()
            raise ServiceException(message='脑图已归档，请恢复后再创建分享链接')

        share_token = uuid.uuid4().hex

        try:
            await MindmapShareDao.add_share(db, {
                'mindmap_id': model.mindmap_id,
                'share_token': share_token,
                'share_type': model.share_type,
                'expire_time': expire_time,
                'created_by': user_id,
                'created_time': datetime.now(),
                'is_active': 1,
            })
            await db.commit()
            return CrudResponseModel(is_success=True, message='分享链接创建成功')
        except Exception as e:
            await db.rollback()
            raise e

    @classmethod
    async def get_share_list(
        cls, db: AsyncSession, mindmap_id: int, user_id: int,
    ) -> list[MindmapShareModel]:
        """获取脑图的分享链接列表"""
        mindmap = await MindmapShareDao.get_mindmap_ownership_snapshot(
            db,
            mindmap_id,
        )
        if not mindmap:
            raise ServiceException(message='思维导图不存在')
        if mindmap.owner_id != user_id:
            raise ServiceException(message='无权限查看')

        shares = await MindmapShareDao.get_shares_by_mindmap_id(db, mindmap_id)
        return [
            MindmapShareModel(
                id=share.id,
                mindmapId=share.mindmap_id,
                shareToken=share.share_token,
                shareType=share.share_type,
                expireTime=share.expire_time,
                createdBy=share.created_by,
                createdTime=share.created_time,
                isActive=share.is_active,
            )
            for share in shares
        ]

    @classmethod
    async def delete_share_link(
        cls, db: AsyncSession, share_id: int, user_id: int,
    ) -> CrudResponseModel:
        """禁用分享链接"""
        share = await MindmapShareDao.get_share_by_id(db, share_id)
        if not share:
            raise ServiceException(message='分享链接不存在')

        mindmap = await MindmapShareDao.get_mindmap_ownership_snapshot(
            db,
            share.mindmap_id,
        )
        if not mindmap or mindmap.owner_id != user_id:
            raise ServiceException(message='无权限操作')

        try:
            await MindmapShareDao.deactivate_share(db, share_id)
            await db.commit()
            return CrudResponseModel(is_success=True, message='分享链接已禁用')
        except Exception as e:
            await db.rollback()
            raise e

    @classmethod
    async def view_by_share_token(
        cls, db: AsyncSession, share_token: str,
    ) -> dict[str, Any]:
        """通过分享 token 查看脑图（公开接口，无需登录）"""
        if not SHARE_TOKEN_PATTERN.fullmatch(share_token):
            raise ServiceException(message='分享链接不存在')
        try:
            observed_share = await MindmapShareDao.get_share_access_snapshot(
                db,
                share_token,
            )
            validate_active_share(observed_share)
            # MySQL 默认 REPEATABLE READ 会在首次普通 SELECT 时建立一致性
            # 快照。先结束 token 探测事务，避免后续虽锁住 Mindmap，结构化
            # 表的普通 SELECT 却仍读取探测时刻的旧快照。
            await db.rollback()

            # 正文保存统一先锁 Mindmap 主记录再更新结构化表。公开读取沿用
            # Mindmap -> Share 的锁顺序并持有共享锁，确保 load_document 的
            # 多条 SELECT 与元数据来自同一个已提交 content_revision。
            mindmap = await MindmapShareDao.get_shared_mindmap_snapshot(
                db,
                observed_share.mindmap_id,
                for_share=True,
            )
            if not mindmap:
                raise ServiceException(message='思维导图不存在')
            share = await MindmapShareDao.get_share_access_snapshot(
                db,
                share_token,
                for_share=True,
            )
            validate_active_share(share)
            if share.mindmap_id != mindmap.mindmap_id:
                raise ServiceException(message='分享链接不存在')

            # 编辑链接只负责授予经过身份认证的协作者权限。公开接口仅返回加入
            # 页面所需的最小元数据，不能把正文当作编辑邀请的匿名预览泄露出去。
            if share.share_type == 1:
                response = {
                    'name': mindmap.name,
                    'shareType': 1,
                    'requiresLogin': True,
                }
            else:
                node_tree = None
                migration_failed = (
                    await MindmapDao.get_migration_status(db, mindmap.mindmap_id)
                    == 'failed'
                )
                if not migration_failed and mindmap.schema_version >= SCHEMA_VERSION:
                    node_tree = await MindmapDocumentService.load_tree(
                        db,
                        mindmap.mindmap_id,
                        required=True,
                    )
                if not node_tree:
                    node_tree = mindmap.node_tree
                    if isinstance(node_tree, str):
                        node_tree = json.loads(node_tree)

                response = {
                    'name': mindmap.name,
                    'nodeTree': node_tree,
                    'layout': mindmap.layout,
                    'theme': mindmap.theme,
                    'viewData': mindmap.view_data,
                    'documentData': mindmap.document_data,
                    'shareType': share.share_type,
                }
            return response
        finally:
            # 返回值在事务结束前已经完全物化为普通 dict；主动结束只读事务，
            # 既释放共享锁，也杜绝响应序列化阶段触碰已过期 ORM 实体。
            await db.rollback()

    @classmethod
    async def join_edit_share(
        cls,
        db: AsyncSession,
        share_token: str,
        user_id: int,
    ) -> MindmapShareJoinModel:
        """让已登录用户通过有效编辑邀请成为该脑图的编辑协作者。"""
        if not SHARE_TOKEN_PATTERN.fullmatch(share_token):
            raise ServiceException(message='分享链接不存在')

        try:
            observed_share = await MindmapShareDao.get_share_access_snapshot(
                db,
                share_token,
            )
            validate_active_share(observed_share)
            # 冻结 token 指向后结束无锁探测事务；真正授权必须在下面的
            # Mindmap -> Share 排他锁事务内基于当前读重新校验。
            await db.rollback()

            # 与正文写入、协作者变更采用相同的主记录锁顺序。拿到主锁后重新
            # 锁定并校验分享记录，确保禁用/过期与领取之间具有明确先后关系。
            mindmap = await MindmapShareDao.get_mindmap_ownership_snapshot(
                db,
                observed_share.mindmap_id,
                for_update=True,
            )
            if not mindmap:
                raise ServiceException(message='思维导图不存在')
            mindmap_id = mindmap.mindmap_id
            mindmap_owner_id = mindmap.owner_id
            mindmap_status = mindmap.status
            share = await MindmapShareDao.get_share_access_snapshot(
                db,
                share_token,
                for_update=True,
            )
            validate_active_share(share)
            if share.mindmap_id != mindmap_id:
                raise ServiceException(message='分享链接不存在')
            if share.share_type != 1:
                raise ServiceException(message='该链接仅支持查看')
            if mindmap_status == 1:
                raise ServiceException(message='脑图已归档，暂时无法加入编辑')
            if mindmap_owner_id == user_id:
                response = MindmapShareJoinModel(
                    mindmapId=mindmap_id,
                    permission=1,
                    alreadyJoined=True,
                )
                await db.rollback()
                return response
            if not await MindmapCollaboratorDao.is_active_user(db, user_id):
                raise ServiceException(message='当前用户不存在或已停用')

            collaborator = await MindmapCollaboratorDao.get_collaborator(
                db,
                mindmap_id,
                user_id,
                for_update=True,
            )
            collaborator_id = int(collaborator.id) if collaborator is not None else None
            collaborator_permission = (
                int(collaborator.permission) if collaborator is not None else None
            )
            already_joined = (
                collaborator_permission is not None
                and collaborator_permission >= 1
            )
            if collaborator is None:
                await MindmapCollaboratorDao.add_collaborator(db, {
                    'mindmap_id': mindmap_id,
                    'user_id': user_id,
                    'permission': 1,
                    'created_by': share.created_by,
                    'created_time': datetime.now(),
                })
            elif collaborator_permission is not None and collaborator_permission < 1:
                await MindmapCollaboratorDao.update_permission(db, collaborator_id, 1)
            response = MindmapShareJoinModel(
                mindmapId=mindmap_id,
                permission=1,
                alreadyJoined=already_joined,
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

        return response
