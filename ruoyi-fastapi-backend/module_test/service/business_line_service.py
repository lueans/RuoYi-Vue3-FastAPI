from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from common.constant import CommonConstant
from common.vo import CrudResponseModel
from exceptions.exception import ServiceException, ServiceWarning
from module_test.dao.business_line_dao import BusinessLineDao
from module_test.entity.do.business_line_do import TestBusinessLine
from module_test.entity.vo.business_line_vo import (
    BusinessLineModel,
    BusinessLineTreeModel,
    DeleteBusinessLineModel,
)
from utils.common_util import CamelCaseUtil


class BusinessLineService:
    """
    业务线管理模块服务层
    """

    @classmethod
    async def get_business_line_tree_services(
        cls, query_db: AsyncSession, page_object: BusinessLineModel
    ) -> list[dict[str, Any]]:
        """
        获取业务线树信息service

        :param query_db: orm对象
        :param page_object: 查询参数对象
        :return: 业务线树信息对象
        """
        list_result = await BusinessLineDao.get_business_line_list_for_tree(query_db, page_object)
        tree_model_result = cls.list_to_tree(list_result)
        tree_result = [item.model_dump(exclude_unset=True, by_alias=True) for item in tree_model_result]

        return tree_result

    @classmethod
    async def get_business_line_for_edit_option_services(
        cls, query_db: AsyncSession, page_object: BusinessLineModel
    ) -> list[dict[str, Any]]:
        """
        获取业务线编辑业务线树信息service

        :param query_db: orm对象
        :param page_object: 查询参数对象
        :return: 业务线树信息对象
        """
        list_result = await BusinessLineDao.get_business_line_info_for_edit_option(query_db, page_object)

        return CamelCaseUtil.transform_result(list_result)

    @classmethod
    async def get_business_line_list_services(
        cls, query_db: AsyncSession, page_object: BusinessLineModel
    ) -> list[dict[str, Any]]:
        """
        获取业务线列表信息service

        :param query_db: orm对象
        :param page_object: 查询参数对象
        :return: 业务线列表信息对象
        """
        list_result = await BusinessLineDao.get_business_line_list(query_db, page_object)

        return CamelCaseUtil.transform_result(list_result)

    @classmethod
    async def check_business_line_name_unique_services(
        cls, query_db: AsyncSession, page_object: BusinessLineModel
    ) -> bool:
        """
        校验业务线名称是否唯一service

        :param query_db: orm对象
        :param page_object: 业务线对象
        :return: 校验结果
        """
        line_id = -1 if page_object.line_id is None else page_object.line_id
        business_line = await BusinessLineDao.get_business_line_detail_by_info(
            query_db, BusinessLineModel(lineName=page_object.line_name, parentId=page_object.parent_id)
        )
        if business_line and business_line.line_id != line_id:
            return CommonConstant.NOT_UNIQUE
        return CommonConstant.UNIQUE

    @classmethod
    async def check_business_line_code_unique_services(
        cls, query_db: AsyncSession, page_object: BusinessLineModel
    ) -> bool:
        """
        校验业务线编码是否唯一service

        :param query_db: orm对象
        :param page_object: 业务线对象
        :return: 校验结果
        """
        line_id = -1 if page_object.line_id is None else page_object.line_id
        business_line = await BusinessLineDao.get_business_line_detail_by_code(query_db, page_object.line_code)
        if business_line and business_line.line_id != line_id:
            return CommonConstant.NOT_UNIQUE
        return CommonConstant.UNIQUE

    @classmethod
    async def add_business_line_services(
        cls, query_db: AsyncSession, page_object: BusinessLineModel
    ) -> CrudResponseModel:
        """
        新增业务线信息service

        :param query_db: orm对象
        :param page_object: 新增业务线对象
        :return: 新增业务线校验结果
        """
        if not await cls.check_business_line_name_unique_services(query_db, page_object):
            raise ServiceException(message=f'新增业务线{page_object.line_name}失败，业务线名称已存在')
        if not await cls.check_business_line_code_unique_services(query_db, page_object):
            raise ServiceException(message=f'新增业务线{page_object.line_name}失败，业务线编码已存在')
        parent_info = await BusinessLineDao.get_business_line_by_id(query_db, page_object.parent_id)
        if parent_info.status != CommonConstant.DEPT_NORMAL:
            raise ServiceException(message=f'业务线{parent_info.line_name}停用，不允许新增')
        page_object.ancestors = f'{parent_info.ancestors},{page_object.parent_id}'
        try:
            await BusinessLineDao.add_business_line_dao(query_db, page_object)
            await query_db.commit()
            return CrudResponseModel(is_success=True, message='新增成功')
        except Exception as e:
            await query_db.rollback()
            raise e

    @classmethod
    async def edit_business_line_services(
        cls, query_db: AsyncSession, page_object: BusinessLineModel
    ) -> CrudResponseModel:
        """
        编辑业务线信息service

        :param query_db: orm对象
        :param page_object: 编辑业务线对象
        :return: 编辑业务线校验结果
        """
        if not await cls.check_business_line_name_unique_services(query_db, page_object):
            raise ServiceException(message=f'修改业务线{page_object.line_name}失败，业务线名称已存在')
        if not await cls.check_business_line_code_unique_services(query_db, page_object):
            raise ServiceException(message=f'修改业务线{page_object.line_name}失败，业务线编码已存在')
        if page_object.line_id == page_object.parent_id:
            raise ServiceException(message=f'修改业务线{page_object.line_name}失败，上级业务线不能是自己')
        if (
            page_object.status == CommonConstant.DEPT_DISABLE
            and (await BusinessLineDao.count_normal_children_dao(query_db, page_object.line_id)) > 0
        ):
            raise ServiceException(message=f'修改业务线{page_object.line_name}失败，该业务线包含未停用的子业务线')
        new_parent = await BusinessLineDao.get_business_line_by_id(query_db, page_object.parent_id)
        old_line = await BusinessLineDao.get_business_line_by_id(query_db, page_object.line_id)
        try:
            if new_parent and old_line:
                new_ancestors = f'{new_parent.ancestors},{new_parent.line_id}'
                old_ancestors = old_line.ancestors
                page_object.ancestors = new_ancestors
                await cls.update_business_line_children(query_db, page_object.line_id, new_ancestors, old_ancestors)
            edit_data = page_object.model_dump(exclude_unset=True)
            await BusinessLineDao.edit_business_line_dao(query_db, edit_data)
            if (
                page_object.status == CommonConstant.DEPT_NORMAL
                and page_object.ancestors
                and page_object.ancestors != '0'
            ):
                await cls.update_parent_status_normal(query_db, page_object)
            await query_db.commit()
            return CrudResponseModel(is_success=True, message='更新成功')
        except Exception as e:
            await query_db.rollback()
            raise e

    @classmethod
    async def delete_business_line_services(
        cls, query_db: AsyncSession, page_object: DeleteBusinessLineModel
    ) -> CrudResponseModel:
        """
        删除业务线信息service

        :param query_db: orm对象
        :param page_object: 删除业务线对象
        :return: 删除业务线校验结果
        """
        if page_object.line_ids:
            line_id_list = page_object.line_ids.split(',')
            try:
                for line_id in line_id_list:
                    if (await BusinessLineDao.count_children_dao(query_db, int(line_id))) > 0:
                        raise ServiceWarning(message='存在下级业务线,不允许删除')
                    await BusinessLineDao.delete_business_line_dao(
                        query_db, BusinessLineModel(lineId=line_id)
                    )
                await query_db.commit()
                return CrudResponseModel(is_success=True, message='删除成功')
            except Exception as e:
                await query_db.rollback()
                raise e
        else:
            raise ServiceException(message='传入业务线id为空')

    @classmethod
    async def business_line_detail_services(cls, query_db: AsyncSession, line_id: int) -> BusinessLineModel:
        """
        获取业务线详细信息service

        :param query_db: orm对象
        :param line_id: 业务线id
        :return: 业务线id对应的信息
        """
        business_line = await BusinessLineDao.get_business_line_detail_by_id(query_db, line_id=line_id)
        result = (
            BusinessLineModel(**CamelCaseUtil.transform_result(business_line))
            if business_line
            else BusinessLineModel()
        )

        return result

    @classmethod
    def list_to_tree(cls, permission_list: Sequence[TestBusinessLine]) -> list[BusinessLineTreeModel]:
        """
        工具方法：根据业务线列表信息生成树形嵌套数据

        :param permission_list: 业务线列表信息
        :return: 业务线树形嵌套数据
        """
        _list = [
            BusinessLineTreeModel(id=item.line_id, label=item.line_name, parentId=item.parent_id)
            for item in permission_list
        ]
        mapping: dict[int, BusinessLineTreeModel] = dict(zip([i.id for i in _list], _list))

        container: list[BusinessLineTreeModel] = []

        for d in _list:
            parent = mapping.get(d.parent_id)
            if parent is None:
                container.append(d)
            else:
                children: list[BusinessLineTreeModel] = parent.children
                if not children:
                    children = []
                children.append(d)
                parent.children = children

        return container

    @classmethod
    async def replace_first(cls, original_str: str, old_str: str, new_str: str) -> str:
        """
        工具方法：替换字符串

        :param original_str: 需要替换的原始字符串
        :param old_str: 用于匹配的字符串
        :param new_str: 替换的字符串
        :return: 替换后的字符串
        """
        if original_str.startswith(old_str):
            return original_str.replace(old_str, new_str, 1)
        return original_str

    @classmethod
    async def update_parent_status_normal(cls, query_db: AsyncSession, business_line: BusinessLineModel) -> None:
        """
        更新父业务线状态为正常

        :param query_db: orm对象
        :param business_line: 业务线对象
        :return:
        """
        line_id_list = business_line.ancestors.split(',')
        await BusinessLineDao.update_business_line_status_normal_dao(query_db, list(map(int, line_id_list)))

    @classmethod
    async def update_business_line_children(
        cls, query_db: AsyncSession, line_id: int, new_ancestors: str, old_ancestors: str
    ) -> None:
        """
        更新子业务线信息

        :param query_db: orm对象
        :param line_id: 业务线id
        :param new_ancestors: 新的祖先
        :param old_ancestors: 旧的祖先
        :return:
        """
        children = await BusinessLineDao.get_children_business_line_dao(query_db, line_id)
        update_children = []
        for child in children:
            child_ancestors = await cls.replace_first(child.ancestors, old_ancestors, new_ancestors)
            update_children.append({'line_id': child.line_id, 'ancestors': child_ancestors})
        if children:
            await BusinessLineDao.update_business_line_children_dao(query_db, update_children)
