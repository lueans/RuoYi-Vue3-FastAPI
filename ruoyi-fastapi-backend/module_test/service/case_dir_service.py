from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from common.constant import CommonConstant
from common.vo import CrudResponseModel
from exceptions.exception import ServiceException, ServiceWarning
from module_test.dao.case_dir_dao import CaseDirDao
from module_test.entity.do.case_dir_do import TestCaseDir
from module_test.entity.vo.case_dir_vo import CaseDirModel, CaseDirTreeModel, DeleteCaseDirModel
from utils.common_util import CamelCaseUtil


class CaseDirService:
    """
    用例目录管理服务层
    """

    @classmethod
    async def get_case_dir_tree_services(
        cls, query_db: AsyncSession, page_object: CaseDirModel
    ) -> list[dict[str, Any]]:
        list_result = await CaseDirDao.get_case_dir_list(query_db, page_object)
        tree_model_result = cls.list_to_tree(list_result)
        return [item.model_dump(exclude_unset=True, by_alias=True) for item in tree_model_result]

    @classmethod
    async def get_case_dir_for_edit_option_services(
        cls, query_db: AsyncSession, page_object: CaseDirModel
    ) -> list[dict[str, Any]]:
        list_result = await CaseDirDao.get_case_dir_info_for_edit_option(query_db, page_object)
        return CamelCaseUtil.transform_result(list_result)

    @classmethod
    async def get_case_dir_list_services(
        cls, query_db: AsyncSession, page_object: CaseDirModel
    ) -> list[dict[str, Any]]:
        list_result = await CaseDirDao.get_case_dir_list(query_db, page_object)
        return CamelCaseUtil.transform_result(list_result)

    @classmethod
    async def check_dir_name_unique_services(cls, query_db: AsyncSession, page_object: CaseDirModel) -> bool:
        dir_id = -1 if page_object.dir_id is None else page_object.dir_id
        case_dir = await CaseDirDao.get_case_dir_detail_by_info(
            query_db, CaseDirModel(dirName=page_object.dir_name, parentId=page_object.parent_id)
        )
        if case_dir and case_dir.dir_id != dir_id:
            return CommonConstant.NOT_UNIQUE
        return CommonConstant.UNIQUE

    @classmethod
    async def add_case_dir_services(cls, query_db: AsyncSession, page_object: CaseDirModel) -> CrudResponseModel:
        if not await cls.check_dir_name_unique_services(query_db, page_object):
            raise ServiceException(message=f'新增目录{page_object.dir_name}失败，目录名称已存在')
        if page_object.parent_id and page_object.parent_id != 0:
            parent_info = await CaseDirDao.get_case_dir_by_id(query_db, page_object.parent_id)
            if parent_info.status != CommonConstant.DEPT_NORMAL:
                raise ServiceException(message=f'目录{parent_info.dir_name}停用，不允许新增')
            page_object.ancestors = f'{parent_info.ancestors},{page_object.parent_id}'
        else:
            page_object.parent_id = 0
            page_object.ancestors = '0'
        try:
            await CaseDirDao.add_case_dir_dao(query_db, page_object)
            await query_db.commit()
            return CrudResponseModel(is_success=True, message='新增成功')
        except Exception as e:
            await query_db.rollback()
            raise e

    @classmethod
    async def edit_case_dir_services(cls, query_db: AsyncSession, page_object: CaseDirModel) -> CrudResponseModel:
        if not await cls.check_dir_name_unique_services(query_db, page_object):
            raise ServiceException(message=f'修改目录{page_object.dir_name}失败，目录名称已存在')
        if page_object.parent_id and page_object.dir_id == page_object.parent_id:
            raise ServiceException(message=f'修改目录{page_object.dir_name}失败，上级目录不能是自己')
        if not page_object.parent_id:
            page_object.parent_id = 0
        old_dir = await CaseDirDao.get_case_dir_by_id(query_db, page_object.dir_id)
        new_parent = await CaseDirDao.get_case_dir_by_id(query_db, page_object.parent_id) if page_object.parent_id != 0 else None
        try:
            if old_dir:
                if new_parent:
                    new_ancestors = f'{new_parent.ancestors},{new_parent.dir_id}'
                else:
                    new_ancestors = '0'
                old_ancestors = old_dir.ancestors
                page_object.ancestors = new_ancestors
                children = await CaseDirDao.get_children_case_dir_dao(query_db, page_object.dir_id)
                update_children = []
                for child in children:
                    child_ancestors = child.ancestors.replace(old_ancestors, new_ancestors, 1) if child.ancestors.startswith(old_ancestors) else child.ancestors
                    update_children.append({'dir_id': child.dir_id, 'ancestors': child_ancestors})
                if children:
                    await CaseDirDao.update_case_dir_children_dao(query_db, update_children)
            edit_data = page_object.model_dump(exclude_unset=True)
            await CaseDirDao.edit_case_dir_dao(query_db, edit_data)
            await query_db.commit()
            return CrudResponseModel(is_success=True, message='更新成功')
        except Exception as e:
            await query_db.rollback()
            raise e

    @classmethod
    async def delete_case_dir_services(
        cls, query_db: AsyncSession, page_object: DeleteCaseDirModel
    ) -> CrudResponseModel:
        if page_object.dir_ids:
            dir_id_list = page_object.dir_ids.split(',')
            try:
                for dir_id in dir_id_list:
                    if (await CaseDirDao.count_children_dao(query_db, int(dir_id))) > 0:
                        raise ServiceWarning(message='存在下级目录，不允许删除')
                    await CaseDirDao.delete_case_dir_dao(query_db, CaseDirModel(dirId=dir_id))
                await query_db.commit()
                return CrudResponseModel(is_success=True, message='删除成功')
            except Exception as e:
                await query_db.rollback()
                raise e
        else:
            raise ServiceException(message='传入目录id为空')

    @classmethod
    async def case_dir_detail_services(cls, query_db: AsyncSession, dir_id: int) -> CaseDirModel:
        case_dir = await CaseDirDao.get_case_dir_detail_by_id(query_db, dir_id=dir_id)
        return CaseDirModel(**CamelCaseUtil.transform_result(case_dir)) if case_dir else CaseDirModel()

    @classmethod
    def list_to_tree(cls, permission_list: Sequence[TestCaseDir]) -> list[CaseDirTreeModel]:
        _list = [
            CaseDirTreeModel(id=item.dir_id, label=item.dir_name, parentId=item.parent_id)
            for item in permission_list
        ]
        mapping: dict[int, CaseDirTreeModel] = dict(zip([i.id for i in _list], _list))
        container: list[CaseDirTreeModel] = []
        for d in _list:
            parent = mapping.get(d.parent_id)
            if parent is None:
                container.append(d)
            else:
                children = parent.children
                if not children:
                    children = []
                children.append(d)
                parent.children = children
        return container
