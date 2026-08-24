"""脑图标签服务层"""
import uuid as uuid_lib
from datetime import datetime

from sqlalchemy import and_, delete, distinct, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from common.vo import CrudResponseModel, PageModel
from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_tag_dao import MindmapTagDao
from module_mindmap.entity.do.mindmap_collaborator_do import MindmapCollaborator
from module_mindmap.entity.do.mindmap_content_do import MindmapChangeLog, MindmapNode, MindmapNodeTag
from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.entity.do.mindmap_tag_do import MindmapTag
from module_mindmap.entity.do.mindmap_ws_state_do import MindmapWsState
from module_mindmap.entity.vo.mindmap_tag_vo import (
    MAX_MINDMAP_TAG_BATCH_SIZE,
    MAX_MINDMAP_TAG_ID,
    MindmapTagCategoryMutationModel,
    MindmapTagCategoryReorderModel,
    MindmapTagModel,
    MindmapTagQueryModel,
)
from module_mindmap.service.mindmap_metrics import (
    observe_mindmap_operation,
    record_mindmap_event,
)
from module_mindmap.websocket.room_manager import room_manager
from utils.common_util import CamelCaseUtil
from utils.log_util import logger

TAG_STATUS_ACTIVE = 0
TAG_STATUS_DISABLED = 1
TAG_STATUS_ARCHIVED = 2


def _tag_impact_metric_units(
    args: tuple, kwargs: dict, result: dict,
) -> int:
    del args, kwargs
    return max(0, int(result.get('nodeCount') or 0))


def _tag_archive_metric_units(
    args: tuple, kwargs: dict, result: CrudResponseModel,
) -> int:
    del args, kwargs
    payload = result.result if isinstance(result.result, dict) else {}
    return len(payload.get('tagIds') or ())


def _tag_replace_metric_units(
    args: tuple, kwargs: dict, result: CrudResponseModel,
) -> int:
    del args, kwargs
    payload = result.result if isinstance(result.result, dict) else {}
    return max(0, int(payload.get('replacedNodeCount') or 0))


def _check_write_permission(resource_owner_id: int, user_id: int, resource_name: str = '资源') -> None:
    """校验写权限：私有资源仅创建者可操作，全局资源仅管理员可操作"""
    if resource_owner_id == 0:
        if user_id != 1:
            raise ServiceException(message=f'仅管理员可修改全局{resource_name}')
    elif resource_owner_id != user_id:
        raise ServiceException(message=f'无权限修改该{resource_name}')


async def _validate_category_assignment(
    db: AsyncSession, category_id: int | None, tag_owner_id: int,
) -> None:
    """标签只能归入全局分组或与标签同所有者的私有分组。"""
    if category_id is None:
        return
    category = await MindmapTagDao.get_category_by_id(db, category_id, for_update=True)
    if not category:
        raise ServiceException(message='标签分组不存在')
    if category.owner_id not in (0, tag_owner_id):
        raise ServiceException(message='标签分组不属于当前标签作用域')


