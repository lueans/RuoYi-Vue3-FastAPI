from datetime import datetime
from typing import Any

from sqlalchemy import case, delete, exists, literal, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import PageModel
from module_admin.entity.do.user_do import SysUser
from module_mindmap.entity.do.mindmap_collaborator_do import MindmapCollaborator
from module_mindmap.entity.do.mindmap_content_do import MindmapMigrationRecord, MindmapNodeTag
from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.entity.vo.mindmap_vo import MindmapPageQueryModel
from utils.page_util import PageUtil


class MindmapDao:
    """思维导图模块数据库操作层"""

    @classmethod
    async def get_mindmap_by_id(cls, db: AsyncSession, mindmap_id: int) -> Mindmap | None:
        """根据ID获取思维导图详细信息"""
        result = (
            await db.execute(
                select(Mindmap).where(
                    Mindmap.id == mindmap_id,
                    Mindmap.del_flag == '0',
                )
            )
        ).scalars().first()
        return result

    @classmethod
    async def get_mindmap_for_update(cls, db: AsyncSession, mindmap_id: int) -> Mindmap | None:
        """锁定单个脑图文件，串行分配 content_revision。"""
        return (await db.execute(
            select(Mindmap)
            .where(Mindmap.id == mindmap_id, Mindmap.del_flag == '0')
            .with_for_update()
        )).scalars().first()

    @classmethod
    async def get_migration_status(cls, db: AsyncSession, mindmap_id: int) -> str | None:
        return (await db.execute(
            select(MindmapMigrationRecord.status).where(MindmapMigrationRecord.file_id == mindmap_id)
        )).scalar_one_or_none()

    @classmethod
    async def get_mindmap_list(
        cls, db: AsyncSession, query_object: MindmapPageQueryModel, is_page: bool = False
    ) -> PageModel | list[dict[str, Any]]:
        """获取思维导图列表"""
        is_shared = query_object.access_scope == 'shared'
        is_trash = query_object.access_scope == 'trash'
        permission_column = (
            MindmapCollaborator.permission if is_shared else literal(1)
        )
        columns = (
            Mindmap.id,
            Mindmap.name,
            Mindmap.description,
            Mindmap.owner_id,
            Mindmap.layout,
            Mindmap.cover_image,
            Mindmap.folder_id,
            Mindmap.is_template,
            Mindmap.version_count,
            Mindmap.node_count,
            Mindmap.content_revision,
            Mindmap.schema_version,
            Mindmap.status,
            Mindmap.create_time,
            Mindmap.update_time,
            SysUser.nick_name.label('owner_name'),
            literal('shared' if is_shared else ('trash' if is_trash else 'owned')).label('access_type'),
            permission_column.label('effective_permission'),
            literal(not is_shared).label('is_owner'),
            (
                literal(False)
                if is_trash
                else case(
                    (MindmapMigrationRecord.status == 'failed', False),
                    (Mindmap.status == 1, False),
                    (permission_column >= 1, True),
                    else_=False,
                )
            ).label('can_edit'),
            case(
                (MindmapMigrationRecord.status == 'failed', 'migration_failed'),
                else_='ready',
            ).label('content_state'),
        )
        keyword_pattern = cls._literal_contains_pattern(query_object.keyword)
        legacy_name_pattern = cls._literal_contains_pattern(query_object.name)
        file_keyword_condition = (
            or_(
                Mindmap.name.ilike(keyword_pattern, escape='\\'),
                Mindmap.description.ilike(keyword_pattern, escape='\\'),
            )
            if keyword_pattern
            else (
                Mindmap.name.like(legacy_name_pattern, escape='\\')
                if legacy_name_pattern
                else True
            )
        )
        query = select(*columns)
        if is_shared:
            query = query.join(
                MindmapCollaborator,
                MindmapCollaborator.mindmap_id == Mindmap.id,
            )
        query = (
            query.outerjoin(SysUser, SysUser.user_id == Mindmap.owner_id)
            .outerjoin(MindmapMigrationRecord, MindmapMigrationRecord.file_id == Mindmap.id)
            .where(
                MindmapCollaborator.user_id == query_object.owner_id
                if is_shared else Mindmap.owner_id == query_object.owner_id,
                Mindmap.del_flag == ('2' if is_trash else '0'),
                file_keyword_condition,
                Mindmap.status == query_object.status if query_object.status is not None else True,
                Mindmap.is_template == query_object.is_template if query_object.is_template is not None else True,
                Mindmap.folder_id == query_object.folder_id if query_object.folder_id is not None else True,
                Mindmap.create_time >= query_object.begin_time if query_object.begin_time else True,
                Mindmap.create_time <= query_object.end_time if query_object.end_time else True,
                exists(
                    select(MindmapNodeTag.id).where(
                        MindmapNodeTag.file_id == Mindmap.id,
                        MindmapNodeTag.tag_id == query_object.tag_id,
                    )
                ) if query_object.tag_id is not None else True,
            )
            .distinct()
        )

        # Sorting — 白名单防止任意属性访问
        _allowed_sort_fields = {'name', 'create_time', 'update_time', 'version_count', 'status'}
        sort_column = getattr(
            Mindmap, query_object.sort_field, Mindmap.update_time
        ) if query_object.sort_field in _allowed_sort_fields else Mindmap.update_time
        if query_object.sort_order == 'desc':
            query = query.order_by(sort_column.desc(), Mindmap.id.desc())
        else:
            query = query.order_by(sort_column.asc(), Mindmap.id.asc())

        if is_page:
            mindmap_list: PageModel = await PageUtil.paginate(
                db, query, query_object.page_num, query_object.page_size, True
            )
            return mindmap_list
        result = (await db.execute(query)).all()
        return [dict(row._mapping) for row in result]

    @staticmethod
    def _literal_contains_pattern(value: str | None) -> str | None:
        if not value:
            return None
        escaped = value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        return f'%{escaped}%'

    @classmethod
    async def add_mindmap_dao(cls, db: AsyncSession, data: dict) -> Mindmap:
        """新增思维导图"""
        db_mindmap = Mindmap(**data)
        db.add(db_mindmap)
        await db.flush()
        return db_mindmap

    @classmethod
    async def edit_mindmap_dao(cls, db: AsyncSession, mindmap: dict) -> None:
        """编辑思维导图"""
        mindmap_id = mindmap.pop('id', None)
        if mindmap_id is None:
            raise ValueError('edit_mindmap_dao requires id in data dict')
        await db.execute(update(Mindmap).where(Mindmap.id == mindmap_id).values(**mindmap))

    @classmethod
    async def update_mindmap_status(
        cls,
        db: AsyncSession,
        mindmap_id: int,
        owner_id: int,
        status: int,
        update_by: str,
    ) -> int:
        """仅更新所有者的有效非模板脑图状态。"""
        result = await db.execute(
            update(Mindmap)
            .where(
                Mindmap.id == mindmap_id,
                Mindmap.owner_id == owner_id,
                Mindmap.del_flag == '0',
                Mindmap.is_template == 0,
            )
            .values(status=status, update_by=update_by, update_time=datetime.now())
        )
        return int(result.rowcount or 0)

    @classmethod
    async def update_mindmaps_status(
        cls,
        db: AsyncSession,
        mindmap_ids: list[int],
        owner_id: int,
        status: int,
        update_by: str,
    ) -> int:
        """批量更新所有者的有效非模板脑图状态。"""
        if not mindmap_ids:
            return 0
        result = await db.execute(
            update(Mindmap)
            .where(
                Mindmap.id.in_(mindmap_ids),
                Mindmap.owner_id == owner_id,
                Mindmap.del_flag == '0',
                Mindmap.is_template == 0,
            )
            .values(status=status, update_by=update_by, update_time=datetime.now())
        )
        return int(result.rowcount or 0)

    @classmethod
    async def update_content_dao(cls, db: AsyncSession, mindmap_id: int, data: dict) -> None:
        """更新思维导图内容（node_tree, view_data, layout, theme）"""
        await db.execute(
            update(Mindmap)
            .where(Mindmap.id == mindmap_id)
            .values(**data)
        )

    @classmethod
    async def delete_mindmap_dao(cls, db: AsyncSession, mindmap_id: int) -> None:
        """软删除思维导图"""
        await db.execute(
            update(Mindmap)
            .where(Mindmap.id == mindmap_id)
            .values(del_flag='2')
        )

    @classmethod
    async def batch_delete_mindmap_dao(cls, db: AsyncSession, mindmap_ids: list[int]) -> None:
        """批量软删除思维导图"""
        await db.execute(
            update(Mindmap)
            .where(Mindmap.id.in_(mindmap_ids))
            .values(del_flag='2')
        )

    @classmethod
    async def move_to_trash(
        cls, db: AsyncSession, mindmap_ids: list[int], owner_id: int, update_by: str,
    ) -> int:
        """将所有者的有效文件移入回收站，保留全部关联数据。"""
        result = await db.execute(
            update(Mindmap)
            .where(
                Mindmap.id.in_(mindmap_ids),
                Mindmap.owner_id == owner_id,
                Mindmap.del_flag == '0',
                Mindmap.is_template == 0,
            )
            .values(del_flag='2', update_by=update_by, update_time=datetime.now())
        )
        return int(result.rowcount or 0)

    @classmethod
    async def restore_from_trash(
        cls,
        db: AsyncSession,
        mindmap_ids: list[int],
        owner_id: int,
        update_by: str,
        root_folder_ids: set[int],
    ) -> int:
        """恢复回收站文件；原目录失效的文件回到根目录。"""
        now = datetime.now()
        root_ids = [mindmap_id for mindmap_id in mindmap_ids if mindmap_id in root_folder_ids]
        retained_folder_ids = [mindmap_id for mindmap_id in mindmap_ids if mindmap_id not in root_folder_ids]
        restored = 0
        if root_ids:
            result = await db.execute(
                update(Mindmap)
                .where(
                    Mindmap.id.in_(root_ids),
                    Mindmap.owner_id == owner_id,
                    Mindmap.del_flag == '2',
                    Mindmap.is_template == 0,
                )
                .values(
                    del_flag='0',
                    folder_id=None,
                    update_by=update_by,
                    update_time=now,
                )
            )
            restored += int(result.rowcount or 0)
        if retained_folder_ids:
            result = await db.execute(
                update(Mindmap)
                .where(
                    Mindmap.id.in_(retained_folder_ids),
                    Mindmap.owner_id == owner_id,
                    Mindmap.del_flag == '2',
                    Mindmap.is_template == 0,
                )
                .values(del_flag='0', update_by=update_by, update_time=now)
            )
            restored += int(result.rowcount or 0)
        return restored

    @classmethod
    async def permanently_delete(cls, db: AsyncSession, mindmap_ids: list[int], owner_id: int) -> int:
        """物理删除所有者回收站中的文件主记录。"""
        result = await db.execute(
            delete(Mindmap).where(
                Mindmap.id.in_(mindmap_ids),
                Mindmap.owner_id == owner_id,
                Mindmap.del_flag == '2',
                Mindmap.is_template == 0,
            )
        )
        return int(result.rowcount or 0)

    @classmethod
    async def check_name_unique(
        cls, db: AsyncSession, name: str, owner_id: int, exclude_id: int | None = None
    ) -> bool:
        """检查名称是否唯一（同一用户下）"""
        conditions = [
            Mindmap.name == name,
            Mindmap.owner_id == owner_id,
            Mindmap.del_flag == '0',
        ]
        if exclude_id:
            conditions.append(Mindmap.id != exclude_id)

        result = (await db.execute(select(Mindmap.id).where(*conditions))).first()
        return result is None

    @classmethod
    async def increment_version_count(cls, db: AsyncSession, mindmap_id: int) -> None:
        """增加版本计数"""
        await db.execute(
            update(Mindmap)
            .where(Mindmap.id == mindmap_id)
            .values(version_count=Mindmap.version_count + 1)
        )

    @classmethod
    async def decrement_version_count(cls, db: AsyncSession, mindmap_id: int) -> None:
        """删除正式版本后同步列表计数，并保留当前状态这一基线版本。"""
        await db.execute(
            update(Mindmap)
            .where(Mindmap.id == mindmap_id)
            .values(version_count=case(
                (Mindmap.version_count > 1, Mindmap.version_count - 1),
                else_=1,
            ))
        )
