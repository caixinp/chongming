from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..model import Permission, RolePermission, Role, User
from .user import UserService
from .role import RoleService


class PermissionService:
    """权限服务类，提供权限的创建、查询、分配和解除绑定等功能"""

    @classmethod
    async def create_permission(
        cls,
        session: AsyncSession,
        name: str,
        resource: str,
        action: str,
        description: Optional[str] = None,
    ) -> Permission:
        """
        创建新的权限记录

        :param session: 数据库会话对象
        :param name: 权限名称
        :param resource: 资源标识
        :param action: 操作类型
        :param description: 权限描述，可选
        :return: 创建的权限对象
        """
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
        """
        根据ID获取权限

        :param session: 数据库会话对象
        :param permission_id: 权限ID
        :return: 权限对象，如果不存在则返回None
        """
        return await session.get(Permission, permission_id)

    @classmethod
    async def get_permission_by_name(
        cls, session: AsyncSession, name: str
    ) -> Optional[Permission]:
        """
        根据名称获取权限

        :param session: 数据库会话对象
        :param name: 权限名称
        :return: 权限对象，如果不存在则返回None
        """
        result = await session.execute(
            select(Permission).where(Permission.name == name)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def assign_permission_to_role(
        cls, session: AsyncSession, role_id: int, permission_id: int
    ) -> RolePermission:
        """
        将权限分配给角色

        :param session: 数据库会话对象
        :param role_id: 角色ID
        :param permission_id: 权限ID
        :return: 创建的角色权限关联对象
        """
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
        """
        将权限分配给用户

        如果用户没有专属角色，则会为用户创建一个专属角色，然后将权限分配给该角色

        :param session: 数据库会话对象
        :param user_id: 用户UUID
        :param permission_id: 权限ID
        :return: 更新后的用户对象
        :raises HTTPException: 当权限或用户不存在时抛出404错误，当角色或权限ID无效时抛出500错误
        """
        # 验证权限是否存在
        permission = await cls.get_permission_by_id(session, permission_id)
        if not permission:
            raise HTTPException(status_code=404, detail="Permission not found")

        # 验证用户是否存在
        user = await UserService.get_user_by_id(user_id, session)
        if user is None:
            raise HTTPException(status_code=404, detail="用户不存在")

        # 获取或创建用户的专属角色
        role = await RoleService.get_role_by_name(session, str(user_id))
        if role is None:
            role = await RoleService.create_role(
                session, str(user_id), is_only_user=True
            )

        # 验证角色和权限ID的有效性
        if role.id is None:
            raise HTTPException(status_code=500, detail="角色ID无效")
        if permission.id is None:
            raise HTTPException(status_code=500, detail="权限ID无效")

        # 将权限分配给角色
        await cls.assign_permission_to_role(session, role.id, permission.id)
        user.roles.append(role)
        await session.commit()
        await session.refresh(user)
        return user

    @classmethod
    async def unbind_permission_from_role(
        cls, session: AsyncSession, role_id: int, permission_id: int
    ) -> Role:
        """
        从角色中解除权限绑定

        :param session: 数据库会话对象
        :param role_id: 角色ID
        :param permission_id: 权限ID
        :return: 更新后的角色对象
        :raises HTTPException: 当角色不存在时抛出404错误
        """
        # 验证角色是否存在
        role = await RoleService.get_role_by_id(session, role_id)
        if role is None:
            raise HTTPException(status_code=404, detail="Role not found")

        # 从角色的权限列表中移除指定权限
        role.permissions = [p for p in role.permissions if p.id != permission_id]
        await session.commit()
        await session.refresh(role)
        return role

    @classmethod
    async def unbind_permission_from_user(
        cls, session: AsyncSession, user_id: UUID, permission_id: int
    ):
        """
        从用户中解除权限绑定

        通过找到用户的专属角色，从该角色中移除指定权限

        :param session: 数据库会话对象
        :param user_id: 用户UUID
        :param permission_id: 权限ID
        :raises HTTPException: 当用户或角色不存在时抛出404错误
        """
        # 验证用户是否存在
        user = await UserService.get_user_by_id(user_id, session)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # 获取用户的专属角色
        role = await RoleService.get_role_by_name(session, str(user.id))
        if role is None:
            raise HTTPException(status_code=404, detail="Role not found")

        # 从角色权限列表中移除指定权限
        role.permissions = [
            permission
            for permission in role.permissions
            if permission.id != permission_id
        ]
        await session.commit()
        await session.refresh(role)
