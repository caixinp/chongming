import os

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from pydantic import BaseModel

from ..deps import get_current_user
from ...service.uploads import UploadService
from ...core.config import get_config


config = get_config()
router = APIRouter(dependencies=[Depends(get_current_user)])
upload_image_service = UploadService(
    config["default"]["upload_path"], 1024 * 1024, "images"
)


class UploadResponse(BaseModel):
    url: str
    filename: str
    file_type: str


@router.post("/image", response_model=UploadResponse)
async def upload_image(file: UploadFile = File(...)):

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Invalid file type")
    if file.filename is None:
        raise HTTPException(status_code=400, detail="Invalid file name")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
        raise HTTPException(status_code=400, detail="Invalid file type")
    url, filename = await upload_image_service.upload(file)
    return UploadResponse(url=url, filename=filename, file_type=ext)
