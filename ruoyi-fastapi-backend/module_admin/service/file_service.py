import os
import uuid
from datetime import datetime

from fastapi import Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from config.env import UploadConfig
from exceptions.exception import ServiceException
from module_admin.dao.file_dao import FileDao
from module_admin.entity.do.file_do import SysFile
from module_admin.entity.vo.file_vo import DeleteFileModel, FileModel, FilePageQueryModel
from module_admin.entity.vo.user_vo import CurrentUserModel
from module_admin.service.common_service import CommonService


class FileService:
    """
    文件管理服务层
    """

    @classmethod
    async def get_file_list_services(cls, query_db: AsyncSession, query_object: FilePageQueryModel):
        """
        获取文件列表service
        """
        return await FileDao.get_file_list(query_db, query_object, is_page=True)

    @classmethod
    async def add_file_services(cls, request: Request, file: UploadFile, query_db: AsyncSession, current_user: CurrentUserModel):
        """
        新增文件service
        """
        upload_result = await CommonService.upload_service(request, file)
        if not upload_result.is_success:
            raise ServiceException(message=upload_result.message)
        
        upload_data = upload_result.result
        file_size = file.size
        
        new_file = SysFile(
            file_uuid=str(uuid.uuid4()),
            file_name=upload_data.original_filename,
            file_path=upload_data.url,
            file_size=file_size,
            file_suffix=upload_data.original_filename.rsplit('.', 1)[-1] if '.' in upload_data.original_filename else '',
            oss_type=0,
            create_by=current_user.user.user_id,
            create_time=datetime.now(),
            update_by=current_user.user.user_name,
            update_time=datetime.now(),
            del_flag='0'
        )
        added_file = await FileDao.add_file(query_db, new_file)
        return FileModel.model_validate(added_file)

    @classmethod
    async def delete_file_services(cls, query_db: AsyncSession, file_ids: DeleteFileModel):
        """
        删除文件service
        """
        if not file_ids.file_ids:
            raise ServiceException(message='文件ID不能为空')
            
        ids = [int(i) for i in file_ids.file_ids.split(',')]
        await FileDao.delete_file(query_db, ids)
        return True
