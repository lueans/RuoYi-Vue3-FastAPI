"""脑图文件夹 DAO"""
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.entity.do.mindmap_folder_do import MindmapFolder


class MindmapFolderDao:
    """文件夹数据库操作层"""

    @classmethod
    async def get_folder_tree(
        cls, db: AsyncSession, owner_id: int, *, for_update: bool = False,
    ) -> list[MindmapFolder]:
        """获取用户所有文件夹（平铺，前端组装树）"""
        query = (
            select(MindmapFolder)
            .where(
                MindmapFolder.owner_id == owner_id,
                MindmapFolder.del_flag == '0',
            )
            .order_by(MindmapFolder.sort_order.asc(), MindmapFolder.id.asc())
        )
        if for_update:
            query = query.with_for_update()
        result = (await db.execute(query)).scalars().all()
        return list(result)

    @classmethod
    async def get_folder_by_id(
        cls,
        db: AsyncSession,
        folder_id: int,
        owner_id: int,
        *,
        for_update: bool = False,
    ) -> MindmapFolder | None:
        query = (
            select(MindmapFolder).where(
                MindmapFolder.id == folder_id,
                MindmapFolder.owner_id == owner_id,
                MindmapFolder.del_flag == '0',
            )
        )
        if for_update:
            query = query.with_for_update()
        result = (await db.execute(query)).scalars().first()
        return result

    @classmethod
    async def add_folder(cls, db: AsyncSession, data: dict) -> MindmapFolder:
        folder = MindmapFolder(**data)
        db.add(folder)
        await db.flush()
        return folder

    @classmethod
    async def update_folder(
        cls, db: AsyncSession, folder_id: int, owner_id: int, data: dict,
    ) -> None:
        await db.execute(
            update(MindmapFolder)
            .where(
                MindmapFolder.id == folder_id,
                MindmapFolder.owner_id == owner_id,
                MindmapFolder.del_flag == '0',
            )
            .values(**data)
        )

    @classmethod
    async def batch_soft_delete_folders(
        cls, db: AsyncSession, folder_ids: list[int], owner_id: int,
    ) -> None:
        await db.execute(
            update(MindmapFolder)
            .where(
                MindmapFolder.id.in_(folder_ids),
                MindmapFolder.owner_id == owner_id,
                MindmapFolder.del_flag == '0',
            )
            .values(del_flag='2')
        )

    @classmethod
    async def get_owned_mindmap_ids(
        cls, db: AsyncSession, mindmap_ids: list[int], owner_id: int, *, for_update: bool = False,
    ) -> list[int]:
        query = select(Mindmap.id).where(
            Mindmap.id.in_(mindmap_ids),
            Mindmap.owner_id == owner_id,
            Mindmap.del_flag == '0',
            Mindmap.is_template == 0,
        )
        if for_update:
            query = query.with_for_update()
        return list((await db.execute(query)).scalars().all())

    @classmethod
    async def move_mindmaps_to_folder(
        cls, db: AsyncSession, mindmap_ids: list[int], folder_id: int | None, owner_id: int,
    ) -> int:
        """将脑图移动到指定文件夹（仅允许操作自己的脑图）"""
        result = await db.execute(
            update(Mindmap)
            .where(
                Mindmap.id.in_(mindmap_ids),
                Mindmap.owner_id == owner_id,
                Mindmap.del_flag == '0',
                Mindmap.is_template == 0,
            )
            .values(folder_id=folder_id)
        )
        return int(result.rowcount or 0)

    @classmethod
    async def move_mindmaps_out_of_folders(
        cls, db: AsyncSession, folder_ids: list[int], owner_id: int,
    ) -> int:
        """将目录子树下的有效脑图一次性移到根目录。"""
        result = await db.execute(
            update(Mindmap)
            .where(
                Mindmap.folder_id.in_(folder_ids),
                Mindmap.owner_id == owner_id,
                Mindmap.del_flag == '0',
                Mindmap.is_template == 0,
            )
            .values(folder_id=None)
        )
        return int(result.rowcount or 0)

    @classmethod
    async def count_mindmaps_in_folders(
        cls, db: AsyncSession, folder_ids: list[int], owner_id: int,
    ) -> int:
        if not folder_ids:
            return 0
        return int((await db.execute(
            select(func.count(Mindmap.id)).where(
                Mindmap.folder_id.in_(folder_ids),
                Mindmap.owner_id == owner_id,
                Mindmap.del_flag == '0',
                Mindmap.is_template == 0,
            )
        )).scalar_one())

    @classmethod
    async def update_sort_order(
        cls,
        db: AsyncSession,
        folder_id: int,
        owner_id: int,
        sort_order: int,
        parent_id: int | None = None,
    ) -> None:
        """更新文件夹排序和父级"""
        values = {'sort_order': sort_order}
        if parent_id is not None:
            values['parent_id'] = parent_id
        await db.execute(
            update(MindmapFolder)
            .where(
                MindmapFolder.id == folder_id,
                MindmapFolder.owner_id == owner_id,
                MindmapFolder.del_flag == '0',
            )
            .values(**values)
        )
