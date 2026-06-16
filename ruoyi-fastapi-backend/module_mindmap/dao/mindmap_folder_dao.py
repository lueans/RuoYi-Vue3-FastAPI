"""脑图文件夹 DAO"""
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.entity.do.mindmap_folder_do import MindmapFolder


class MindmapFolderDao:
    """文件夹数据库操作层"""

    @classmethod
    async def get_folder_tree(cls, db: AsyncSession, owner_id: int) -> list[MindmapFolder]:
        """获取用户所有文件夹（平铺，前端组装树）"""
        result = (await db.execute(
            select(MindmapFolder)
            .where(
                MindmapFolder.owner_id == owner_id,
                MindmapFolder.del_flag == '0',
            )
            .order_by(MindmapFolder.sort_order.asc(), MindmapFolder.id.asc())
        )).scalars().all()
        return list(result)

    @classmethod
    async def get_folder_by_id(cls, db: AsyncSession, folder_id: int) -> MindmapFolder | None:
        result = (await db.execute(
            select(MindmapFolder).where(
                MindmapFolder.id == folder_id,
                MindmapFolder.del_flag == '0',
            )
        )).scalars().first()
        return result

    @classmethod
    async def add_folder(cls, db: AsyncSession, data: dict) -> MindmapFolder:
        folder = MindmapFolder(**data)
        db.add(folder)
        await db.flush()
        return folder

    @classmethod
    async def update_folder(cls, db: AsyncSession, folder_id: int, data: dict) -> None:
        await db.execute(
            update(MindmapFolder)
            .where(MindmapFolder.id == folder_id)
            .values(**data)
        )

    @classmethod
    async def batch_soft_delete_folders(cls, db: AsyncSession, folder_ids: list[int]) -> None:
        await db.execute(
            update(MindmapFolder)
            .where(MindmapFolder.id.in_(folder_ids))
            .values(del_flag='2')
        )

    @classmethod
    async def get_child_folder_ids(cls, db: AsyncSession, parent_id: int, owner_id: int) -> list[int]:
        """获取直接子文件夹ID列表"""
        result = (await db.execute(
            select(MindmapFolder.id)
            .where(
                MindmapFolder.parent_id == parent_id,
                MindmapFolder.owner_id == owner_id,
                MindmapFolder.del_flag == '0',
            )
        )).scalars().all()
        return list(result)

    @classmethod
    async def move_mindmaps_to_folder(cls, db: AsyncSession, mindmap_ids: list[int], folder_id: int | None, owner_id: int) -> None:
        """将脑图移动到指定文件夹（仅允许操作自己的脑图）"""
        await db.execute(
            update(Mindmap)
            .where(Mindmap.id.in_(mindmap_ids), Mindmap.owner_id == owner_id)
            .values(folder_id=folder_id)
        )

    @classmethod
    async def move_mindmaps_out_of_folder(cls, db: AsyncSession, folder_id: int) -> None:
        """将文件夹下的脑图移到根目录"""
        await db.execute(
            update(Mindmap)
            .where(Mindmap.folder_id == folder_id)
            .values(folder_id=None)
        )

    @classmethod
    async def check_name_unique(
        cls, db: AsyncSession, name: str, parent_id: int, owner_id: int, exclude_id: int | None = None,
    ) -> bool:
        """检查同一父文件夹下名称是否唯一"""
        conditions = [
            MindmapFolder.name == name,
            MindmapFolder.parent_id == parent_id,
            MindmapFolder.owner_id == owner_id,
            MindmapFolder.del_flag == '0',
        ]
        if exclude_id is not None:
            conditions.append(MindmapFolder.id != exclude_id)
        result = (await db.execute(select(MindmapFolder.id).where(*conditions))).first()
        return result is None

    @classmethod
    async def update_sort_order(cls, db: AsyncSession, folder_id: int, sort_order: int, parent_id: int | None = None) -> None:
        """更新文件夹排序和父级"""
        values = {'sort_order': sort_order}
        if parent_id is not None:
            values['parent_id'] = parent_id
        await db.execute(
            update(MindmapFolder)
            .where(MindmapFolder.id == folder_id)
            .values(**values)
        )
