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
    """图片上传响应数据模型"""

    url: str
    filename: str
    file_type: str


@router.post("/image", response_model=UploadResponse)
async def upload_image(file: UploadFile = File(...)):
    """
    上传图片文件接口

    该接口用于接收用户上传的图片文件，进行格式验证后保存到服务器，
    并返回文件的访问URL、文件名和文件类型信息。

    Args:
        file (UploadFile): 上传的文件对象，必须为图片格式

    Returns:
        UploadResponse: 包含以下字段的响应对象：
            - url (str): 上传文件的访问URL
            - filename (str): 保存后的文件名
            - file_type (str): 文件扩展名（如 .jpg, .png 等）

    Raises:
        HTTPException:
            - 400: 当文件类型不是图片格式时
            - 400: 当文件名为空时
            - 400: 当文件扩展名不在允许列表中时

    Note:
        支持的图片格式包括：.jpg, .jpeg, .png, .gif, .webp
        需要用户认证才能访问此接口
    """
    # 验证文件内容类型是否为图片
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Invalid file type")

    # 验证文件名是否存在
    if file.filename is None:
        raise HTTPException(status_code=400, detail="Invalid file name")

    # 检查文件扩展名是否在允许的范围内
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
        raise HTTPException(status_code=400, detail="Invalid file type")

    # 执行文件上传操作
    url, filename = await upload_image_service.upload(file)
    return UploadResponse(url=url, filename=filename, file_type=ext)
