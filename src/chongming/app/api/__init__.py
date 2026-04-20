"""
API 路由
"""

from fastapi import APIRouter

from .routers import todo, auth, upload

# 创建主路由
api_router = APIRouter()

# 注册子路由
api_router.include_router(todo.router, prefix="/todos", tags=["todo"])
api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(upload.router, prefix="/upload", tags=["upload"])


# 导出路由
__all__ = ["api_router"]
