"""
用户角色分配 Handler
=====================

为用户分配/撤销角色，查询用户角色及权限。
"""
import logging
from typing import List

from sqlmodel import select

from app.bootstrap import app
from app.database_models import User, Role, UserRole, Permission, RolePermission
from chongming_permission import invalidate_user_permissions, get_user_permissions
from .role import get_role
from ..listeners import get_db_session_master, get_db_session_slave

from models import (
    UserRoleAssignInput, UserRoleAssignOutput,
    UserRoleRevokeInput, UserRoleRevokeOutput,
    UserRoleListInput, UserRoleListOutput,
    RoleGetInput
)

logger = logging.getLogger("chongming.worker.user_auth")


@app.handler("userrole.assign")
async def assign_user_role(input: UserRoleAssignInput) -> UserRoleAssignOutput:
    """为用户分配角色

    同时更新 User.roles 冗余字段，方便快速查询。
    """
    async for session in get_db_session_master():
        # 检查用户
        user = await session.get(User, int(input.user_id))
        if user is None:
            raise ValueError(f"用户不存在: {input.user_id}")

        # 检查角色
        role_stmt = select(Role).where(Role.name == input.role_name)
        role_result = await session.execute(role_stmt)
        role = role_result.scalar_one_or_none()
        if role is None:
            raise ValueError(f"角色不存在: {input.role_name}")

        # 检查是否已分配
        ur_stmt = select(UserRole).where(
            UserRole.user_id == user.id,
            UserRole.role_id == role.id,
        )
        ur_result = await session.execute(ur_stmt)
        if ur_result.scalar_one_or_none() is not None:
            return UserRoleAssignOutput(
                status=True,
                message=f"用户 '{user.username}' 已有角色 '{role.name}'",
            )

        # 分配角色
        ur = UserRole(user_id=user.id, role_id=role.id) # type: ignore
        session.add(ur)

        # 更新 User.roles 冗余字段
        if role.name not in user.roles:
            user.roles = list(set(user.roles + [role.name]))

        session.add(user)
        await session.commit()

        # 角色变更后使权限缓存失效
        try:
            await invalidate_user_permissions(str(input.user_id))
        except Exception as e:
            logger.warning("缓存失效失败（不影响业务）: %s", e)

        logger.info("分配角色: user=%s, role=%s", user.username, role.name)
        return UserRoleAssignOutput(
            status=True,
            message=f"用户 '{user.username}' 已分配角色 '{role.name}'",
        )

    raise RuntimeError("No database session available")


@app.handler("userrole.revoke")
async def revoke_user_role(input: UserRoleRevokeInput) -> UserRoleRevokeOutput:
    """撤销用户的角色

    同时更新 User.roles 冗余字段。
    """
    async for session in get_db_session_master():
        # 检查用户
        user = await session.get(User, int(input.user_id))
        if user is None:
            raise ValueError(f"用户不存在: {input.user_id}")

        # 检查角色
        role_stmt = select(Role).where(Role.name == input.role_name)
        role_result = await session.execute(role_stmt)
        role = role_result.scalar_one_or_none()
        if role is None:
            raise ValueError(f"角色不存在: {input.role_name}")

        # 查找关联
        ur_stmt = select(UserRole).where(
            UserRole.user_id == user.id,
            UserRole.role_id == role.id,
        )
        ur_result = await session.execute(ur_stmt)
        ur = ur_result.scalar_one_or_none()
        if ur is None:
            return UserRoleRevokeOutput(
                status=True,
                message=f"用户 '{user.username}' 未拥有角色 '{role.name}'",
            )

        # 撤销角色
        await session.delete(ur)

        # 更新 User.roles 冗余字段
        if role.name in user.roles:
            user.roles = [r for r in user.roles if r != role.name]

        session.add(user)
        await session.commit()

        # 角色变更后使权限缓存失效
        try:
            await invalidate_user_permissions(str(input.user_id))
        except Exception as e:
            logger.warning("缓存失效失败（不影响业务）: %s", e)

        logger.info("撤销角色: user=%s, role=%s", user.username, role.name)
        return UserRoleRevokeOutput(
            status=True,
            message=f"用户 '{user.username}' 已撤销角色 '{role.name}'",
        )

    raise RuntimeError("No database session available")


@app.handler("userrole.list")
async def list_user_roles(input: UserRoleListInput) -> UserRoleListOutput:
    """查询用户的角色和权限"""
    async for session in get_db_session_slave():
        user = await session.get(User, int(input.user_id))
        if user is None:
            raise ValueError(f"用户不存在: {input.user_id}")

        # 获取角色列表
        role_stmt = (
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id) # type: ignore
            .where(UserRole.user_id == user.id)
        )
        role_result = await session.exec(role_stmt)
        roles = list(role_result.all())

        # 获取权限列表（优先使用缓存）
        permissions = []
        for perm in roles:
            if perm.id is None:
                continue
            role = await get_role(RoleGetInput(role_id=perm.id))
            for p in role.permissions:
                if p not in permissions:
                    permissions.append(p)

        return UserRoleListOutput(
            user_id=str(user.id), # type: ignore
            username=user.username,
            roles=roles,
            permissions=permissions,
        )

    raise RuntimeError("No database session available")
