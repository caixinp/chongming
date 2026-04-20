from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..model import Role, RoleUpdate, UserRole
from ..service.user import UserService


class RoleService:
    @staticmethod
    async def create_role(
        session: AsyncSession,
        name: str,
        description: Optional[str] = None,
        is_only_user: bool = False,
    ) -> Role:
        role = Role(name=name, description=description, is_only_user=is_only_user)
        session.add(role)
        await session.commit()
        await session.refresh(role)

        return role

    @staticmethod
    async def assign_role_to_user(
        session: AsyncSession,
        user_id: UUID,
        role_id: int,
    ):
        user_role = UserRole(user_id=user_id, role_id=role_id)
        session.add(user_role)
        await session.commit()
        await session.refresh(user_role)

    @classmethod
    async def get_role_by_name(cls, session: AsyncSession, name: str) -> Optional[Role]:
        result = await session.execute(select(Role).where(Role.name == name))
        return result.scalar_one_or_none()

    @classmethod
    async def get_role_by_id(
        cls, session: AsyncSession, role_id: int
    ) -> Optional[Role]:
        result = await session.get(Role, role_id)
        return result

    @staticmethod
    async def unbind_role_from_user(
        session: AsyncSession,
        user_id: UUID,
        role_id: int,
    ):
        user = await UserService.get_user_by_id(user_id, session)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        user.roles = [role for role in user.roles if role.id != role_id]
        await session.commit()
        await session.refresh(user)
        return user

    @staticmethod
    async def delete_role(
        role_id: int,
        session: AsyncSession,
    ) -> bool:
        result = await session.execute(
            select(UserRole).where(UserRole.role_id == role_id)
        )
        if result.scalars().all():
            raise HTTPException(status_code=400, detail="Role is not empty")
        role = await RoleService.get_role_by_id(session, role_id)
        if role is None:
            raise HTTPException(status_code=404, detail="Role not found")
        await session.delete(role)
        await session.commit()
        return True

    @classmethod
    async def update_role(
        cls,
        role_id: int,
        role_update: RoleUpdate,
        session: AsyncSession,
    ) -> Optional[Role]:
        role = await cls.get_role_by_id(session, role_id)
        if role is None:
            raise HTTPException(status_code=404, detail="Role not found")
        role.name = role_update.name if role_update.name else role.name
        role.description = (
            role_update.description if role_update.description else role.description
        )
        await session.commit()
        await session.refresh(role)
        return role
