from collections.abc import Sequence
from typing import Union

from sqlalchemy import bindparam, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.util import immutabledict

from module_test.entity.do.case_dir_do import TestCaseDir
from module_test.entity.vo.case_dir_vo import CaseDirModel


class CaseDirDao:
    """
    用例目录管理数据库操作层
    """

    @classmethod
    async def get_case_dir_by_id(cls, db: AsyncSession, dir_id: int) -> Union[TestCaseDir, None]:
        return (await db.execute(select(TestCaseDir).where(TestCaseDir.dir_id == dir_id))).scalars().first()

    @classmethod
    async def get_case_dir_detail_by_id(cls, db: AsyncSession, dir_id: int) -> Union[TestCaseDir, None]:
        return (
            (await db.execute(select(TestCaseDir).where(TestCaseDir.dir_id == dir_id, TestCaseDir.del_flag == '0')))
            .scalars()
            .first()
        )

    @classmethod
    async def get_case_dir_detail_by_info(cls, db: AsyncSession, case_dir: CaseDirModel) -> Union[TestCaseDir, None]:
        return (
            (
                await db.execute(
                    select(TestCaseDir).where(
                        TestCaseDir.parent_id == case_dir.parent_id if case_dir.parent_id is not None else True,
                        TestCaseDir.dir_name == case_dir.dir_name if case_dir.dir_name else True,
                        TestCaseDir.del_flag == '0',
                    )
                )
            )
            .scalars()
            .first()
        )

    @classmethod
    async def get_case_dir_info_for_edit_option(
        cls, db: AsyncSession, case_dir_info: CaseDirModel
    ) -> Sequence[TestCaseDir]:
        return (
            (
                await db.execute(
                    select(TestCaseDir)
                    .where(
                        TestCaseDir.dir_id != case_dir_info.dir_id,
                        ~TestCaseDir.dir_id.in_(
                            select(TestCaseDir.dir_id).where(
                                func.find_in_set(case_dir_info.dir_id, TestCaseDir.ancestors)
                            )
                        ),
                        TestCaseDir.del_flag == '0',
                        TestCaseDir.status == '0',
                    )
                    .order_by(TestCaseDir.order_num)
                    .distinct()
                )
            )
            .scalars()
            .all()
        )

    @classmethod
    async def get_children_case_dir_dao(cls, db: AsyncSession, dir_id: int) -> Sequence[TestCaseDir]:
        return (
            (await db.execute(select(TestCaseDir).where(func.find_in_set(dir_id, TestCaseDir.ancestors))))
            .scalars()
            .all()
        )

    @classmethod
    async def get_case_dir_list(cls, db: AsyncSession, page_object: CaseDirModel) -> Sequence[TestCaseDir]:
        return (
            (
                await db.execute(
                    select(TestCaseDir)
                    .where(
                        TestCaseDir.del_flag == '0',
                        TestCaseDir.dir_id == page_object.dir_id if page_object.dir_id is not None else True,
                        TestCaseDir.status == page_object.status if page_object.status else True,
                        TestCaseDir.dir_name.like(f'%{page_object.dir_name}%') if page_object.dir_name else True,
                    )
                    .order_by(TestCaseDir.order_num)
                    .distinct()
                )
            )
            .scalars()
            .all()
        )

    @classmethod
    async def add_case_dir_dao(cls, db: AsyncSession, case_dir: CaseDirModel) -> TestCaseDir:
        db_obj = TestCaseDir(**case_dir.model_dump())
        db.add(db_obj)
        await db.flush()
        return db_obj

    @classmethod
    async def edit_case_dir_dao(cls, db: AsyncSession, case_dir: dict) -> None:
        await db.execute(update(TestCaseDir), [case_dir])

    @classmethod
    async def update_case_dir_children_dao(cls, db: AsyncSession, update_list: list) -> None:
        await db.execute(
            update(TestCaseDir)
            .where(TestCaseDir.dir_id == bindparam('dir_id'))
            .values({'dir_id': bindparam('dir_id'), 'ancestors': bindparam('ancestors')}),
            update_list,
            execution_options=immutabledict({'synchronize_session': None}),
        )

    @classmethod
    async def delete_case_dir_dao(cls, db: AsyncSession, case_dir: CaseDirModel) -> None:
        await db.execute(
            update(TestCaseDir)
            .where(TestCaseDir.dir_id == case_dir.dir_id)
            .values(del_flag='2', update_by=case_dir.update_by, update_time=case_dir.update_time)
        )

    @classmethod
    async def count_children_dao(cls, db: AsyncSession, dir_id: int) -> Union[int, None]:
        return (
            await db.execute(
                select(func.count('*'))
                .select_from(TestCaseDir)
                .where(TestCaseDir.del_flag == '0', TestCaseDir.parent_id == dir_id)
                .limit(1)
            )
        ).scalar()
