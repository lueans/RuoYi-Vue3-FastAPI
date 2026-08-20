"""脑图分享链接服务层"""
import json
import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import CrudResponseModel
from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_dao import MindmapDao
from module_mindmap.dao.mindmap_share_dao import MindmapShareDao
from module_mindmap.entity.vo.mindmap_share_vo import MindmapShareCreateModel, MindmapShareModel
from module_mindmap.service.mindmap_document_service import MindmapDocumentService
from module_mindmap.service.simple_mind_document_codec import SCHEMA_VERSION
from utils.common_util import CamelCaseUtil

SHARE_TOKEN_PATTERN = re.compile(r'^[0-9a-f]{32}$')


def normalize_share_expire_time(value: datetime | None) -> datetime | None:
    """将带时区的浏览器时间转换为数据库使用的本地无时区时间。"""
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone().replace(tzinfo=None)
    return value


class MindmapShareService:
    """分享链接服务层"""

    @classmethod
    async def create_share_link(
        cls, db: AsyncSession, model: MindmapShareCreateModel, user_id: int,
    ) -> CrudResponseModel:
        """创建分享链接"""
        if model.share_type != 0:
            raise ServiceException(message='公开分享仅支持只读查看，协作编辑请使用协作者功能')
        expire_time = normalize_share_expire_time(model.expire_time)
        if expire_time is not None and expire_time <= datetime.now():
            raise ServiceException(message='分享链接过期时间必须晚于当前时间')
        # 验证脑图所有权
        mindmap = await MindmapDao.get_mindmap_for_update(db, model.mindmap_id)
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
        mindmap = await MindmapDao.get_mindmap_by_id(db, mindmap_id)
        if not mindmap:
            raise ServiceException(message='思维导图不存在')
        if mindmap.owner_id != user_id:
            raise ServiceException(message='无权限查看')

        shares = await MindmapShareDao.get_shares_by_mindmap_id(db, mindmap_id)
        return [
            MindmapShareModel(**CamelCaseUtil.transform_result(s))
            for s in shares
        ]

    @classmethod
    async def delete_share_link(
        cls, db: AsyncSession, share_id: int, user_id: int,
    ) -> CrudResponseModel:
        """禁用分享链接"""
        share = await MindmapShareDao.get_share_by_id(db, share_id)
        if not share:
            raise ServiceException(message='分享链接不存在')

        mindmap = await MindmapDao.get_mindmap_by_id(db, share.mindmap_id)
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
        share = await MindmapShareDao.get_share_by_token(db, share_token)
        if not share:
            raise ServiceException(message='分享链接不存在')
        if not share.is_active:
            raise ServiceException(message='分享链接已失效')

        # 检查过期时间
        expire_time = normalize_share_expire_time(share.expire_time)
        if expire_time and expire_time <= datetime.now():
            raise ServiceException(message='分享链接已过期')

        # 获取脑图数据
        mindmap = await MindmapDao.get_mindmap_by_id(db, share.mindmap_id)
        if not mindmap:
            raise ServiceException(message='思维导图不存在')

        result_dict = CamelCaseUtil.transform_result(mindmap)
        node_tree = None
        migration_failed = await MindmapDao.get_migration_status(db, mindmap.id) == 'failed'
        if not migration_failed and getattr(mindmap, 'schema_version', 1) >= SCHEMA_VERSION:
            node_tree = await MindmapDocumentService.load_tree(db, mindmap.id, required=True)
        if not node_tree:
            node_tree = result_dict.get('nodeTree')
            if isinstance(node_tree, str):
                node_tree = json.loads(node_tree)

        return {
            'name': mindmap.name,
            'nodeTree': node_tree,
            'layout': mindmap.layout,
            'theme': mindmap.theme,
            'viewData': mindmap.view_data,
            'documentData': mindmap.document_data,
            'shareType': 0,
        }
