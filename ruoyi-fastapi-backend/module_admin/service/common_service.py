import os
import uuid
from datetime import datetime
from pathlib import Path

import aiofiles
from fastapi import BackgroundTasks, Request, UploadFile

from common.vo import CrudResponseModel
from config.env import UploadConfig
from exceptions.exception import ServiceException
from module_admin.entity.vo.common_vo import UploadResponseModel
from utils.upload_util import UploadUtil


class CommonService:
    """
    通用模块服务层
    """

    @classmethod
    async def upload_service(cls, request: Request, file: UploadFile) -> CrudResponseModel:
        """
        通用上传service

        :param request: Request对象
        :param file: 上传文件对象
        :return: 上传结果
        """
        if not UploadUtil.check_file_extension(file):
            raise ServiceException(message='文件类型不合法')
        if file.size and file.size > UploadConfig.MAX_UPLOAD_SIZE:
            max_mb = UploadConfig.MAX_UPLOAD_SIZE // (1024 * 1024)
            raise ServiceException(message=f'文件大小超出限制，最大允许{max_mb}MB')
        now = datetime.now()
        relative_path = Path('upload', now.strftime('%Y'), now.strftime('%m'), now.strftime('%d'))
        upload_root = Path(UploadConfig.UPLOAD_PATH).resolve()  # noqa: ASYNC240
        dir_path = (upload_root / relative_path).resolve()
        cls._ensure_path_within_root(dir_path, upload_root)
        dir_path.mkdir(parents=True, exist_ok=True)

        original_filename = Path((file.filename or '').replace('\\', '/')).name
        extension = Path(original_filename).suffix.lower()
        filename = f'{uuid.uuid4().hex}{extension}'
        filepath = (dir_path / filename).resolve()
        cls._ensure_path_within_root(filepath, upload_root)
        async with aiofiles.open(filepath, 'wb') as f:
            # 流式写出大型文件，这里的10代表10MB
            while True:
                chunk = await file.read(1024 * 1024 * 10)
                if not chunk:
                    break
                await f.write(chunk)

        return CrudResponseModel(
            is_success=True,
            result=UploadResponseModel(
                fileName=f'{UploadConfig.UPLOAD_PREFIX}/{relative_path.as_posix()}/{filename}',
                newFileName=filename,
                originalFilename=original_filename,
                url=(
                    f'{request.url.scheme}://{request.url.netloc}'
                    f'{UploadConfig.UPLOAD_PREFIX}/{relative_path.as_posix()}/{filename}'
                ),
            ),
            message='上传成功',
        )

    @classmethod
    async def download_services(
        cls, background_tasks: BackgroundTasks, file_name: str, delete: bool
    ) -> CrudResponseModel:
        """
        下载下载目录文件service

        :param background_tasks: 后台任务对象
        :param file_name: 下载的文件名称
        :param delete: 是否在下载完成后删除文件
        :return: 上传结果
        """
        filepath = os.path.join(UploadConfig.DOWNLOAD_PATH, file_name)
        if '..' in file_name:
            raise ServiceException(message='文件名称不合法')
        if not UploadUtil.check_file_exists(filepath):
            raise ServiceException(message='文件不存在')
        if delete:
            background_tasks.add_task(UploadUtil.delete_file, filepath)
        return CrudResponseModel(is_success=True, result=UploadUtil.generate_file(filepath), message='下载成功')

    @classmethod
    async def download_resource_services(cls, resource: str) -> CrudResponseModel:
        """
        下载上传目录文件service

        :param resource: 下载的文件名称
        :return: 上传结果
        """
        prefix = UploadConfig.UPLOAD_PREFIX.rstrip('/')
        if not resource.startswith(f'{prefix}/'):
            raise ServiceException(message='文件名称不合法')
        relative_resource = resource[len(prefix) :].lstrip('/\\')
        upload_root = Path(UploadConfig.UPLOAD_PATH).resolve()  # noqa: ASYNC240
        filepath = (upload_root / relative_resource).resolve()
        cls._ensure_path_within_root(filepath, upload_root)
        if not UploadUtil.check_file_exists(filepath):
            raise ServiceException(message='文件不存在')
        return CrudResponseModel(
            is_success=True,
            result=UploadUtil.generate_file(str(filepath)),
            message='下载成功',
        )

    @staticmethod
    def _ensure_path_within_root(path: Path, root: Path) -> None:
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ServiceException(message='文件名称不合法') from exc
