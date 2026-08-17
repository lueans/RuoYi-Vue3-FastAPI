import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from fastapi import UploadFile

from config.env import UploadConfig
from exceptions.exception import ServiceException
from module_admin.service.common_service import CommonService


class CommonServiceSecurityTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_upload_path = UploadConfig.UPLOAD_PATH
        UploadConfig.UPLOAD_PATH = self.temp_dir.name

    def tearDown(self) -> None:
        UploadConfig.UPLOAD_PATH = self.original_upload_path
        self.temp_dir.cleanup()

    async def test_upload_ignores_client_path_and_uses_server_filename(self) -> None:
        request = SimpleNamespace(url=SimpleNamespace(scheme='http', netloc='testserver'))
        upload = UploadFile(filename='../../outside.txt', file=BytesIO(b'safe content'), size=12)

        result = await CommonService.upload_service(request, upload)

        stored_path = Path(  # noqa: ASYNC240
            self.temp_dir.name, result.result.file_name.removeprefix('/profile/')
        ).resolve()
        stored_path.relative_to(Path(self.temp_dir.name).resolve())  # noqa: ASYNC240
        self.assertEqual(stored_path.suffix, '.txt')
        self.assertNotIn('outside', stored_path.name)
        self.assertEqual(result.result.original_filename, 'outside.txt')
        self.assertEqual(stored_path.read_bytes(), b'safe content')

    async def test_download_rejects_parent_directory_escape(self) -> None:
        with self.assertRaises(ServiceException):
            await CommonService.download_resource_services('/profile/../outside_20260814120000A001.txt')

    async def test_download_accepts_file_inside_upload_root(self) -> None:
        target = Path(self.temp_dir.name, 'upload', '2026', '08', '14', 'document.txt')
        target.parent.mkdir(parents=True)
        target.write_text('content', encoding='utf-8')  # noqa: ASYNC240

        result = await CommonService.download_resource_services('/profile/upload/2026/08/14/document.txt')

        self.assertTrue(result.is_success)


if __name__ == '__main__':
    unittest.main()
