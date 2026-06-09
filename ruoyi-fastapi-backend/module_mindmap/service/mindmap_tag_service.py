"""脑图标签服务层"""
import uuid as uuid_lib
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import CrudResponseModel, PageModel
from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_tag_dao import MindmapTagDao
from module_mindmap.entity.vo.mindmap_tag_vo import (
    MindmapTagModel,
    MindmapTagQueryModel,
)
from utils.common_util import CamelCaseUtil


def _check_write_permission(resource_owner_id: int, user_id: int, resource_name: str = '资源') -> None:
    """校验写权限：私有资源仅创建者可操作，全局资源仅管理员可操作"""
    if resource_owner_id == 0:
        if user_id != 1:
            raise ServiceException(message=f'仅管理员可修改全局{resource_name}')
    elif resource_owner_id != user_id:
        raise ServiceException(message=f'无权限修改该{resource_name}')


class MindmapTagService:
    """标签服务层"""

    # ── 分类 ──

    @classmethod
    async def get_categories(cls, db: AsyncSession, user_id: int) -> list[dict]:
        """获取分类列表（全局 + 当前用户私有）"""
        categories = await MindmapTagDao.get_categories(db, user_id)
        return [CamelCaseUtil.transform_result(c) for c in categories]

    @classmethod
    async def add_category(
        cls, db: AsyncSession, name: str, user_id: int, user_name: str,
        sort_order: int = 0,
    ) -> CrudResponseModel:
        """新增分类"""
        try:
            await MindmapTagDao.add_category(db, {
                'name': name,
                'owner_id': user_id,
                'sort_order': sort_order,
                'created_by': user_name,
                'created_time': datetime.now(),
            })
            await db.commit()
            return CrudResponseModel(is_success=True, message='分类创建成功')
        except Exception as e:
            await db.rollback()
            raise e

    @classmethod
    async def update_category(
        cls, db: AsyncSession, category_id: int, name: str,
        sort_order: int, user_id: int,
    ) -> CrudResponseModel:
        """修改分类"""
        cat = await MindmapTagDao.get_category_by_id(db, category_id)
        if not cat:
            raise ServiceException(message='分类不存在')
        _check_write_permission(cat.owner_id, user_id, '分类')
        try:
            await MindmapTagDao.update_category(db, category_id, {
                'name': name,
                'sort_order': sort_order,
            })
            await db.commit()
            return CrudResponseModel(is_success=True, message='分类更新成功')
        except Exception as e:
            await db.rollback()
            raise e

    @classmethod
    async def delete_category(
        cls, db: AsyncSession, category_id: int, user_id: int,
    ) -> CrudResponseModel:
        """删除分类（检查关联标签）"""
        cat = await MindmapTagDao.get_category_by_id(db, category_id)
        if not cat:
            raise ServiceException(message='分类不存在')
        _check_write_permission(cat.owner_id, user_id, '分类')

        tag_count = await MindmapTagDao.count_tags_in_category(db, category_id)
        if tag_count > 0:
            raise ServiceException(message=f'该分类下还有 {tag_count} 个标签，请先移除或转移')

        try:
            await MindmapTagDao.delete_category(db, category_id)
            await db.commit()
            return CrudResponseModel(is_success=True, message='分类删除成功')
        except Exception as e:
            await db.rollback()
            raise e

    # ── 标签 ──

    @classmethod
    async def get_tag_list(
        cls, db: AsyncSession, query: MindmapTagQueryModel, user_id: int,
    ) -> PageModel:
        """获取标签列表"""
        return await MindmapTagDao.get_tag_list(
            db, user_id,
            category_id=query.category_id,
            keyword=query.keyword,
            owner_scope=query.owner_scope or 'all',
            page_num=query.page_num,
            page_size=query.page_size,
        )

    @classmethod
    async def get_tag_detail(cls, db: AsyncSession, tag_id: int, user_id: int) -> dict:
        """获取标签详情"""
        tag = await MindmapTagDao.get_tag_by_id(db, tag_id)
        if not tag:
            raise ServiceException(message='标签不存在')
        if tag.owner_id != user_id and tag.owner_id != 0:
            raise ServiceException(message='无权限查看该标签')
        return CamelCaseUtil.transform_result(tag)

    @classmethod
    async def add_tag(
        cls, db: AsyncSession, model: MindmapTagModel, user_id: int, user_name: str,
    ) -> CrudResponseModel:
        """新增标签"""
        # 管理员可创建全局标签(owner_id=0)，普通用户只能创建私有标签
        owner_id = user_id
        if model.owner_id == 0 and user_id == 1:
            owner_id = 0

        # key 唯一性检查
        is_unique = await MindmapTagDao.check_key_unique(db, owner_id, model.tag_key)
        if not is_unique:
            raise ServiceException(message=f'标签key "{model.tag_key}" 已存在')

        try:
            await MindmapTagDao.add_tag(db, {
                'uuid': str(uuid_lib.uuid4()),
                'tag_key': model.tag_key,
                'name': model.name,
                'category_id': model.category_id,
                'owner_id': owner_id,
                'style': model.style,
                'description': model.description,
                'created_by': user_name,
                'created_time': datetime.now(),
                'updated_time': datetime.now(),
            })
            await db.commit()
            return CrudResponseModel(is_success=True, message='标签创建成功')
        except Exception as e:
            await db.rollback()
            raise e

    @classmethod
    async def update_tag(
        cls, db: AsyncSession, model: MindmapTagModel, user_id: int,
    ) -> CrudResponseModel:
        """修改标签"""
        tag = await MindmapTagDao.get_tag_by_id(db, model.id)
        if not tag:
            raise ServiceException(message='标签不存在')
        _check_write_permission(tag.owner_id, user_id, '标签')

        # key 唯一性检查（排除自身），使用标签自身的 owner scope
        if model.tag_key != tag.tag_key:
            is_unique = await MindmapTagDao.check_key_unique(
                db, tag.owner_id, model.tag_key, exclude_id=model.id,
            )
            if not is_unique:
                raise ServiceException(message=f'标签key "{model.tag_key}" 已存在')

        try:
            await MindmapTagDao.update_tag(db, model.id, {
                'tag_key': model.tag_key,
                'name': model.name,
                'category_id': model.category_id,
                'style': model.style,
                'description': model.description,
                'updated_time': datetime.now(),
            })
            await db.commit()
            return CrudResponseModel(is_success=True, message='标签更新成功')
        except Exception as e:
            await db.rollback()
            raise e

    @classmethod
    async def delete_tags(
        cls, db: AsyncSession, ids_str: str, user_id: int,
    ) -> CrudResponseModel:
        """批量删除标签"""
        id_list = [int(i) for i in ids_str.split(',') if i.strip()]
        if not id_list:
            raise ServiceException(message='传入标签ID为空')

        # 逐个校验权限
        for tag_id in id_list:
            tag = await MindmapTagDao.get_tag_by_id(db, tag_id)
            if tag:
                _check_write_permission(tag.owner_id, user_id, '标签')

        try:
            await MindmapTagDao.delete_tags(db, id_list)
            await db.commit()
            return CrudResponseModel(is_success=True, message='标签删除成功')
        except Exception as e:
            await db.rollback()
            raise e

    @classmethod
    async def get_suggestions(
        cls, db: AsyncSession, user_id: int, keyword: str | None = None,
    ) -> list[dict]:
        """获取标签建议（编辑器自动补全）"""
        tags = await MindmapTagDao.get_suggestions(db, user_id, keyword)
        return [CamelCaseUtil.transform_result(t) for t in tags]
