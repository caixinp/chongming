from fastapi import HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from sqlite_vfs.core import SQLiteVFS


class SVFSStaticFiles(StaticFiles):
    """
    基于 SQLite VFS 的静态文件服务类

    该类继承自 FastAPI 的 StaticFiles，使用 SQLite 虚拟文件系统来存储和提供静态文件。
    支持单页应用（SPA）的路由回退机制，当请求的文件不存在时，会自动返回 index.html。
    """

    def __init__(self, directory, vfs_db_path="static.svfs"):
        """
        初始化 SVFSStaticFiles 实例

        参数:
            directory (str): 静态文件的根目录路径
            vfs_db_path (str): SQLite VFS 数据库文件路径，默认为 "static.svfs"

        返回值:
            无
        """
        vfs_db_path = vfs_db_path
        self._vfs = SQLiteVFS(vfs_db_path, compress=False)
        super().__init__(directory=directory)

    async def get_response(self, path: str, scope):
        """
        根据请求路径获取对应的静态文件响应

        该方法处理静态文件的请求逻辑，包括：
        1. 路径标准化处理
        2. 文件存在性检查
        3. SPA 路由回退支持
        4. 目录索引处理
        5. MIME 类型自动识别

        参数:
            path (str): 请求的文件路径
            scope: ASGI 作用域对象，包含请求上下文信息

        返回值:
            Response: FastAPI 响应对象，包含文件内容和正确的 Content-Type

        异常:
            HTTPException: 当文件不存在且无法回退到 index.html 时，抛出 404 错误
        """
        # 统一路径格式：以 / 开头，并将 Windows 反斜杠转为正斜杠
        normalized_path = "/" + path.replace("\\", "/")

        # 获取文件信息
        file_info = self._vfs.get_file_info(normalized_path)

        # 处理文件不存在的情况，尝试 SPA 回退机制
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
                index_info = self._vfs.get_file_info("/index.html")
                if index_info:
                    content = self._vfs.read_file("/index.html")
                    return Response(content=content, media_type="text/html")
            raise HTTPException(status_code=404, detail="File not found")

        # 处理目录请求，返回目录下的 index.html
        if file_info["is_directory"]:
            index_info = self._vfs.get_file_info(f"{normalized_path}/index.html")
            if index_info:
                content = self._vfs.read_file(f"{normalized_path}/index.html")
                return Response(content=content, media_type="text/html")
            raise HTTPException(status_code=404, detail="Directory index not found")

        # 读取文件内容并确定 MIME 类型
        content = self._vfs.read_file(normalized_path)
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
