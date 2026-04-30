from typing import Optional
from uuid import UUID
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..model.user import User
from ..core.security import get_password_hash


class UserService:
    """用户服务类，提供用户相关的业务逻辑操作"""

    @staticmethod
    async def get_user_by_email(email: str, session: AsyncSession) -> Optional[User]:
        """
        根据邮箱地址查询用户

        Args:
            email: 用户的邮箱地址
            session: 异步数据库会话

        Returns:
            如果找到则返回用户对象，否则返回None
        """
        result = await session.execute(select(User).where(User.email == email))  # type: ignore
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_by_id(user_id: UUID, session: AsyncSession) -> Optional[User]:
        """
        根据用户ID查询用户

        Args:
            user_id: 用户的UUID标识
            session: 异步数据库会话

        Returns:
            如果找到则返回用户对象，否则返回None
        """
        return await session.get(User, user_id)

    @staticmethod
    async def create_user(
        session: AsyncSession, email: str, password: str, **kwargs
    ) -> User:
        """
        创建新用户

        Args:
            session: 异步数据库会话
            email: 用户的邮箱地址
            password: 用户的明文密码，将自动进行哈希加密
            **kwargs: 其他用户属性参数

        Returns:
            创建成功的用户对象

        Raises:
            IntegrityError: 当邮箱已存在时可能抛出完整性错误
        """
        hashed = get_password_hash(password)
        user = User(email=email, hashed_password=hashed, created_at=str(time.time() * 1000), **kwargs)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user
