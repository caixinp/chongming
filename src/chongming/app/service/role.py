from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..model import Role, RoleUpdate, UserRole
from ..service.user import UserService


class RoleService:
    """角色服务类，提供角色管理相关的业务逻辑"""

    @staticmethod
    async def create_role(
        session: AsyncSession,
        name: str,
        description: Optional[str] = None,
        is_only_user: bool = False,
    ) -> Role:
        """
        创建新角色

        Args:
            session: 数据库会话对象
            name: 角色名称
            description: 角色描述，可选
            is_only_user: 是否仅用于用户，默认为False

        Returns:
            Role: 创建成功的角色对象
        """
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
        """
        为用户分配角色

        Args:
            session: 数据库会话对象
            user_id: 用户UUID
            role_id: 角色ID
        """
        user_role = UserRole(user_id=user_id, role_id=role_id)
        session.add(user_role)
        await session.commit()
        await session.refresh(user_role)

    @classmethod
    async def get_role_by_name(cls, session: AsyncSession, name: str) -> Optional[Role]:
        """
        根据角色名称查询角色

        Args:
            session: 数据库会话对象
            name: 角色名称

        Returns:
            Optional[Role]: 找到的角色对象，未找到则返回None
        """
        result = await session.execute(select(Role).where(Role.name == name))
        return result.scalar_one_or_none()

    @classmethod
    async def get_role_by_id(
        cls, session: AsyncSession, role_id: int
    ) -> Optional[Role]:
        """
        根据角色ID查询角色

        Args:
            session: 数据库会话对象
            role_id: 角色ID

        Returns:
            Optional[Role]: 找到的角色对象，未找到则返回None
        """
        result = await session.get(Role, role_id)
        return result

    @staticmethod
    async def unbind_role_from_user(
        session: AsyncSession,
        user_id: UUID,
        role_id: int,
    ):
        """
        从用户解绑角色

        Args:
            session: 数据库会话对象
            user_id: 用户UUID
            role_id: 角色ID

        Returns:
            User: 更新后的用户对象

        Raises:
            HTTPException: 当用户不存在时抛出404错误
        """
        user = await UserService.get_user_by_id(user_id, session)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        # 过滤掉指定角色，保留其他角色
        user.roles = [role for role in user.roles if role.id != role_id]
        await session.commit()
        await session.refresh(user)
        return user

    @staticmethod
    async def delete_role(
        role_id: int,
        session: AsyncSession,
    ) -> bool:
        """
        删除角色

        Args:
            role_id: 角色ID
            session: 数据库会话对象

        Returns:
            bool: 删除成功返回True

        Raises:
            HTTPException: 当角色被使用时抛出400错误，角色不存在时抛出404错误
        """
        # 检查角色是否被用户使用
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
        """
        更新角色信息

        Args:
            role_id: 角色ID
            role_update: 角色更新数据对象
            session: 数据库会话对象

        Returns:
            Optional[Role]: 更新后的角色对象

        Raises:
            HTTPException: 当角色不存在时抛出404错误
        """
        role = await cls.get_role_by_id(session, role_id)
        if role is None:
            raise HTTPException(status_code=404, detail="Role not found")

        # 只更新提供的字段，保持原有值不变
        role.name = role_update.name if role_update.name else role.name
        role.description = (
            role_update.description if role_update.description else role.description
        )
        await session.commit()
        await session.refresh(role)
        return role
