"""脑图文件夹服务层"""
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import CrudResponseModel
from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_folder_dao import MindmapFolderDao
from module_mindmap.entity.vo.mindmap_folder_vo import (
    MindmapFolderModel,
    MindmapFolderSortModel,
    MindmapMoveModel,
)


class MindmapFolderService:
    """文件夹服务层"""

    @classmethod
    async def get_folder_tree(cls, db: AsyncSession, user_id: int) -> list[dict]:
        """获取文件夹树"""
        folders = await MindmapFolderDao.get_folder_tree(db, user_id)
        # 只返回树节点需要的字段，避免暴露内部审计字段
        folder_list = [
            {'id': f.id, 'name': f.name, 'parentId': f.parent_id, 'sortOrder': f.sort_order}
            for f in folders
        ]
        return cls._build_tree(folder_list)

    @classmethod
    def _build_tree(cls, folder_list: list[dict], parent_id: int = 0) -> list[dict]:
        """将平铺列表组装为树结构"""
        tree = []
        for folder in folder_list:
            if folder.get('parentId', 0) == parent_id:
                children = cls._build_tree(folder_list, folder['id'])
                if children:
                    folder['children'] = children
                tree.append(folder)
        return tree

    @classmethod
    async def add_folder(
        cls, db: AsyncSession, model: MindmapFolderModel, user_id: int, user_name: str,
    ) -> CrudResponseModel:
        """新建文件夹"""
        if not model.name:
            raise ServiceException(message='文件夹名称不能为空')

        # 校验父文件夹归属
        if model.parent_id and model.parent_id > 0:
            parent = await MindmapFolderDao.get_folder_by_id(db, model.parent_id)
            if not parent or parent.owner_id != user_id:
                raise ServiceException(message='父文件夹不存在或无权限')

        # 检查同级名称唯一
        is_unique = await MindmapFolderDao.check_name_unique(
            db, model.name, model.parent_id or 0, user_id,
        )
        if not is_unique:
            raise ServiceException(message='同一目录下已存在同名文件夹')

        try:
            folder = await MindmapFolderDao.add_folder(db, {
                'name': model.name,
                'parent_id': model.parent_id or 0,
                'owner_id': user_id,
                'sort_order': model.sort_order or 0,
                'create_by': user_name,
                'create_time': datetime.now(),
                'update_by': user_name,
                'update_time': datetime.now(),
            })
            folder_id = folder.id  # commit 前捕获 ID，避免 session 过期后触发 MissingGreenlet
            await db.commit()
            return CrudResponseModel(is_success=True, message='文件夹创建成功', result={'id': folder_id})
        except Exception as e:
            await db.rollback()
            raise e

    @classmethod
    async def update_folder(
        cls, db: AsyncSession, model: MindmapFolderModel, user_id: int, user_name: str,
    ) -> CrudResponseModel:
        """重命名/移动文件夹"""
        folder = await MindmapFolderDao.get_folder_by_id(db, model.id)
        if not folder:
            raise ServiceException(message='文件夹不存在')
        if folder.owner_id != user_id:
            raise ServiceException(message='无权限修改该文件夹')

        # 检查同级名称唯一
        parent_id = model.parent_id if model.parent_id is not None else folder.parent_id
        if model.name and model.name != folder.name:
            is_unique = await MindmapFolderDao.check_name_unique(
                db, model.name, parent_id, user_id, exclude_id=model.id,
            )
            if not is_unique:
                raise ServiceException(message='同一目录下已存在同名文件夹')

        # 防止将文件夹移入自身或子文件夹
        if model.parent_id is not None and model.parent_id != folder.parent_id:
            if model.parent_id == model.id:
                raise ServiceException(message='不能将文件夹移入自身')
            # 校验目标父文件夹归属
            if model.parent_id > 0:
                target_parent = await MindmapFolderDao.get_folder_by_id(db, model.parent_id)
                if not target_parent or target_parent.owner_id != user_id:
                    raise ServiceException(message='目标父文件夹不存在或无权限')
            await cls._check_not_descendant(db, model.id, model.parent_id, user_id)

        try:
            update_data = {}
            if model.name is not None:
                update_data['name'] = model.name
            if model.parent_id is not None:
                update_data['parent_id'] = model.parent_id
            if model.sort_order is not None:
                update_data['sort_order'] = model.sort_order
            update_data['update_by'] = user_name
            update_data['update_time'] = datetime.now()

            await MindmapFolderDao.update_folder(db, model.id, update_data)
            await db.commit()
            return CrudResponseModel(is_success=True, message='文件夹更新成功')
        except Exception as e:
            await db.rollback()
            raise e

    @classmethod
    async def _check_not_descendant(cls, db: AsyncSession, folder_id: int, target_id: int, user_id: int, max_depth: int = 50) -> None:
        """检查 target_id 不是 folder_id 的子孙文件夹"""
        if max_depth <= 0:
            raise ServiceException(message='文件夹嵌套层级过深')
        children = await MindmapFolderDao.get_child_folder_ids(db, folder_id, user_id)
        if target_id in children:
            raise ServiceException(message='不能将文件夹移入其子文件夹')
        for child_id in children:
            await cls._check_not_descendant(db, child_id, target_id, user_id, max_depth - 1)

    @classmethod
    async def delete_folder(
        cls, db: AsyncSession, folder_id: int, user_id: int,
    ) -> CrudResponseModel:
        """删除文件夹（内容移至根目录）"""
        folder = await MindmapFolderDao.get_folder_by_id(db, folder_id)
        if not folder:
            raise ServiceException(message='文件夹不存在')
        if folder.owner_id != user_id:
            raise ServiceException(message='无权限删除该文件夹')

        try:
            # 递归收集所有子孙文件夹ID
            all_ids = await cls._collect_descendant_ids(db, folder_id, user_id)
            all_ids.append(folder_id)

            # 将所有相关文件夹下的脑图移到根目录
            for fid in all_ids:
                await MindmapFolderDao.move_mindmaps_out_of_folder(db, fid)

            # 软删除所有文件夹
            await MindmapFolderDao.batch_soft_delete_folders(db, all_ids)
            await db.commit()
            return CrudResponseModel(is_success=True, message='文件夹删除成功')
        except Exception as e:
            await db.rollback()
            raise e

    @classmethod
    async def _collect_descendant_ids(cls, db: AsyncSession, parent_id: int, user_id: int, max_depth: int = 50) -> list[int]:
        """递归收集所有子孙文件夹ID"""
        if max_depth <= 0:
            return []
        children = await MindmapFolderDao.get_child_folder_ids(db, parent_id, user_id)
        result = list(children)
        for child_id in children:
            result.extend(await cls._collect_descendant_ids(db, child_id, user_id, max_depth - 1))
        return result

    @classmethod
    async def sort_folders(
        cls, db: AsyncSession, model: MindmapFolderSortModel, user_id: int,
    ) -> CrudResponseModel:
        """批量更新文件夹排序"""
        try:
            for item in model.items:
                # 验证文件夹归属
                folder = await MindmapFolderDao.get_folder_by_id(db, item.id)
                if not folder or folder.owner_id != user_id:
                    raise ServiceException(message=f'文件夹 {item.id} 不存在或无权限')
                # 验证目标父文件夹归属
                if item.parent_id is not None and item.parent_id > 0:
                    target_parent = await MindmapFolderDao.get_folder_by_id(db, item.parent_id)
                    if not target_parent or target_parent.owner_id != user_id:
                        raise ServiceException(message=f'目标父文件夹 {item.parent_id} 不存在或无权限')
                await MindmapFolderDao.update_sort_order(db, item.id, item.sort_order, item.parent_id)
            await db.commit()
            return CrudResponseModel(is_success=True, message='排序更新成功')
        except Exception as e:
            await db.rollback()
            raise e

    @classmethod
    async def move_mindmaps(
        cls, db: AsyncSession, model: MindmapMoveModel, user_id: int,
    ) -> CrudResponseModel:
        """移动脑图到指定文件夹"""
        # 验证目标文件夹归属
        if model.folder_id is not None:
            folder = await MindmapFolderDao.get_folder_by_id(db, model.folder_id)
            if not folder or folder.owner_id != user_id:
                raise ServiceException(message='目标文件夹不存在或无权限')

        try:
            await MindmapFolderDao.move_mindmaps_to_folder(db, model.mindmap_ids, model.folder_id, user_id)
            await db.commit()
            return CrudResponseModel(is_success=True, message='移动成功')
        except Exception as e:
            await db.rollback()
            raise e
