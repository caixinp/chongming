from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..model import Permission, RolePermission, Role, User
from .user import UserService
from .role import RoleService


class PermissionService:
    @classmethod
    async def create_permission(
        cls,
        session: AsyncSession,
        name: str,
        resource: str,
        action: str,
        description: Optional[str] = None,
    ) -> Permission:
        permission = Permission(
            name=name, resource=resource, action=action, description=description
        )
        session.add(permission)
        await session.commit()
        await session.refresh(permission)
        return permission

    @classmethod
    async def get_permission_by_id(
        cls, session: AsyncSession, permission_id: int
    ) -> Optional[Permission]:
        return await session.get(Permission, permission_id)

    @classmethod
    async def get_permission_by_name(
        cls, session: AsyncSession, name: str
    ) -> Optional[Permission]:
        result = await session.execute(
            select(Permission).where(Permission.name == name)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def assign_permission_to_role(
        cls, session: AsyncSession, role_id: int, permission_id: int
    ) -> RolePermission:
        role_permission = RolePermission(role_id=role_id, permission_id=permission_id)
        session.add(role_permission)
        await session.commit()
        await session.refresh(role_permission)
        return role_permission

    @classmethod
    async def assign_permission_to_user(
        cls,
        session: AsyncSession,
        user_id: UUID,
        permission_id: int,
    ) -> User:
        permission = await cls.get_permission_by_id(session, permission_id)
        if not permission:
            raise HTTPException(status_code=404, detail="Permission not found")
        user = await UserService.get_user_by_id(user_id, session)
        if user is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        role = await RoleService.get_role_by_name(session, str(user_id))
        if role is None:
            role = await RoleService.create_role(
                session, str(user_id), is_only_user=True
            )
        if role.id is None:
            raise HTTPException(status_code=500, detail="角色ID无效")
        if permission.id is None:
            raise HTTPException(status_code=500, detail="权限ID无效")
        await cls.assign_permission_to_role(session, role.id, permission.id)
        user.roles.append(role)
        await session.commit()
        await session.refresh(user)
        return user

    @classmethod
    async def unbind_permission_from_role(
        cls, session: AsyncSession, role_id: int, permission_id: int
    ) -> Role:
        role = await RoleService.get_role_by_id(session, role_id)
        if role is None:
            raise HTTPException(status_code=404, detail="Role not found")
        role.permissions = [p for p in role.permissions if p.id != permission_id]
        await session.commit()
        await session.refresh(role)
        return role

    @classmethod
    async def unbind_permission_from_user(
        cls, session: AsyncSession, user_id: UUID, permission_id: int
    ):
        user = await UserService.get_user_by_id(user_id, session)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        role = await RoleService.get_role_by_name(session, str(user.id))
        if role is None:
            raise HTTPException(status_code=404, detail="Role not found")
        role.permissions = [
            permission
            for permission in role.permissions
            if permission.id != permission_id
        ]
        await session.commit()
        await session.refresh(role)
