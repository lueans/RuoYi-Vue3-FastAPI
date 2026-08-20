"""脑图目录生命周期服务。"""

from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import CrudResponseModel
from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_folder_dao import MindmapFolderDao
from module_mindmap.entity.vo.mindmap_folder_vo import (
    MindmapFolderCreateModel,
    MindmapFolderSortModel,
    MindmapFolderUpdateModel,
    MindmapMoveModel,
)

MAX_FOLDER_DEPTH = 20


class MindmapFolderService:
    """目录树、排序和文件移动的一致性边界。"""

    @staticmethod
    def _folder_map(folders: list[Any]) -> dict[int, dict[str, Any]]:
        return {
            int(folder.id): {
                'id': int(folder.id),
                'name': folder.name,
                'parentId': int(folder.parent_id or 0),
                'sortOrder': int(folder.sort_order or 0),
            }
            for folder in folders
        }

    @classmethod
    def _validate_folder_graph(cls, folders: dict[int, dict[str, Any]]) -> None:
        """拒绝孤儿、环和超过产品上限的目录层级。"""
        for folder_id in folders:
            current_id = folder_id
            path: set[int] = set()
            depth = 0
            while current_id:
                if current_id in path:
                    raise ServiceException(message='文件夹层级存在循环，请联系管理员修复')
                current = folders.get(current_id)
                if current is None:
                    raise ServiceException(message='文件夹层级存在失效的上级目录')
                path.add(current_id)
                depth += 1
                if depth > MAX_FOLDER_DEPTH:
                    raise ServiceException(message=f'文件夹最多支持 {MAX_FOLDER_DEPTH} 层')
                current_id = int(current.get('parentId') or 0)

    @staticmethod
    def _validate_sibling_names(folders: dict[int, dict[str, Any]]) -> None:
        seen: dict[tuple[int, str], int] = {}
        for folder in folders.values():
            key = (int(folder.get('parentId') or 0), str(folder.get('name') or '').casefold())
            existing_id = seen.get(key)
            if existing_id is not None and existing_id != folder['id']:
                raise ServiceException(message='同一目录下已存在同名文件夹')
            seen[key] = folder['id']

    @staticmethod
    def _subtree_ids(folders: dict[int, dict[str, Any]], root_id: int) -> list[int]:
        children: dict[int, list[int]] = {}
        for folder in folders.values():
            children.setdefault(int(folder.get('parentId') or 0), []).append(folder['id'])
        result: list[int] = []
        pending = [root_id]
        visited: set[int] = set()
        while pending:
            folder_id = pending.pop()
            if folder_id in visited:
                raise ServiceException(message='文件夹层级存在循环，请联系管理员修复')
            visited.add(folder_id)
            result.append(folder_id)
            pending.extend(children.get(folder_id, ()))
        return result

    @classmethod
    def _build_tree(cls, folders: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
        nodes = {
            folder_id: {
                'id': folder['id'],
                'name': folder['name'],
                'parentId': folder['parentId'],
                'sortOrder': folder['sortOrder'],
            }
            for folder_id, folder in folders.items()
        }
        roots: list[dict[str, Any]] = []
        ordered = sorted(nodes.values(), key=lambda item: (item['sortOrder'], item['id']))
        for node in ordered:
            parent_id = node['parentId']
            if parent_id == 0:
                roots.append(node)
            else:
                nodes[parent_id].setdefault('children', []).append(node)
        return roots

    @classmethod
    async def get_folder_tree(cls, db: AsyncSession, user_id: int) -> list[dict[str, Any]]:
        folders = cls._folder_map(await MindmapFolderDao.get_folder_tree(db, user_id))
        cls._validate_folder_graph(folders)
        cls._validate_sibling_names(folders)
        return cls._build_tree(folders)

    @classmethod
    async def add_folder(
        cls,
        db: AsyncSession,
        model: MindmapFolderCreateModel,
        user_id: int,
        user_name: str,
    ) -> CrudResponseModel:
        existing = cls._folder_map(
            await MindmapFolderDao.get_folder_tree(db, user_id, for_update=True),
        )
        try:
            if model.parent_id and model.parent_id not in existing:
                raise ServiceException(message='父文件夹不存在或无权限')
            candidate_id = -1
            candidate = {
                'id': candidate_id,
                'name': model.name,
                'parentId': model.parent_id,
                'sortOrder': model.sort_order,
            }
            proposed = {**existing, candidate_id: candidate}
            cls._validate_folder_graph(proposed)
            cls._validate_sibling_names(proposed)
        except Exception:
            await db.rollback()
            raise

        try:
            folder = await MindmapFolderDao.add_folder(db, {
                'name': model.name,
                'parent_id': model.parent_id,
                'owner_id': user_id,
                'sort_order': model.sort_order,
                'create_by': user_name,
                'create_time': datetime.now(),
                'update_by': user_name,
                'update_time': datetime.now(),
            })
            folder_id = folder.id
            await db.commit()
            return CrudResponseModel(
                is_success=True,
                message='文件夹创建成功',
                result={'id': folder_id},
            )
        except IntegrityError as exc:
            await db.rollback()
            raise ServiceException(message='同一目录下已存在同名文件夹') from exc
        except Exception:
            await db.rollback()
            raise

    @classmethod
    async def update_folder(
        cls,
        db: AsyncSession,
        model: MindmapFolderUpdateModel,
        user_id: int,
        user_name: str,
    ) -> CrudResponseModel:
        existing = cls._folder_map(
            await MindmapFolderDao.get_folder_tree(db, user_id, for_update=True),
        )
        try:
            current = existing.get(model.id)
            if current is None:
                raise ServiceException(message='文件夹不存在或无权限')
            updated = {
                **current,
                **({'name': model.name} if model.name is not None else {}),
                **({'parentId': model.parent_id} if model.parent_id is not None else {}),
                **({'sortOrder': model.sort_order} if model.sort_order is not None else {}),
            }
            if updated['parentId'] and updated['parentId'] not in existing:
                raise ServiceException(message='目标父文件夹不存在或无权限')
            proposed = {**existing, model.id: updated}
            cls._validate_folder_graph(proposed)
            cls._validate_sibling_names(proposed)
        except Exception:
            await db.rollback()
            raise

        update_data = {
            key: value
            for key, value in {
                'name': model.name,
                'parent_id': model.parent_id,
                'sort_order': model.sort_order,
            }.items()
            if value is not None
        }
        if all(
            updated[field] == current[field]
            for field in ('name', 'parentId', 'sortOrder')
        ):
            await db.rollback()
            return CrudResponseModel(is_success=True, message='文件夹未发生变化')
        update_data.update(update_by=user_name, update_time=datetime.now())
        try:
            await MindmapFolderDao.update_folder(db, model.id, user_id, update_data)
            await db.commit()
            return CrudResponseModel(is_success=True, message='文件夹更新成功')
        except IntegrityError as exc:
            await db.rollback()
            raise ServiceException(message='同一目录下已存在同名文件夹') from exc
        except Exception:
            await db.rollback()
            raise

    @classmethod
    async def get_delete_impact(
        cls, db: AsyncSession, folder_id: int, user_id: int,
    ) -> dict[str, Any]:
        folders = cls._folder_map(await MindmapFolderDao.get_folder_tree(db, user_id))
        if folder_id not in folders:
            raise ServiceException(message='文件夹不存在或无权限')
        cls._validate_folder_graph(folders)
        subtree_ids = cls._subtree_ids(folders, folder_id)
        mindmap_count = await MindmapFolderDao.count_mindmaps_in_folders(
            db,
            subtree_ids,
            user_id,
        )
        return {
            'folderId': folder_id,
            'folderName': folders[folder_id]['name'],
            'folderCount': len(subtree_ids),
            'subfolderCount': len(subtree_ids) - 1,
            'mindmapCount': mindmap_count,
        }

    @classmethod
    async def delete_folder(
        cls, db: AsyncSession, folder_id: int, user_id: int,
    ) -> CrudResponseModel:
        folders = cls._folder_map(
            await MindmapFolderDao.get_folder_tree(db, user_id, for_update=True),
        )
        try:
            if folder_id not in folders:
                raise ServiceException(message='文件夹不存在或无权限')
            cls._validate_folder_graph(folders)
            subtree_ids = cls._subtree_ids(folders, folder_id)
            mindmap_count = await MindmapFolderDao.count_mindmaps_in_folders(
                db,
                subtree_ids,
                user_id,
            )
        except Exception:
            await db.rollback()
            raise
        try:
            moved_count = await MindmapFolderDao.move_mindmaps_out_of_folders(
                db,
                subtree_ids,
                user_id,
            )
            if moved_count != mindmap_count:
                raise ServiceException(message='目录内容已发生变化，请刷新后重试')
            await MindmapFolderDao.batch_soft_delete_folders(db, subtree_ids, user_id)
            await db.commit()
            return CrudResponseModel(
                is_success=True,
                message='文件夹删除成功',
                result={
                    'folderCount': len(subtree_ids),
                    'subfolderCount': len(subtree_ids) - 1,
                    'mindmapCount': mindmap_count,
                    'movedMindmapCount': moved_count,
                },
            )
        except Exception:
            await db.rollback()
            raise

    @classmethod
    async def sort_folders(
        cls, db: AsyncSession, model: MindmapFolderSortModel, user_id: int,
    ) -> CrudResponseModel:
        existing = cls._folder_map(
            await MindmapFolderDao.get_folder_tree(db, user_id, for_update=True),
        )
        try:
            for item in model.items:
                if item.id not in existing:
                    raise ServiceException(message=f'文件夹 {item.id} 不存在或无权限')
            proposed = {folder_id: dict(folder) for folder_id, folder in existing.items()}
            for item in model.items:
                proposed[item.id]['sortOrder'] = item.sort_order
                if item.parent_id is not None:
                    if item.parent_id and item.parent_id not in existing:
                        raise ServiceException(message=f'目标父文件夹 {item.parent_id} 不存在或无权限')
                    proposed[item.id]['parentId'] = item.parent_id
            cls._validate_folder_graph(proposed)
            cls._validate_sibling_names(proposed)
        except Exception:
            await db.rollback()
            raise

        try:
            changed_count = 0
            for item in model.items:
                current = existing[item.id]
                next_parent = current['parentId'] if item.parent_id is None else item.parent_id
                if current['sortOrder'] == item.sort_order and current['parentId'] == next_parent:
                    continue
                await MindmapFolderDao.update_sort_order(
                    db,
                    item.id,
                    user_id,
                    item.sort_order,
                    item.parent_id,
                )
                changed_count += 1
            await db.commit()
            return CrudResponseModel(
                is_success=True,
                message='排序更新成功',
                result={'changedCount': changed_count},
            )
        except IntegrityError as exc:
            await db.rollback()
            raise ServiceException(message='目标目录下已存在同名文件夹') from exc
        except Exception:
            await db.rollback()
            raise

    @classmethod
    async def move_mindmaps(
        cls, db: AsyncSession, model: MindmapMoveModel, user_id: int,
    ) -> CrudResponseModel:
        if model.folder_id is not None:
            folder = await MindmapFolderDao.get_folder_by_id(
                db,
                model.folder_id,
                user_id,
                for_update=True,
            )
            if not folder:
                await db.rollback()
                raise ServiceException(message='目标文件夹不存在或无权限')

        owned_ids = await MindmapFolderDao.get_owned_mindmap_ids(
            db,
            model.mindmap_ids,
            user_id,
            for_update=True,
        )
        if set(owned_ids) != set(model.mindmap_ids):
            await db.rollback()
            raise ServiceException(message='部分脑图不存在、已删除或无移动权限')
        try:
            moved_count = await MindmapFolderDao.move_mindmaps_to_folder(
                db,
                model.mindmap_ids,
                model.folder_id,
                user_id,
            )
            if moved_count != len(model.mindmap_ids):
                raise ServiceException(message='部分脑图移动失败，请刷新列表后重试')
            await db.commit()
            return CrudResponseModel(
                is_success=True,
                message='移动成功',
                result={'movedCount': moved_count},
            )
        except Exception:
            await db.rollback()
            raise
