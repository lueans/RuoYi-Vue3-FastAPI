"""脑图标签字段服务层"""
from datetime import datetime

from sqlalchemy import distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from common.vo import CrudResponseModel
from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_tag_field_dao import MindmapTagFieldDao
from module_mindmap.entity.do.mindmap_collaborator_do import MindmapCollaborator
from module_mindmap.entity.do.mindmap_content_do import MindmapNodeTag
from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.entity.do.mindmap_tag_do import MindmapTag, MindmapTagCategory
from module_mindmap.entity.do.mindmap_tag_field_do import MindmapTagField, MindmapTagFieldOption
from module_mindmap.entity.vo.mindmap_tag_field_vo import (
    TagFieldModel,
    TagFieldOptionModel,
    TagFieldOptionSortModel,
)
from module_mindmap.service.mindmap_document_service import MindmapDocumentService
from module_mindmap.websocket.room_manager import room_manager
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
        if field.owner_id not in (user_id, 0):
            raise ServiceException(message='无权限查看该字段')

        options = await MindmapTagFieldDao.get_options_by_field_id(db, field_id)
        result = CamelCaseUtil.transform_result(field)
        result['options'] = [CamelCaseUtil.transform_result(o) for o in options]
        return result

    @classmethod
    async def get_field_impact(cls, db: AsyncSession, field_id: int, user_id: int) -> dict:
        """返回字段默认样式或选择模式变更影响的可见文件与节点。"""
        field = await MindmapTagFieldDao.get_field_by_id(db, field_id)
        if not field:
            raise ServiceException(message='字段不存在')
        if field.owner_id not in (0, user_id):
            raise ServiceException(message='无权限查看该字段影响范围')

        options = await MindmapTagFieldDao.get_options_by_field_id(db, field_id)
        option_ids = [option.id for option in options]
        binding_filter = cls._field_binding_filter(field_id, option_ids)
        impact_query = (
            select(
                Mindmap.id,
                Mindmap.name,
                func.count(distinct(MindmapNodeTag.node_id)),
            )
            .join(MindmapNodeTag, MindmapNodeTag.file_id == Mindmap.id)
            .where(binding_filter, Mindmap.del_flag == '0')
            .group_by(Mindmap.id, Mindmap.name, Mindmap.update_time)
            .order_by(Mindmap.update_time.desc())
        )
        if user_id != 1:
            impact_query = impact_query.where(or_(
                Mindmap.owner_id == user_id,
                Mindmap.id.in_(select(MindmapCollaborator.mindmap_id).where(
                    MindmapCollaborator.user_id == user_id,
                )),
            ))
        rows = (await db.execute(impact_query)).all()
        files = [
            {'id': file_id, 'name': name, 'nodeCount': node_count}
            for file_id, name, node_count in rows
        ]
        conflict_count = await cls._count_multi_selection_nodes(
            db, field_id, user_id=user_id, option_ids=option_ids,
        )
        return {
            'fieldId': field_id,
            'fileCount': len(files),
            'nodeCount': sum(item['nodeCount'] for item in files),
            'optionCount': len(options),
            'multiSelectionNodeCount': conflict_count,
            'files': files[:20],
        }

    @staticmethod
    def _field_binding_filter(field_id: int, option_ids: list[int]) -> ColumnElement[bool]:
        conditions = [MindmapNodeTag.field_id == field_id]
        if option_ids:
            conditions.append(MindmapNodeTag.option_id.in_(option_ids))
        return or_(*conditions)

    @classmethod
    async def _count_multi_selection_nodes(
        cls, db: AsyncSession, field_id: int, user_id: int | None = None,
        option_ids: list[int] | None = None,
    ) -> int:
        """统计同一节点绑定当前字段多个选项的数量。"""
        if option_ids is None:
            options = await MindmapTagFieldDao.get_options_by_field_id(db, field_id)
            option_ids = [option.id for option in options]
        binding_filter = cls._field_binding_filter(field_id, option_ids)
        conflicts_query = (
            select(MindmapNodeTag.node_id)
            .join(Mindmap, Mindmap.id == MindmapNodeTag.file_id)
            .where(
                binding_filter,
                MindmapNodeTag.option_id.is_not(None),
                Mindmap.del_flag == '0',
            )
            .group_by(MindmapNodeTag.node_id)
            .having(func.count(distinct(MindmapNodeTag.option_id)) > 1)
        )
        if user_id not in (None, 1):
            conflicts_query = conflicts_query.where(or_(
                Mindmap.owner_id == user_id,
                Mindmap.id.in_(select(MindmapCollaborator.mindmap_id).where(
                    MindmapCollaborator.user_id == user_id,
                )),
            ))
        conflicts = conflicts_query.subquery()
        return (await db.execute(select(func.count()).select_from(conflicts))).scalar_one()

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
            field = await MindmapTagFieldDao.add_field(db, {
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
            return CrudResponseModel(
                is_success=True,
                message='字段创建成功',
                result={'fieldId': field.id},
            )
        except Exception as e:
            await db.rollback()
            raise e

    @classmethod
    async def update_field(  # noqa: PLR0912
        cls, db: AsyncSession, model: TagFieldModel, user_id: int,
    ) -> CrudResponseModel:
        """修改字段"""
        field = await MindmapTagFieldDao.get_field_by_id(db, model.id)
        if not field:
            raise ServiceException(message='字段不存在')
        _check_write_permission(field.owner_id, user_id, '字段')

        if field.select_mode != 'single' and model.select_mode == 'single':
            conflict_count = await cls._count_multi_selection_nodes(db, model.id)
            if conflict_count:
                raise ServiceException(
                    message=(
                        f'当前有 {conflict_count} 个节点使用了该字段的多个选项，'
                        '请先清理冲突后再切换为单选'
                    )
                )

        # 处理 owner_id 变更（仅管理员可在私有/全局间切换）
        new_owner_id = field.owner_id
        if model.owner_id is not None and model.owner_id != field.owner_id and user_id == 1:
            new_owner_id = model.owner_id

        # key 唯一性检查（排除自身）
        if model.field_key != field.field_key or new_owner_id != field.owner_id:
            is_unique = await MindmapTagFieldDao.check_field_key_unique(
                db, new_owner_id, model.field_key, exclude_id=model.id,
            )
            if not is_unique:
                raise ServiceException(message=f'字段key "{model.field_key}" 已存在')

        old_style = dict(field.style or {})
        style_changed = (field.style or {}) != (model.style or {})
        owner_changed = new_owner_id != field.owner_id
        options = []
        option_tags = []
        if style_changed or owner_changed:
            options = await MindmapTagFieldDao.get_options_by_field_id(db, model.id)
        if owner_changed:
            option_tags = await cls._validate_option_tag_scope_change(
                db, model.id, options, new_owner_id,
            )
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
            for tag in option_tags:
                tag.owner_id = new_owner_id
                tag.definition_revision = (tag.definition_revision or 1) + 1
                tag.updated_time = datetime.now()
                tag.update_by = str(user_id)
            option_events = []
            if style_changed:
                for option in options:
                    tag, affected_file_ids, resolved_style = (
                        await MindmapDocumentService.sync_option_tag_definition(
                            db, option.id, str(user_id), inherited_style=old_style,
                        )
                    )
                    if tag:
                        option_events.append((tag, affected_file_ids, resolved_style))
            await db.commit()
            for tag, affected_file_ids, resolved_style in option_events:
                event = {
                    'type': 'tag_definition_changed',
                    'tagId': tag.id,
                    'definitionRevision': tag.definition_revision,
                    'changedFields': ['style'],
                    'definition': {
                        'tagId': tag.id,
                        'uuid': tag.uuid,
                        'tagKey': tag.tag_key,
                        'text': tag.name,
                        'style': resolved_style,
                        'status': tag.status,
                    },
                }
                for file_id in affected_file_ids:
                    await room_manager.broadcast(file_id, event)
            return CrudResponseModel(is_success=True, message='字段更新成功')
        except Exception as e:
            await db.rollback()
            raise e

    @staticmethod
    async def _validate_option_tag_scope_change(
        db: AsyncSession, field_id: int, options: list, new_owner_id: int,
    ) -> list[MindmapTag]:
        """锁定关联标签并确保切换字段作用域不会破坏既有绑定。"""
        tag_ids = sorted({option.tag_id for option in options if option.tag_id})
        if not tag_ids:
            return []
        tags = list((await db.execute(
            select(MindmapTag)
            .where(MindmapTag.id.in_(tag_ids))
            .order_by(MindmapTag.id.asc())
            .with_for_update()
        )).scalars())
        if len(tags) != len(tag_ids):
            raise ServiceException(message='字段选项关联的标签不存在，无法切换作用域')

        if new_owner_id != 0:
            foreign_file_count = (await db.execute(
                select(func.count(distinct(MindmapNodeTag.file_id)))
                .join(Mindmap, Mindmap.id == MindmapNodeTag.file_id)
                .where(
                    MindmapNodeTag.tag_id.in_(tag_ids),
                    Mindmap.del_flag == '0',
                    Mindmap.owner_id != new_owner_id,
                )
            )).scalar_one()
            if foreign_file_count:
                raise ServiceException(
                    message=(
                        f'字段选项仍被 {foreign_file_count} 个其他所有者的脑图使用，'
                        '不能收窄为私有字段'
                    )
                )

        linked_field_mismatch = (await db.execute(
            select(func.count(MindmapTagFieldOption.id))
            .join(MindmapTagField, MindmapTagField.id == MindmapTagFieldOption.field_id)
            .where(
                MindmapTagFieldOption.tag_id.in_(tag_ids),
                MindmapTagFieldOption.field_id != field_id,
                MindmapTagField.owner_id != new_owner_id,
            )
        )).scalar_one()
        if linked_field_mismatch:
            raise ServiceException(message='关联标签同时被其他作用域字段使用，无法切换字段作用域')

        category_scope_mismatch = (await db.execute(
            select(func.count(MindmapTag.id))
            .join(MindmapTagCategory, MindmapTagCategory.id == MindmapTag.category_id)
            .where(
                MindmapTag.id.in_(tag_ids),
                MindmapTagCategory.owner_id.not_in((0, new_owner_id)),
            )
        )).scalar_one()
        if category_scope_mismatch:
            raise ServiceException(message='关联标签所属分类与目标作用域不兼容，无法切换字段作用域')

        target_conflict = (await db.execute(
            select(func.count(MindmapTag.id)).where(
                MindmapTag.owner_id == new_owner_id,
                MindmapTag.tag_key.in_([tag.tag_key for tag in tags]),
                MindmapTag.id.not_in(tag_ids),
            )
        )).scalar_one()
        if target_conflict:
            raise ServiceException(message='目标作用域已存在同 Key 标签，无法切换字段作用域')
        return tags

    @classmethod
    async def delete_field(
        cls, db: AsyncSession, field_id: int, user_id: int,
    ) -> CrudResponseModel:
        """删除字段（同时删除所有选项）"""
        field = await MindmapTagFieldDao.get_field_by_id(db, field_id)
        if not field:
            raise ServiceException(message='字段不存在')
        _check_write_permission(field.owner_id, user_id, '字段')

        options = await MindmapTagFieldDao.get_options_by_field_id(db, field_id)
        option_ids = [option.id for option in options]
        binding_filter = cls._field_binding_filter(field_id, option_ids)
        actual_count = (await db.execute(
            select(func.count(MindmapNodeTag.id)).where(binding_filter)
        )).scalar_one()
        if actual_count:
            raise ServiceException(
                message=f'字段仍被 {actual_count} 个节点使用，请先停用或解除绑定'
            )

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
            option = await MindmapTagFieldDao.add_option(db, {
                'field_id': model.field_id,
                'option_key': model.option_key,
                'name': model.name,
                'fill': model.fill,
                'color': model.color,
                'sort_order': model.sort_order or 0,
                'created_time': datetime.now(),
            })
            tag, _, _ = await MindmapDocumentService.sync_option_tag_definition(
                db, option.id, str(user_id),
            )
            await db.commit()
            return CrudResponseModel(
                is_success=True,
                message='选项创建成功',
                result={'optionId': option.id, 'tagId': tag.id if tag else None},
            )
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
            await db.flush()
            tag, affected_file_ids, resolved_style = await MindmapDocumentService.sync_option_tag_definition(
                db, model.id, str(user_id),
            )
            await db.commit()
            if tag:
                event = {
                    'type': 'tag_definition_changed',
                    'tagId': tag.id,
                    'definitionRevision': tag.definition_revision,
                    'changedFields': ['name', 'style'],
                    'definition': {
                        'tagId': tag.id,
                        'uuid': tag.uuid,
                        'tagKey': tag.tag_key,
                        'text': tag.name,
                        'style': resolved_style,
                        'status': tag.status,
                    },
                }
                for file_id in affected_file_ids:
                    await room_manager.broadcast(file_id, event)
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

        actual_count = (await db.execute(
            select(func.count(MindmapNodeTag.id)).where(MindmapNodeTag.option_id == option_id)
        )).scalar_one()
        if actual_count:
            raise ServiceException(
                message=f'选项“{option.name}”仍被 {actual_count} 个节点使用，请先停用或解除绑定'
            )

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
                'id': field.id,
                'name': field.name,
                'fieldKey': field.field_key,
                'selectMode': field.select_mode,
                'style': field.style,
                'options': [
                    {
                        'id': o.id,
                        'tagId': o.tag_id,
                        'optionKey': o.option_key,
                        'name': o.name,
                        'fill': o.fill,
                        'color': o.color,
                    }
                    for o in options
                ],
            })
        return output
