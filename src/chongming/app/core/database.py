from typing import AsyncGenerator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


# 获取数据库会话的依赖
async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    async_session_maker = request.app.state.async_session_maker
    async with async_session_maker() as session:
        yield session