class MindmapTagService:
    """标签服务层"""

    # ── 标签分组（兼容 category 命名） ──

    @classmethod
    async def get_categories(cls, db: AsyncSession, user_id: int) -> list[dict]:
        """获取分组列表（全局 + 当前用户私有）"""
        categories = await MindmapTagDao.get_categories(db, user_id)
        counts = await MindmapTagDao.get_category_tag_counts(db, [category.id for category in categories])
        result = []
        for category in categories:
            item = CamelCaseUtil.transform_result(category)
            item['tagCount'] = counts.get(category.id, 0)
            result.append(item)
        return result

    @classmethod
    async def add_category(
        cls,
        db: AsyncSession,
        model: MindmapTagCategoryMutationModel,
        user_id: int,
        user_name: str,
    ) -> CrudResponseModel:
        """新增分组"""
        if model.owner_scope == 'global' and user_id != 1:
            raise ServiceException(message='仅管理员可创建全局分组')
        owner_id = 0 if model.owner_scope == 'global' else user_id
        is_unique = await MindmapTagDao.check_category_name_unique(db, owner_id, model.name)
        if not is_unique:
            raise ServiceException(message=f'分组“{model.name}”已存在')
        try:
            category = await MindmapTagDao.add_category(db, {
                'name': model.name,
                'category_type': 'custom',
                'owner_id': owner_id,
                'sort_order': model.sort_order,
                'created_by': user_name,
                'created_time': datetime.now(),
            })
            await db.commit()
            return CrudResponseModel(
                is_success=True,
                message='分组创建成功',
                result={'categoryId': category.id},
            )
        except IntegrityError as exc:
            await db.rollback()
            raise ServiceException(message=f'分组“{model.name}”已存在') from exc
        except Exception:
            await db.rollback()
            raise

    @classmethod
    async def reorder_categories(
        cls,
        db: AsyncSession,
        model: MindmapTagCategoryReorderModel,
        user_id: int,
    ) -> CrudResponseModel:
        """调整同一所有者范围内的完整分组顺序。"""
        requested_ids = model.category_ids
        requested_id_set = set(requested_ids)
        visible_categories = await MindmapTagDao.get_categories(db, user_id)
        requested_categories = [
            category for category in visible_categories if category.id in requested_id_set
        ]
        if len(requested_categories) != len(requested_ids):
            raise ServiceException(message='分组列表已变化，请刷新后重试')

        owner_ids = {category.owner_id for category in requested_categories}
        if len(owner_ids) != 1:
            raise ServiceException(message='一次只能调整同一范围内的分组')
        owner_id = owner_ids.pop()
        _check_write_permission(owner_id, user_id, '分组排序')

        try:
            owner_categories = await MindmapTagDao.get_categories_by_owner(
                db, owner_id, for_update=True,
            )
            if {category.id for category in owner_categories} != requested_id_set:
                raise ServiceException(message='分组列表已变化，请刷新后重试')
            await MindmapTagDao.update_category_sort_orders(db, requested_ids)
            await db.commit()
            return CrudResponseModel(is_success=True, message='分组排序已更新')
        except ServiceException:
            await db.rollback()
            raise
        except Exception:
            await db.rollback()
            raise

    @classmethod
    async def update_category(
        cls,
        db: AsyncSession,
        category_id: int,
        model: MindmapTagCategoryMutationModel,
        user_id: int,
    ) -> CrudResponseModel:
        """修改分组"""
        cat = await MindmapTagDao.get_category_by_id(db, category_id, for_update=True)
        if not cat:
            raise ServiceException(message='分组不存在')
        _check_write_permission(cat.owner_id, user_id, '分组')
        is_unique = await MindmapTagDao.check_category_name_unique(
            db,
            cat.owner_id,
            model.name,
            exclude_id=category_id,
        )
        if not is_unique:
            raise ServiceException(message=f'分组“{model.name}”已存在')
        try:
            await MindmapTagDao.update_category(db, category_id, {
                'name': model.name,
                'sort_order': model.sort_order,
            })
            await db.commit()
            return CrudResponseModel(is_success=True, message='分组更新成功')
        except IntegrityError as exc:
            await db.rollback()
            raise ServiceException(message=f'分组“{model.name}”已存在') from exc
        except Exception:
            await db.rollback()
            raise

    @classmethod
    async def delete_category(
        cls, db: AsyncSession, category_id: int, user_id: int,
    ) -> CrudResponseModel:
        """删除分组（检查关联标签）"""
        cat = await MindmapTagDao.get_category_by_id(db, category_id, for_update=True)
        if not cat:
            raise ServiceException(message='分组不存在')
        _check_write_permission(cat.owner_id, user_id, '分组')

        tag_count = await MindmapTagDao.count_tags_in_category(db, category_id)
        if tag_count > 0:
            raise ServiceException(message=f'该分组下还有 {tag_count} 个标签，请先移除或转移')

        try:
            await MindmapTagDao.delete_category(db, category_id)
            await db.commit()
            return CrudResponseModel(is_success=True, message='分组删除成功')
        except IntegrityError as exc:
            await db.rollback()
            raise ServiceException(message='该分组正在被标签使用，请刷新后重试') from exc
        except Exception:
            await db.rollback()
            raise

    # ── 标签 ──

    @classmethod
    async def get_tag_list(
        cls, db: AsyncSession, query: MindmapTagQueryModel, user_id: int,
    ) -> PageModel:
        """获取标签列表"""
        result = await MindmapTagDao.get_tag_list(
            db, user_id,
            category_id=query.category_id,
            status=query.status,
            keyword=query.keyword,
            owner_scope=query.owner_scope or 'all',
            page_num=query.page_num,
            page_size=query.page_size,
        )
        return result

    @classmethod
    async def get_tag_detail(cls, db: AsyncSession, tag_id: int, user_id: int) -> dict:
        """获取标签详情"""
        tag = await MindmapTagDao.get_tag_by_id(db, tag_id)
        if not tag:
            raise ServiceException(message='标签不存在')
        if tag.owner_id not in (user_id, 0):
            raise ServiceException(message='无权限查看该标签')
        return CamelCaseUtil.transform_result(tag)

    @classmethod
    @observe_mindmap_operation('tag_impact', work_units_getter=_tag_impact_metric_units)
    async def get_tag_impact(cls, db: AsyncSession, tag_id: int, user_id: int) -> dict:
        """返回标签修改/删除前的真实影响范围。"""
        tag = await MindmapTagDao.get_tag_by_id(db, tag_id)
        if not tag:
            raise ServiceException(message='标签不存在')
        if tag.owner_id not in (0, user_id):
            raise ServiceException(message='无权限查看该标签影响范围')
        impact_query = (
            select(Mindmap.id, Mindmap.name, func.count(MindmapNodeTag.node_id))
            .join(MindmapNodeTag, MindmapNodeTag.file_id == Mindmap.id)
            .where(MindmapNodeTag.tag_id == tag_id, Mindmap.del_flag == '0')
            .group_by(Mindmap.id, Mindmap.name, Mindmap.update_time)
            .order_by(Mindmap.update_time.desc())
        )
        if user_id != 1:
            from module_mindmap.entity.do.mindmap_collaborator_do import MindmapCollaborator  # noqa: PLC0415

            impact_query = impact_query.where(or_(
                Mindmap.owner_id == user_id,
                Mindmap.id.in_(select(MindmapCollaborator.mindmap_id).where(
                    MindmapCollaborator.user_id == user_id,
                )),
            ))
        rows = (await db.execute(impact_query)).all()
        files = {
            file_id: {'id': file_id, 'name': file_name, 'nodeCount': node_count}
            for file_id, file_name, node_count in rows
        }
        return {
            'tagId': tag_id,
            'fileCount': len(files),
            'nodeCount': sum(item['nodeCount'] for item in files.values()),
            'files': list(files.values())[:20],
        }

    @classmethod
    async def get_tag_usages(
        cls, db: AsyncSession, tag_id: int, user_id: int,
        page_num: int = 1, page_size: int = 20,
    ) -> PageModel:
        """分页返回当前用户可访问的标签使用节点，避免泄露其他用户文件。"""
        tag = await MindmapTagDao.get_tag_by_id(db, tag_id)
        if not tag:
            raise ServiceException(message='标签不存在')
        if tag.owner_id not in (0, user_id):
            raise ServiceException(message='无权限查看该标签使用明细')

        from module_mindmap.entity.do.mindmap_collaborator_do import MindmapCollaborator  # noqa: PLC0415

        accessible_files = select(MindmapCollaborator.mindmap_id).where(
            MindmapCollaborator.user_id == user_id,
        )
        query = (
            select(
                MindmapNodeTag.id,
                Mindmap.id.label('file_id'),
                Mindmap.name.label('file_name'),
                MindmapNode.node_uid,
                MindmapNode.text_plain,
                MindmapNodeTag.placement,
                MindmapNodeTag.align,
                MindmapNodeTag.sort_order,
            )
            .join(MindmapNode, MindmapNode.id == MindmapNodeTag.node_id)
            .join(Mindmap, Mindmap.id == MindmapNodeTag.file_id)
            .where(
                MindmapNodeTag.tag_id == tag_id,
                MindmapNode.is_deleted == 0,
                Mindmap.del_flag == '0',
                or_(Mindmap.owner_id == user_id, Mindmap.id.in_(accessible_files)),
            )
            .order_by(Mindmap.update_time.desc(), MindmapNodeTag.id.desc())
        )
        from utils.page_util import PageUtil  # noqa: PLC0415
        return await PageUtil.paginate(db, query, page_num, page_size, True)

    @classmethod
    async def add_tag(
        cls, db: AsyncSession, model: MindmapTagModel, user_id: int, user_name: str,
    ) -> CrudResponseModel:
        """新增标签"""
        # 管理员可创建全局标签(owner_id=0)，普通用户只能创建私有标签
        owner_id = user_id
        if model.owner_id == 0 and user_id == 1:
            owner_id = 0
        await _validate_category_assignment(db, model.category_id, owner_id)

        # key 唯一性检查
        is_unique = await MindmapTagDao.check_key_unique(db, owner_id, model.tag_key)
        if not is_unique:
            raise ServiceException(message=f'标签key "{model.tag_key}" 已存在')

        try:
            tag = await MindmapTagDao.add_tag(db, {
                'uuid': str(uuid_lib.uuid4()),
                'tag_key': model.tag_key,
                'name': model.name,
                'category_id': model.category_id,
                'owner_id': owner_id,
                'style': model.style,
                'description': model.description,
                'status': model.status or 0,
                'definition_revision': 1,
                'usage_node_count': 0,
                'usage_file_count': 0,
                'created_by': user_name,
                'created_time': datetime.now(),
                'updated_time': datetime.now(),
                'update_by': user_name,
            })
            tag_result = CamelCaseUtil.transform_result(tag)
            await db.commit()
            return CrudResponseModel(
                is_success=True,
                message='标签创建成功',
                result=tag_result,
            )
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
        # 处理 owner_id 变更（仅管理员可在私有/全局间切换）
        new_owner_id = tag.owner_id
        if model.owner_id is not None and model.owner_id != tag.owner_id and user_id == 1:
            new_owner_id = model.owner_id
            # 非管理员忽略 owner_id 变更请求
        await _validate_category_assignment(db, model.category_id, new_owner_id)

        if new_owner_id not in (tag.owner_id, 0):
            foreign_file_count = (await db.execute(
                select(func.count(distinct(MindmapNodeTag.file_id)))
                .join(Mindmap, Mindmap.id == MindmapNodeTag.file_id)
                .where(
                    MindmapNodeTag.tag_id == model.id,
                    Mindmap.del_flag == '0',
                    Mindmap.owner_id != new_owner_id,
                )
            )).scalar_one()
            if foreign_file_count:
                raise ServiceException(
                    message=(
                        f'该标签仍被 {foreign_file_count} 个其他所有者的脑图使用，'
                        '不能收窄为私有标签'
                    )
                )

        if model.tag_key != tag.tag_key and user_id != 1:
            raise ServiceException(message='标签 Key 是稳定外部标识，仅管理员可修改')
        if model.tag_key != tag.tag_key or new_owner_id != tag.owner_id:
            is_unique = await MindmapTagDao.check_key_unique(
                db, new_owner_id, model.tag_key, exclude_id=model.id,
            )
            if not is_unique:
                raise ServiceException(message=f'标签key "{model.tag_key}" 已存在')

        try:
            affected_file_ids = list((await db.execute(
                select(distinct(MindmapNodeTag.file_id)).where(MindmapNodeTag.tag_id == model.id)
            )).scalars())
            own_style = dict(model.style or {})
            new_revision = (tag.definition_revision or 1) + 1
            new_status = model.status if model.status is not None else tag.status
            definition = {
                'tagId': model.id,
                'uuid': tag.uuid,
                'tagKey': model.tag_key,
                'text': model.name,
                'style': own_style,
                'status': new_status,
            }
            await MindmapTagDao.update_tag(db, model.id, {
                'tag_key': model.tag_key,
                'name': model.name,
                'category_id': model.category_id,
                'owner_id': new_owner_id,
                'style': own_style or None,
                'description': model.description,
                'status': new_status,
                'definition_revision': new_revision,
                'updated_time': datetime.now(),
                'update_by': str(user_id),
            })
            await db.commit()
        except Exception as e:
            await db.rollback()
            raise e
        await cls._broadcast_definition(
            affected_file_ids,
            tag_id=model.id,
            revision=new_revision,
            definition=definition,
            event_type='tag_definition_changed',
            changed_fields=['name', 'style', 'status'],
        )
        return CrudResponseModel(is_success=True, message='标签更新成功')

    @classmethod
    async def disable_tag(cls, db: AsyncSession, tag_id: int, user_id: int) -> CrudResponseModel:
        """停用标签：保留既有绑定和渲染，但不再出现在新增选择器。"""
        tag = await MindmapTagDao.get_tag_by_id(db, tag_id)
        if not tag:
            raise ServiceException(message='标签不存在')
        _check_write_permission(tag.owner_id, user_id, '标签')
        if tag.status == TAG_STATUS_ARCHIVED:
            raise ServiceException(message='已归档标签不能停用')
        if tag.status == TAG_STATUS_DISABLED:
            return CrudResponseModel(is_success=True, message='标签已处于停用状态')

        affected_file_ids = await cls._affected_file_ids(db, tag_id)
        resolved_style = dict(tag.style or {})
        revision = (tag.definition_revision or 1) + 1
        definition = {
            'tagId': tag.id,
            'uuid': tag.uuid,
            'tagKey': tag.tag_key,
            'text': tag.name,
            'style': resolved_style,
            'status': TAG_STATUS_DISABLED,
        }
        try:
            await MindmapTagDao.update_tag(db, tag_id, {
                'status': 1,
                'definition_revision': revision,
                'updated_time': datetime.now(),
                'update_by': str(user_id),
            })
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        await cls._broadcast_definition(
            affected_file_ids,
            tag_id=tag_id,
            revision=revision,
            definition=definition,
            event_type='tag_definition_changed',
            changed_fields=['status'],
        )
        return CrudResponseModel(
            is_success=True,
            message='标签已停用，既有节点仍保留该标签',
            result={'tagId': tag_id, 'definitionRevision': revision, 'affectedFileCount': len(affected_file_ids)},
        )

    @classmethod
    @observe_mindmap_operation('tag_replace', work_units_getter=_tag_replace_metric_units)
    async def replace_tag(
        cls, db: AsyncSession, source_tag_id: int, target_tag_id: int, user_id: int,
    ) -> CrudResponseModel:
        """把所有源标签绑定原子替换为目标标签，并消除同节点重复绑定。"""
        if source_tag_id == target_tag_id:
            raise ServiceException(message='源标签和目标标签不能相同')
        source = await MindmapTagDao.get_tag_by_id(db, source_tag_id)
        target = await MindmapTagDao.get_tag_by_id(db, target_tag_id)
        if not source or not target:
            raise ServiceException(message='源标签或目标标签不存在')
        _check_write_permission(source.owner_id, user_id, '源标签')
        if source.owner_id == 0 and target.owner_id != 0:
            raise ServiceException(message='全局标签只能替换为全局标签')
        if source.owner_id != 0 and target.owner_id not in (0, source.owner_id):
            raise ServiceException(message='目标标签必须与源标签同属一个私有范围，或使用全局标签')
        if target.status != TAG_STATUS_ACTIVE:
            raise ServiceException(message='只能替换为启用中的标签')

        affected_file_ids = sorted(await cls._affected_file_ids(db, source_tag_id))
        await cls._check_files_edit_access(db, affected_file_ids, user_id)

        duplicate_query = cls._replacement_duplicate_query(source_tag_id, target_tag_id)

        binding_count = (await db.execute(
            select(func.count(MindmapNodeTag.id)).where(MindmapNodeTag.tag_id == source_tag_id)
        )).scalar_one()
        duplicate_count = (await db.execute(
            select(func.count()).select_from(duplicate_query.subquery())
        )).scalar_one()
        duplicate_ids = duplicate_query.subquery()
        target_definition_revision = target.definition_revision
        target_definition = {
            'tagId': target.id,
            'uuid': target.uuid,
            'tagKey': target.tag_key,
            'text': target.name,
            'style': dict(target.style or {}),
            'status': target.status,
        }
        source_revision = (source.definition_revision or 1) + 1
        try:
            await db.execute(
                delete(MindmapNodeTag).where(MindmapNodeTag.id.in_(select(duplicate_ids.c.id)))
            )
            await db.execute(
                update(MindmapNodeTag)
                .where(MindmapNodeTag.tag_id == source_tag_id)
                .values(tag_id=target_tag_id)
            )
            await MindmapTagDao.update_tag(db, source_tag_id, {
                'status': 2,
                'definition_revision': source_revision,
                'updated_time': datetime.now(),
                'update_by': str(user_id),
            })
            revisions = await cls._advance_file_revisions(
                db, affected_file_ids, user_id,
                operation={
                    'type': 'tag.replace',
                    'payload': {'sourceTagId': source_tag_id, 'targetTagId': target_tag_id},
                },
            )
            await cls._refresh_usage(db, {source_tag_id, target_tag_id})
            await db.commit()
        except Exception:
            await db.rollback()
            raise

        for file_id in affected_file_ids:
            await cls._safe_broadcast(file_id, {
                'type': 'tag_replaced',
                'sourceTagId': source_tag_id,
                'targetTagId': target_tag_id,
                'definitionRevision': target_definition_revision,
                'definition': target_definition,
                'contentRevision': revisions[file_id],
            }, revision=revisions[file_id], operation='标签替换')
        return CrudResponseModel(
            is_success=True,
            message='标签替换成功，源标签已归档',
            result={
                'sourceTagId': source_tag_id,
                'targetTagId': target_tag_id,
                'affectedFileCount': len(affected_file_ids),
                'replacedNodeCount': binding_count,
                'duplicateBindingCount': duplicate_count,
            },
        )

    @classmethod
    @observe_mindmap_operation('tag_archive', work_units_getter=_tag_archive_metric_units)
    async def delete_tags(
        cls, db: AsyncSession, ids_str: str, user_id: int, unbind: bool = False,
    ) -> CrudResponseModel:
        """归档标签；使用中时必须显式 unbind，禁止依赖缓存计数误删。"""
        id_list = cls._parse_tag_ids(ids_str)

        tags = list((await db.execute(
            select(MindmapTag)
            .where(MindmapTag.id.in_(id_list))
            .order_by(MindmapTag.id.asc())
            .with_for_update()
        )).scalars())
        if len(tags) != len(id_list):
            raise ServiceException(message=f'有 {len(id_list) - len(tags)} 个标签不存在或已删除')
        for tag in tags:
            _check_write_permission(tag.owner_id, user_id, '标签')

        usage_rows = (await db.execute(
            select(MindmapNodeTag.tag_id, func.count(MindmapNodeTag.id))
            .where(MindmapNodeTag.tag_id.in_(id_list))
            .group_by(MindmapNodeTag.tag_id)
        )).all()
        usage_counts = dict(usage_rows)
        if not unbind:
            for tag in tags:
                if actual_count := usage_counts.get(tag.id, 0):
                    raise ServiceException(
                        message=(
                            f'标签“{tag.name}”仍被 {actual_count} 个节点使用，'
                            '请先停用、替换或使用 unbind=true 解除绑定'
                        )
                    )

        affected_file_ids = set((await db.execute(
            select(distinct(MindmapNodeTag.file_id)).where(MindmapNodeTag.tag_id.in_(id_list))
        )).scalars())

        if unbind:
            await cls._check_files_edit_access(db, sorted(affected_file_ids), user_id)

        try:
            if unbind:
                await db.execute(delete(MindmapNodeTag).where(MindmapNodeTag.tag_id.in_(id_list)))
            tag_updates = {
                'status': TAG_STATUS_ARCHIVED,
                'definition_revision': MindmapTag.definition_revision + 1,
                'updated_time': datetime.now(),
                'update_by': str(user_id),
            }
            if unbind:
                tag_updates.update({'usage_node_count': 0, 'usage_file_count': 0})
            await db.execute(
                update(MindmapTag)
                .where(MindmapTag.id.in_([tag.id for tag in tags]))
                .values(**tag_updates)
            )
            revisions = await cls._advance_file_revisions(
                db, sorted(affected_file_ids), user_id,
                operation={'type': 'tag.unbind', 'payload': {'tagIds': id_list}},
            ) if unbind else {}
            await db.commit()
            for file_id in affected_file_ids:
                await cls._safe_broadcast(file_id, {
                    'type': 'tag_unbound' if unbind else 'tag_definition_changed',
                    'tagIds': id_list,
                    'contentRevision': revisions.get(file_id),
                }, revision=revisions.get(file_id), operation='标签解绑')
            return CrudResponseModel(
                is_success=True,
                message='标签已解除绑定并归档' if unbind else '标签已归档',
                result={'tagIds': id_list, 'unbind': unbind, 'affectedFileCount': len(affected_file_ids)},
            )
        except Exception:
            await db.rollback()
            raise

    @classmethod
    async def get_suggestions(
        cls, db: AsyncSession, user_id: int, keyword: str | None = None,
    ) -> list[dict]:
        """获取标签建议（编辑器自动补全）"""
        tags = await MindmapTagDao.get_suggestions(db, user_id, keyword)
        return [CamelCaseUtil.transform_result(tag) for tag in tags]

    @staticmethod
    async def _affected_file_ids(db: AsyncSession, tag_id: int) -> list[int]:
        return list((await db.execute(
            select(distinct(MindmapNodeTag.file_id)).where(MindmapNodeTag.tag_id == tag_id)
        )).scalars())

    @staticmethod
    async def _refresh_usage(db: AsyncSession, tag_ids: set[int]) -> None:
        if not tag_ids:
            return
        rows = (await db.execute(
            select(
                MindmapNodeTag.tag_id,
                func.count(MindmapNodeTag.id),
                func.count(distinct(MindmapNodeTag.file_id)),
            )
            .where(MindmapNodeTag.tag_id.in_(tag_ids))
            .group_by(MindmapNodeTag.tag_id)
        )).all()
        counts = {tag_id: (node_count, file_count) for tag_id, node_count, file_count in rows}
        for tag_id in tag_ids:
            node_count, file_count = counts.get(tag_id, (0, 0))
            await MindmapTagDao.update_tag(db, tag_id, {
                'usage_node_count': node_count,
                'usage_file_count': file_count,
            })

    @staticmethod
    def _parse_tag_ids(ids_str: str) -> list[int]:
        try:
            tag_ids = list(dict.fromkeys(
                int(value.strip()) for value in ids_str.split(',') if value.strip()
            ))
        except ValueError as exc:
            raise ServiceException(message='标签ID必须是逗号分隔的正整数') from exc
        if not tag_ids:
            raise ServiceException(message='传入标签ID为空')
        if any(tag_id <= 0 for tag_id in tag_ids):
            raise ServiceException(message='标签ID必须是逗号分隔的正整数')
        if any(tag_id > MAX_MINDMAP_TAG_ID for tag_id in tag_ids):
            raise ServiceException(message='标签ID超出数据库整数范围')
        if len(tag_ids) > MAX_MINDMAP_TAG_BATCH_SIZE:
            raise ServiceException(message=f'单次最多处理 {MAX_MINDMAP_TAG_BATCH_SIZE} 个标签')
        return tag_ids

    @staticmethod
    def _replacement_duplicate_query(
        source_tag_id: int, target_tag_id: int,
    ) -> Select:
        """返回同一节点已存在目标标签时应删除的源标签绑定。"""
        target_nodes = select(MindmapNodeTag.node_id).where(
            MindmapNodeTag.tag_id == target_tag_id,
        )
        return select(MindmapNodeTag.id).where(
            MindmapNodeTag.tag_id == source_tag_id,
            MindmapNodeTag.node_id.in_(target_nodes),
        )

    @staticmethod
    async def _check_files_edit_access(
        db: AsyncSession, file_ids: list[int], user_id: int,
    ) -> None:
        """一次查询校验批量标签治理涉及的全部文件均处于可编辑状态。"""
        if not file_ids:
            return
        query = select(Mindmap.id).where(
            Mindmap.id.in_(file_ids),
            Mindmap.del_flag == '0',
            Mindmap.status == 0,
        )
        if user_id != 1:
            query = query.outerjoin(
                MindmapCollaborator,
                and_(
                    MindmapCollaborator.mindmap_id == Mindmap.id,
                    MindmapCollaborator.user_id == user_id,
                ),
            ).where(or_(
                Mindmap.owner_id == user_id,
                MindmapCollaborator.permission >= 1,
            ))
        allowed_ids = set((await db.execute(query)).scalars())
        denied_count = len(set(file_ids) - allowed_ids)
        if denied_count:
            raise ServiceException(
                message=f'有 {denied_count} 个受影响脑图无编辑权限，无法执行批量标签治理'
            )

    @staticmethod
    async def _advance_file_revisions(
        db: AsyncSession, file_ids: list[int], user_id: int, operation: dict,
    ) -> dict[int, int]:
        """标签绑定批处理也是文件内容变更，必须推进 revision 并废弃旧 Yjs 缓存。"""
        revisions: dict[int, int] = {}
        for file_id in sorted(file_ids):
            mindmap = (await db.execute(
                select(Mindmap).where(Mindmap.id == file_id).with_for_update()
            )).scalars().first()
            if not mindmap:
                continue
            base_revision = mindmap.content_revision
            revision = base_revision + 1
            mutation_id = f'tag-governance-{uuid_lib.uuid4()}'
            await db.execute(
                update(Mindmap).where(Mindmap.id == file_id).values(
                    content_revision=revision,
                    update_by=str(user_id),
                    update_time=datetime.now(),
                )
            )
            await db.execute(delete(MindmapWsState).where(MindmapWsState.mindmap_id == file_id))
            db.add(MindmapChangeLog(
                file_id=file_id,
                base_revision=base_revision,
                revision=revision,
                client_mutation_id=mutation_id,
                operations=[operation],
                result_data={
                    'contentRevision': revision,
                    'clientMutationId': mutation_id,
                    'changedNodes': [],
                },
                created_by=str(user_id),
                created_time=datetime.now(),
            ))
            revisions[file_id] = revision
        return revisions

    @staticmethod
    async def _broadcast_definition(
        file_ids: list[int], *, tag_id: int, revision: int, definition: dict,
        event_type: str, changed_fields: list[str],
    ) -> None:
        event = {
            'type': event_type,
            'tagId': tag_id,
            'definitionRevision': revision,
            'changedFields': changed_fields,
            'definition': definition,
        }
        for file_id in file_ids:
            await MindmapTagService._safe_broadcast(
                file_id, event, operation='标签定义变更',
            )

    @staticmethod
    async def _safe_broadcast(
        file_id: int, event: dict, *, revision: int | None = None, operation: str,
    ) -> None:
        """持久化提交后的实时通知只能降级，不能反向改变接口结果。"""
        try:
            if revision is not None:
                room_manager.set_content_revision(file_id, revision)
            await room_manager.broadcast(file_id, event)
        except Exception as exc:
            record_mindmap_event('broadcast_failure')
            logger.warning(f'广播{operation}失败: file_id={file_id}, error={exc}')
