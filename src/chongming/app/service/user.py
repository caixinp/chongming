from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from ..model.user import User
from ..core.security import get_password_hash


class UserService:
    @staticmethod
    async def get_user_by_email(email: str, session: AsyncSession) -> Optional[User]:
        result = await session.execute(select(User).where(User.email == email))  # type: ignore
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_by_id(user_id: int, session: AsyncSession) -> Optional[User]:
        return await session.get(User, user_id)

    @staticmethod
    async def create_user(
        session: AsyncSession, email: str, password: str, **kwargs
    ) -> User:
        hashed = get_password_hash(password)
        user = User(email=email, hashed_password=hashed, **kwargs)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user
