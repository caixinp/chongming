import os
import uuid
from pathlib import Path

from fastapi.exceptions import HTTPException
from fastapi import UploadFile
import aiofiles

from ..core.config import get_config


config = get_config()


class UploadService:
    def __init__(self, upload_dir: str, chunk_size: int, file_type: str):
        self.upload_dir = upload_dir
        self.file_type = file_type
        self.chunk_size = chunk_size
        UPLOAD_DIR = Path(f"{self.upload_dir}/{self.file_type}")
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    async def upload(self, file_data: UploadFile):
        if file_data.filename is None:
            raise HTTPException(status_code=400, detail="Invalid file name")
        ext = os.path.splitext(file_data.filename)[1].lower()
        new_filename = f"{uuid.uuid4().hex}{ext}"
        file_path = os.path.join(self.upload_dir, self.file_type, new_filename)
        try:
            async with aiofiles.open(file_path, "wb") as out_file:
                while chunk := await file_data.read(self.chunk_size):
                    await out_file.write(chunk)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            await file_data.close()
        return (
            f"{config['default']['prefix']}/{self.file_type}/{new_filename}".replace(
                "\\", "/"
            ),
            new_filename,
        )
