from collections.abc import Sequence
from typing import Union

from sqlalchemy import bindparam, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.util import immutabledict

from module_test.entity.do.business_line_do import TestBusinessLine
from module_test.entity.vo.business_line_vo import BusinessLineModel


class BusinessLineDao:
    """
    业务线管理模块数据库操作层
    """

    @classmethod
    async def get_business_line_by_id(cls, db: AsyncSession, line_id: int) -> Union[TestBusinessLine, None]:
        """
        根据业务线id获取业务线信息

        :param db: orm对象
        :param line_id: 业务线id
        :return: 业务线信息对象
        """
        result = (
            await db.execute(select(TestBusinessLine).where(TestBusinessLine.line_id == line_id))
        ).scalars().first()

        return result

    @classmethod
    async def get_business_line_detail_by_id(cls, db: AsyncSession, line_id: int) -> Union[TestBusinessLine, None]:
        """
        根据业务线id获取业务线详细信息

        :param db: orm对象
        :param line_id: 业务线id
        :return: 业务线信息对象
        """
        result = (
            (
                await db.execute(
                    select(TestBusinessLine).where(
                        TestBusinessLine.line_id == line_id, TestBusinessLine.del_flag == '0'
                    )
                )
            )
            .scalars()
            .first()
        )

        return result

    @classmethod
    async def get_business_line_detail_by_info(
        cls, db: AsyncSession, business_line: BusinessLineModel
    ) -> Union[TestBusinessLine, None]:
        """
        根据业务线参数获取业务线信息

        :param db: orm对象
        :param business_line: 业务线参数对象
        :return: 业务线信息对象
        """
        result = (
            (
                await db.execute(
                    select(TestBusinessLine).where(
                        TestBusinessLine.parent_id == business_line.parent_id
                        if business_line.parent_id is not None
                        else True,
                        TestBusinessLine.line_name == business_line.line_name
                        if business_line.line_name
                        else True,
                        TestBusinessLine.del_flag == '0',
                    )
                )
            )
            .scalars()
            .first()
        )

        return result

    @classmethod
    async def get_business_line_detail_by_code(
        cls, db: AsyncSession, line_code: str
    ) -> Union[TestBusinessLine, None]:
        """
        根据业务线编码获取业务线信息

        :param db: orm对象
        :param line_code: 业务线编码
        :return: 业务线信息对象
        """
        result = (
            (
                await db.execute(
                    select(TestBusinessLine).where(
                        TestBusinessLine.line_code == line_code,
                        TestBusinessLine.del_flag == '0',
                    )
                )
            )
            .scalars()
            .first()
        )

        return result

    @classmethod
    async def get_business_line_info_for_edit_option(
        cls, db: AsyncSession, business_line_info: BusinessLineModel
    ) -> Sequence[TestBusinessLine]:
        """
        获取业务线编辑对应的在用业务线列表信息

        :param db: orm对象
        :param business_line_info: 业务线对象
        :return: 业务线列表信息
        """
        result = (
            (
                await db.execute(
                    select(TestBusinessLine)
                    .where(
                        TestBusinessLine.line_id != business_line_info.line_id,
                        ~TestBusinessLine.line_id.in_(
                            select(TestBusinessLine.line_id).where(
                                func.find_in_set(business_line_info.line_id, TestBusinessLine.ancestors)
                            )
                        ),
                        TestBusinessLine.del_flag == '0',
                        TestBusinessLine.status == '0',
                    )
                    .order_by(TestBusinessLine.order_num)
                    .distinct()
                )
            )
            .scalars()
            .all()
        )

        return result

    @classmethod
    async def get_children_business_line_dao(
        cls, db: AsyncSession, line_id: int
    ) -> Sequence[TestBusinessLine]:
        """
        根据业务线id查询当前业务线的子业务线列表信息

        :param db: orm对象
        :param line_id: 业务线id
        :return: 子业务线信息列表
        """
        result = (
            (
                await db.execute(
                    select(TestBusinessLine).where(func.find_in_set(line_id, TestBusinessLine.ancestors))
                )
            )
            .scalars()
            .all()
        )

        return result

    @classmethod
    async def get_business_line_list_for_tree(
        cls, db: AsyncSession, business_line_info: BusinessLineModel
    ) -> Sequence[TestBusinessLine]:
        """
        获取所有在用业务线列表信息

        :param db: orm对象
        :param business_line_info: 业务线对象
        :return: 在用业务线列表信息
        """
        result = (
            (
                await db.execute(
                    select(TestBusinessLine)
                    .where(
                        TestBusinessLine.status == '0',
                        TestBusinessLine.del_flag == '0',
                        TestBusinessLine.line_name.like(f'%{business_line_info.line_name}%')
                        if business_line_info.line_name
                        else True,
                    )
                    .order_by(TestBusinessLine.order_num)
                    .distinct()
                )
            )
            .scalars()
            .all()
        )

        return result

    @classmethod
    async def get_business_line_list(
        cls, db: AsyncSession, page_object: BusinessLineModel
    ) -> Sequence[TestBusinessLine]:
        """
        根据查询参数获取业务线列表信息

        :param db: orm对象
        :param page_object: 查询参数对象
        :return: 业务线列表信息对象
        """
        result = (
            (
                await db.execute(
                    select(TestBusinessLine)
                    .where(
                        TestBusinessLine.del_flag == '0',
                        TestBusinessLine.line_id == page_object.line_id
                        if page_object.line_id is not None
                        else True,
                        TestBusinessLine.status == page_object.status if page_object.status else True,
                        TestBusinessLine.line_name.like(f'%{page_object.line_name}%')
                        if page_object.line_name
                        else True,
                        TestBusinessLine.line_code.like(f'%{page_object.line_code}%')
                        if page_object.line_code
                        else True,
                    )
                    .order_by(TestBusinessLine.order_num)
                    .distinct()
                )
            )
            .scalars()
            .all()
        )

        return result

    @classmethod
    async def add_business_line_dao(cls, db: AsyncSession, business_line: BusinessLineModel) -> TestBusinessLine:
        """
        新增业务线数据库操作

        :param db: orm对象
        :param business_line: 业务线对象
        :return: 新增结果
        """
        db_business_line = TestBusinessLine(**business_line.model_dump())
        db.add(db_business_line)
        await db.flush()

        return db_business_line

    @classmethod
    async def edit_business_line_dao(cls, db: AsyncSession, business_line: dict) -> None:
        """
        编辑业务线数据库操作

        :param db: orm对象
        :param business_line: 需要更新的业务线字典
        :return:
        """
        await db.execute(update(TestBusinessLine), [business_line])

    @classmethod
    async def update_business_line_children_dao(cls, db: AsyncSession, update_list: list) -> None:
        """
        更新子业务线信息

        :param db: orm对象
        :param update_list: 需要更新的业务线列表
        :return:
        """
        await db.execute(
            update(TestBusinessLine)
            .where(TestBusinessLine.line_id == bindparam('line_id'))
            .values(
                {
                    'line_id': bindparam('line_id'),
                    'ancestors': bindparam('ancestors'),
                }
            ),
            update_list,
            execution_options=immutabledict({'synchronize_session': None}),
        )

    @classmethod
    async def update_business_line_status_normal_dao(cls, db: AsyncSession, line_id_list: list) -> None:
        """
        批量更新业务线状态为正常

        :param db: orm对象
        :param line_id_list: 业务线id列表
        :return:
        """
        await db.execute(
            update(TestBusinessLine).where(TestBusinessLine.line_id.in_(line_id_list)).values(status='0')
        )

    @classmethod
    async def delete_business_line_dao(cls, db: AsyncSession, business_line: BusinessLineModel) -> None:
        """
        删除业务线数据库操作

        :param db: orm对象
        :param business_line: 业务线对象
        :return:
        """
        await db.execute(
            update(TestBusinessLine)
            .where(TestBusinessLine.line_id == business_line.line_id)
            .values(del_flag='2', update_by=business_line.update_by, update_time=business_line.update_time)
        )

    @classmethod
    async def count_normal_children_dao(cls, db: AsyncSession, line_id: int) -> Union[int, None]:
        """
        根据业务线id查询所有子业务线（正常状态）的数量

        :param db: orm对象
        :param line_id: 业务线id
        :return: 所有子业务线（正常状态）的数量
        """
        count = (
            await db.execute(
                select(func.count('*'))
                .select_from(TestBusinessLine)
                .where(
                    TestBusinessLine.status == '0',
                    TestBusinessLine.del_flag == '0',
                    func.find_in_set(line_id, TestBusinessLine.ancestors),
                )
            )
        ).scalar()

        return count

    @classmethod
    async def count_children_dao(cls, db: AsyncSession, line_id: int) -> Union[int, None]:
        """
        根据业务线id查询直接子业务线的数量

        :param db: orm对象
        :param line_id: 业务线id
        :return: 直接子业务线的数量
        """
        count = (
            await db.execute(
                select(func.count('*'))
                .select_from(TestBusinessLine)
                .where(TestBusinessLine.del_flag == '0', TestBusinessLine.parent_id == line_id)
                .limit(1)
            )
        ).scalar()

        return count
