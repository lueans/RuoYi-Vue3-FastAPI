from sqlalchemy import select, update, desc
from sqlalchemy.ext.asyncio import AsyncSession

from module_admin.entity.do.file_do import SysFile
from module_admin.entity.vo.file_vo import FilePageQueryModel
from utils.page_util import PageUtil


class FileDao:
    """
    文件管理DAO层
    """

    @classmethod
    async def get_file_list(cls, db: AsyncSession, query_object: FilePageQueryModel, is_page: bool = False):
        """
        根据查询参数获取文件列表
        """
        stmt = select(SysFile).where(SysFile.del_flag == '0')
        
        if query_object.file_name:
            stmt = stmt.where(SysFile.file_name.like(f'%{query_object.file_name}%'))
        if query_object.file_suffix:
            stmt = stmt.where(SysFile.file_suffix == query_object.file_suffix)
        if query_object.oss_type is not None:
             stmt = stmt.where(SysFile.oss_type == query_object.oss_type)
        if query_object.begin_time and query_object.end_time:
            stmt = stmt.where(SysFile.create_time.between(query_object.begin_time, query_object.end_time))
        
        stmt = stmt.order_by(desc(SysFile.create_time))
        return await PageUtil.paginate(db, stmt, query_object.page_num, query_object.page_size, is_page)

    @classmethod
    async def get_file_detail_by_id(cls, db: AsyncSession, file_id: int):
        """
        根据文件ID获取文件详情
        """
        stmt = select(SysFile).where(SysFile.file_id == file_id, SysFile.del_flag == '0')
        result = await db.execute(stmt)
        return result.scalars().first()
    
    @classmethod
    async def get_file_detail_by_uuid(cls, db: AsyncSession, file_uuid: str):
        """
        根据文件UUID获取文件详情
        """
        stmt = select(SysFile).where(SysFile.file_uuid == file_uuid, SysFile.del_flag == '0')
        result = await db.execute(stmt)
        return result.scalars().first()

    @classmethod
    async def add_file(cls, db: AsyncSession, file: SysFile):
        """
        新增文件
        """
        db.add(file)
        await db.flush()
        return file

    @classmethod
    async def delete_file(cls, db: AsyncSession, file_ids: list[int]):
        """
        删除文件（逻辑删除）
        """
        stmt = update(SysFile).where(SysFile.file_id.in_(file_ids)).values(del_flag='2')
        await db.execute(stmt)
