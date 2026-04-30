from typing import Optional, List, Sequence
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..model import Permission, PermissionUpdate, RolePermission, Role, User
from ..core.cache import acached, get_cache
from .user import UserService
from .role import RoleService


# 用户权限缓存的 TTL（秒），权限变更后最多 2 分钟自动刷新
_USER_PERMS_CACHE_TTL = 120


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
    async def list_permissions(
        cls,
        session: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        resource: Optional[str] = None,
    ) -> Sequence[Permission]:
        """
        获取权限列表，支持分页和按资源筛选

        :param session: 数据库会话对象
        :param skip: 跳过的记录数，用于分页
        :param limit: 返回的最大记录数，用于分页
        :param resource: 资源名称筛选条件，可选
        :return: 权限对象列表
        """
        query = select(Permission)

        if resource:
            query = query.where(Permission.resource == resource)

        query = query.offset(skip).limit(limit)
        result = await session.execute(query)
        return result.scalars().all()

    @classmethod
    async def update_permission(
        cls,
        session: AsyncSession,
        permission_id: int,
        permission_update: PermissionUpdate,
    ) -> Permission:
        """
        更新权限信息

        :param session: 数据库会话对象
        :param permission_id: 权限ID
        :param permission_update: 权限更新数据
        :return: 更新后的权限对象
        :raises HTTPException: 当权限不存在时抛出404错误
        """
        permission = await cls.get_permission_by_id(session, permission_id)
        if not permission:
            raise HTTPException(status_code=404, detail="Permission not found")

        # 只更新提供的字段
        update_data = permission_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(permission, field, value)

        await session.commit()
        await session.refresh(permission)
        return permission

    @classmethod
    async def delete_permission(
        cls,
        session: AsyncSession,
        permission_id: int,
    ) -> bool:
        """
        删除权限

        :param session: 数据库会话对象
        :param permission_id: 权限ID
        :return: 删除成功返回True
        :raises HTTPException: 当权限不存在或正在被使用时抛出对应错误
        """
        # 检查权限是否被角色使用
        result = await session.execute(
            select(RolePermission).where(
                RolePermission.permission_id == permission_id
            )
        )
        if result.scalars().all():
            raise HTTPException(
                status_code=400, detail="Permission is assigned to roles, cannot delete"
            )

        permission = await cls.get_permission_by_id(session, permission_id)
        if not permission:
            raise HTTPException(status_code=404, detail="Permission not found")

        await session.delete(permission)
        await session.commit()
        return True

    @classmethod
    async def get_permissions_by_role(
        cls,
        session: AsyncSession,
        role_id: int,
    ) -> Sequence[Permission]:
        """
        获取指定角色的所有权限

        使用 JOIN 查询直接从数据库获取，避免在异步上下文中触发懒加载。

        :param session: 数据库会话对象
        :param role_id: 角色ID
        :return: 权限对象列表
        :raises HTTPException: 当角色不存在时抛出404错误
        """
        from ..model.relationship_table import RolePermission as RolePermTB

        stmt = (
            select(Permission)
            .join(RolePermTB, RolePermTB.permission_id == Permission.id) # type: ignore
            .where(RolePermTB.role_id == role_id)
        )
        result = await session.execute(stmt)
        permissions = result.scalars().all()

        if not permissions:
            # 确认角色是否存在
            role = await RoleService.get_role_by_id(session, role_id)
            if not role:
                raise HTTPException(status_code=404, detail="Role not found")

        return permissions

    # ---- TTL 缓存辅助方法 ----

    @classmethod
    def _get_user_perms_cache_key(cls, user_id: UUID) -> str:
        """生成用户权限缓存的键"""
        return f"user_perms:{user_id}"

    @classmethod
    def _invalidate_user_perms_cache(cls, user_id: UUID):
        """
        清除指定用户的权限缓存

        :param user_id: 用户UUID
        """
        cache = get_cache()
        cache_key = cls._get_user_perms_cache_key(user_id)
        cache.delete(cache_key)

    # ---- 核心业务方法 ----

    @classmethod
    @acached(ttl=_USER_PERMS_CACHE_TTL, key_func=lambda cls, session, user_id: f"user_perms:{user_id}")
    async def get_permissions_by_user(
        cls,
        session: AsyncSession,
        user_id: UUID,
    ) -> List[Permission]:
        """
        获取指定用户的所有权限（通过用户的所有角色汇总）

        使用 @acached 装饰器自动缓存查询结果，缓存键为 user_perms:{user_id}。
        TTL 120 秒作为兜底机制。当用户权限发生变更时，主动调用
        _invalidate_user_perms_cache() 清除缓存。

        :param session: 数据库会话对象
        :param user_id: 用户UUID
        :return: 去重后的权限对象列表
        :raises HTTPException: 当用户不存在时抛出404错误
        """
        # 通过 role_permission 和 user_role 关联表进行 JOIN 查询
        from ..model.relationship_table import UserRole as UserRoleTB, RolePermission as RolePermTB

        stmt = (
            select(Permission)
            .join(RolePermTB, RolePermTB.permission_id == Permission.id) # type: ignore
            .join(Role, Role.id == RolePermTB.role_id) # type: ignore
            .join(UserRoleTB, UserRoleTB.role_id == Role.id) # type: ignore
            .where(UserRoleTB.user_id == user_id)
            .distinct()
        )
        result = await session.execute(stmt)
        permissions = result.scalars().all()

        if not permissions:
            # 确认用户是否存在
            user = await UserService.get_user_by_id(user_id, session)
            if not user:
                raise HTTPException(status_code=404, detail="User not found")

        return list(permissions)

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
        :raises HTTPException: 当角色或权限不存在，或权限已分配给角色时抛出错误
        """
        role = await RoleService.get_role_by_id(session, role_id)
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")

        permission = await cls.get_permission_by_id(session, permission_id)
        if not permission:
            raise HTTPException(status_code=404, detail="Permission not found")

        # 检查是否已经分配
        existing = await session.execute(
            select(RolePermission).where(
                RolePermission.role_id == role_id,
                RolePermission.permission_id == permission_id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Permission already assigned to role")

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
        # 清除该用户的权限缓存，下次查询时重新加载
        cls._invalidate_user_perms_cache(user_id)
        return user

    @classmethod
    async def unbind_permission_from_role(
        cls, session: AsyncSession, role_id: int, permission_id: int
    ) -> Role:
        """
        从角色中解除权限绑定

        直接通过 RolePermission 关联表删除记录，避免在异步上下文中触发懒加载。

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

        # 通过关联表删除记录
        from ..model.relationship_table import RolePermission as RolePermTB
        from sqlmodel import delete

        stmt = delete(RolePermTB).where(
            RolePermTB.role_id == role_id, # type: ignore
            RolePermTB.permission_id == permission_id, # type: ignore
        )
        await session.execute(stmt)
        await session.commit()
        await session.refresh(role)
        return role

    @classmethod
    async def unbind_permission_from_user(
        cls, session: AsyncSession, user_id: UUID, permission_id: int
    ):
        """
        从用户中解除权限绑定

        通过找到用户的专属角色，从该角色中移除指定权限。

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

        if role.id is not None:
            # 直接通过关联表删除记录
            from ..model.relationship_table import RolePermission as RolePermTB
            from sqlmodel import delete

            stmt = delete(RolePermTB).where(
                RolePermTB.role_id == role.id, # type: ignore
                RolePermTB.permission_id == permission_id, # type: ignore
            )
            await session.execute(stmt)
            await session.commit()
            await session.refresh(role)
            # 清除该用户的权限缓存
            cls._invalidate_user_perms_cache(user_id)
