"""脑图标签字段服务层"""
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import CrudResponseModel
from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_tag_field_dao import MindmapTagFieldDao
from module_mindmap.entity.vo.mindmap_tag_field_vo import (
    TagFieldModel,
    TagFieldOptionModel,
    TagFieldOptionSortModel,
)
from utils.common_util import CamelCaseUtil


def _check_write_permission(resource_owner_id: int, user_id: int, resource_name: str = '资源') -> None:
    """校验写权限：私有资源仅创建者可操作，全局资源仅管理员可操作"""
    if resource_owner_id == 0:
        if user_id != 1:
            raise ServiceException(message=f'仅管理员可修改全局{resource_name}')
    elif resource_owner_id != user_id:
        raise ServiceException(message=f'无权限修改该{resource_name}')


class MindmapTagFieldService:
    """标签字段服务层"""

    # ── 字段 ──

    @classmethod
    async def get_fields(cls, db: AsyncSession, user_id: int) -> list[dict]:
        """获取字段列表（全局 + 当前用户私有）"""
        fields = await MindmapTagFieldDao.get_fields(db, user_id)
        return [CamelCaseUtil.transform_result(f) for f in fields]

    @classmethod
    async def get_field_detail(cls, db: AsyncSession, field_id: int, user_id: int) -> dict:
        """获取字段详情（含选项列表）"""
        field = await MindmapTagFieldDao.get_field_by_id(db, field_id)
        if not field:
            raise ServiceException(message='字段不存在')
        if field.owner_id != user_id and field.owner_id != 0:
            raise ServiceException(message='无权限查看该字段')

        options = await MindmapTagFieldDao.get_options_by_field_id(db, field_id)
        result = CamelCaseUtil.transform_result(field)
        result['options'] = [CamelCaseUtil.transform_result(o) for o in options]
        return result

    @classmethod
    async def add_field(
        cls, db: AsyncSession, model: TagFieldModel, user_id: int, user_name: str,
    ) -> CrudResponseModel:
        """新增字段"""
        # 管理员可创建全局字段(owner_id=0)，普通用户只能创建私有字段
        owner_id = user_id
        if model.owner_id == 0 and user_id == 1:
            owner_id = 0

        # key 唯一性检查
        is_unique = await MindmapTagFieldDao.check_field_key_unique(db, owner_id, model.field_key)
        if not is_unique:
            raise ServiceException(message=f'字段key "{model.field_key}" 已存在')

        try:
            await MindmapTagFieldDao.add_field(db, {
                'field_key': model.field_key,
                'name': model.name,
                'select_mode': model.select_mode,
                'style': model.style,
                'owner_id': owner_id,
                'sort_order': model.sort_order or 0,
                'description': model.description,
                'created_by': user_name,
                'created_time': datetime.now(),
                'updated_time': datetime.now(),
            })
            await db.commit()
            return CrudResponseModel(is_success=True, message='字段创建成功')
        except Exception as e:
            await db.rollback()
            raise e

    @classmethod
    async def update_field(
        cls, db: AsyncSession, model: TagFieldModel, user_id: int,
    ) -> CrudResponseModel:
        """修改字段"""
        field = await MindmapTagFieldDao.get_field_by_id(db, model.id)
        if not field:
            raise ServiceException(message='字段不存在')
        _check_write_permission(field.owner_id, user_id, '字段')

        # 处理 owner_id 变更（仅管理员可在私有/全局间切换）
        new_owner_id = field.owner_id
        if model.owner_id is not None and model.owner_id != field.owner_id:
            if user_id == 1:
                new_owner_id = model.owner_id

        # key 唯一性检查（排除自身）
        if model.field_key != field.field_key:
            is_unique = await MindmapTagFieldDao.check_field_key_unique(
                db, new_owner_id, model.field_key, exclude_id=model.id,
            )
            if not is_unique:
                raise ServiceException(message=f'字段key "{model.field_key}" 已存在')

        try:
            await MindmapTagFieldDao.update_field(db, model.id, {
                'field_key': model.field_key,
                'name': model.name,
                'select_mode': model.select_mode,
                'style': model.style,
                'owner_id': new_owner_id,
                'sort_order': model.sort_order or 0,
                'description': model.description,
                'updated_time': datetime.now(),
            })
            await db.commit()
            return CrudResponseModel(is_success=True, message='字段更新成功')
        except Exception as e:
            await db.rollback()
            raise e

    @classmethod
    async def delete_field(
        cls, db: AsyncSession, field_id: int, user_id: int,
    ) -> CrudResponseModel:
        """删除字段（同时删除所有选项）"""
        field = await MindmapTagFieldDao.get_field_by_id(db, field_id)
        if not field:
            raise ServiceException(message='字段不存在')
        _check_write_permission(field.owner_id, user_id, '字段')

        try:
            # 先删选项，再删字段
            await MindmapTagFieldDao.delete_options_by_field_id(db, field_id)
            await MindmapTagFieldDao.delete_field(db, field_id)
            await db.commit()
            return CrudResponseModel(is_success=True, message='字段删除成功')
        except Exception as e:
            await db.rollback()
            raise e

    # ── 选项 ──

    @classmethod
    async def add_option(
        cls, db: AsyncSession, model: TagFieldOptionModel, user_id: int,
    ) -> CrudResponseModel:
        """新增选项"""
        field = await MindmapTagFieldDao.get_field_by_id(db, model.field_id)
        if not field:
            raise ServiceException(message='所属字段不存在')
        _check_write_permission(field.owner_id, user_id, '字段')

        # option_key 唯一性检查
        is_unique = await MindmapTagFieldDao.check_option_key_unique(
            db, model.field_id, model.option_key,
        )
        if not is_unique:
            raise ServiceException(message=f'选项key "{model.option_key}" 已存在')

        try:
            await MindmapTagFieldDao.add_option(db, {
                'field_id': model.field_id,
                'option_key': model.option_key,
                'name': model.name,
                'fill': model.fill,
                'color': model.color,
                'sort_order': model.sort_order or 0,
                'created_time': datetime.now(),
            })
            await db.commit()
            return CrudResponseModel(is_success=True, message='选项创建成功')
        except Exception as e:
            await db.rollback()
            raise e

    @classmethod
    async def update_option(
        cls, db: AsyncSession, model: TagFieldOptionModel, user_id: int,
    ) -> CrudResponseModel:
        """修改选项"""
        option = await MindmapTagFieldDao.get_option_by_id(db, model.id)
        if not option:
            raise ServiceException(message='选项不存在')

        field = await MindmapTagFieldDao.get_field_by_id(db, option.field_id)
        if not field:
            raise ServiceException(message='所属字段不存在')
        _check_write_permission(field.owner_id, user_id, '字段')

        # option_key 唯一性检查（排除自身）
        if model.option_key != option.option_key:
            is_unique = await MindmapTagFieldDao.check_option_key_unique(
                db, option.field_id, model.option_key, exclude_id=model.id,
            )
            if not is_unique:
                raise ServiceException(message=f'选项key "{model.option_key}" 已存在')

        try:
            await MindmapTagFieldDao.update_option(db, model.id, {
                'option_key': model.option_key,
                'name': model.name,
                'fill': model.fill,
                'color': model.color,
                'sort_order': model.sort_order or 0,
            })
            await db.commit()
            return CrudResponseModel(is_success=True, message='选项更新成功')
        except Exception as e:
            await db.rollback()
            raise e

    @classmethod
    async def delete_option(
        cls, db: AsyncSession, option_id: int, user_id: int,
    ) -> CrudResponseModel:
        """删除选项"""
        option = await MindmapTagFieldDao.get_option_by_id(db, option_id)
        if not option:
            raise ServiceException(message='选项不存在')

        field = await MindmapTagFieldDao.get_field_by_id(db, option.field_id)
        if not field:
            raise ServiceException(message='所属字段不存在')
        _check_write_permission(field.owner_id, user_id, '字段')

        try:
            await MindmapTagFieldDao.delete_option(db, option_id)
            await db.commit()
            return CrudResponseModel(is_success=True, message='选项删除成功')
        except Exception as e:
            await db.rollback()
            raise e

    @classmethod
    async def batch_update_option_sort(
        cls, db: AsyncSession, field_id: int,
        sort_list: list[TagFieldOptionSortModel], user_id: int,
    ) -> CrudResponseModel:
        """批量更新选项排序"""
        field = await MindmapTagFieldDao.get_field_by_id(db, field_id)
        if not field:
            raise ServiceException(message='字段不存在')
        _check_write_permission(field.owner_id, user_id, '字段')

        try:
            data = [{'option_id': s.option_id, 'sort_order': s.sort_order} for s in sort_list]
            await MindmapTagFieldDao.batch_update_option_sort(db, field_id, data)
            await db.commit()
            return CrudResponseModel(is_success=True, message='排序更新成功')
        except Exception as e:
            await db.rollback()
            raise e

    # ── 搜索建议 ──

    @classmethod
    async def get_suggestions(
        cls, db: AsyncSession, user_id: int, keyword: str | None = None,
    ) -> list[dict]:
        """获取字段搜索建议（侧边栏用）"""
        results = await MindmapTagFieldDao.get_suggestions(db, user_id, keyword)
        output = []
        for field, options in results:
            output.append({
                'fieldId': field.id,
                'fieldName': field.name,
                'fieldKey': field.field_key,
                'selectMode': field.select_mode,
                'style': field.style,
                'options': [
                    {
                        'id': o.id,
                        'optionKey': o.option_key,
                        'name': o.name,
                        'fill': o.fill,
                        'color': o.color,
                    }
                    for o in options
                ],
            })
        return output
