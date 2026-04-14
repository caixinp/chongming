import os
import mimetypes
from fastapi import HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from typing import Optional
from sqlite_vfs.core import SQLiteVFS


class SVFSStaticFiles(StaticFiles):
    def __init__(self, directory, vfs_db_path="static.svfs"):
        if not os.path.exists(vfs_db_path):
            raise RuntimeError(
                f"虚拟文件系统数据库 {vfs_db_path} 不存在，请先运行打包脚本"
            )
        self.vfs_db_path = vfs_db_path
        self.vfs = SQLiteVFS(vfs_db_path, compress=False)
        super().__init__(directory=directory)

    async def get_response(self, path: str, scope):
        # 统一路径格式：以 / 开头，并将 Windows 反斜杠转为正斜杠
        normalized_path = "/" + path.replace("\\", "/")

        # 获取文件信息
        file_info = self.vfs.get_file_info(normalized_path)

        if file_info is None:
            # SPA 回退：如果不是静态资源扩展名，尝试返回 index.html
            if not any(
                normalized_path.endswith(ext)
                for ext in [
                    ".js",
                    ".css",
                    ".png",
                    ".jpg",
                    ".ico",
                    ".svg",
                    ".webp",
                    ".json",
                ]
            ):
                index_info = self.vfs.get_file_info("/index.html")
                if index_info:
                    content = self.vfs.read_file("/index.html")
                    return Response(content=content, media_type="text/html")
            raise HTTPException(status_code=404, detail="File not found")

        # 如果是目录，也返回 index.html（某些情况）
        if file_info["is_directory"]:
            index_info = self.vfs.get_file_info(f"{normalized_path}/index.html")
            if index_info:
                content = self.vfs.read_file(f"{normalized_path}/index.html")
                return Response(content=content, media_type="text/html")
            raise HTTPException(status_code=404, detail="Directory index not found")

        # 读取文件内容
        content = self.vfs.read_file(normalized_path)
        content_type = file_info.get("content_type") or "application/octet-stream"
        # 简单根据扩展名补充 MIME 类型（可选）
        if normalized_path.endswith(".js"):
            content_type = "application/javascript"
        elif normalized_path.endswith(".css"):
            content_type = "text/css"
        elif normalized_path.endswith(".html"):
            content_type = "text/html"
        elif normalized_path.endswith(".ico"):
            content_type = "image/x-icon"

        return Response(content=content, media_type=content_type)


static_files_handler = SVFSStaticFiles(directory="/")
