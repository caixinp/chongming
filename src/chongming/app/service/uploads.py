import os
import uuid
from pathlib import Path

from fastapi.exceptions import HTTPException
from fastapi import UploadFile
import aiofiles

from ..core.config import get_config


config = get_config()


class UploadService:
    """
    文件上传服务类

    提供文件上传功能，支持将上传的文件保存到指定目录，
    并生成唯一的文件名以避免冲突。
    """

    def __init__(self, upload_dir: str, chunk_size: int, file_type: str):
        """
        初始化上传服务

        Args:
            upload_dir: 文件上传的根目录路径
            chunk_size: 文件读取的块大小（字节），用于控制内存使用
            file_type: 文件类型标识，用于创建对应的子目录
        """
        self.upload_dir = upload_dir
        self.file_type = file_type
        self.chunk_size = chunk_size
        UPLOAD_DIR = Path(f"{self.upload_dir}/{self.file_type}")
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    async def upload(self, file_data: UploadFile):
        """
        异步上传文件

        接收上传的文件数据，生成唯一文件名，并将文件分块写入到服务器磁盘。
        上传成功后返回文件的访问URL和新文件名。

        Args:
            file_data: FastAPI的UploadFile对象，包含上传的文件数据和元信息

        Returns:
            tuple: 包含两个元素的元组
                - str: 文件的完整访问URL路径
                - str: 生成的新文件名（UUID + 原始扩展名）

        Raises:
            HTTPException:
                - 400: 当文件名为空或无效时抛出
                - 500: 当文件写入过程中发生异常时抛出
        """
        if file_data.filename is None:
            raise HTTPException(status_code=400, detail="Invalid file name")

        # 提取文件扩展名并生成唯一的UUID文件名
        ext = os.path.splitext(file_data.filename)[1].lower()
        new_filename = f"{uuid.uuid4().hex}{ext}"
        file_path = os.path.join(self.upload_dir, self.file_type, new_filename)

        try:
            # 分块读取上传文件并异步写入磁盘，避免大文件占用过多内存
            async with aiofiles.open(file_path, "wb") as out_file:
                while chunk := await file_data.read(self.chunk_size):
                    await out_file.write(chunk)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            await file_data.close()

        # 构建并返回文件的访问URL和新文件名
        return (
            f"{config['default']['prefix']}/{self.file_type}/{new_filename}".replace(
                "\\", "/"
            ),
            new_filename,
        )
