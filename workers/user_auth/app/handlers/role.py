"""
角色管理 Handler
=================

角色的增删改查及权限分配。
"""
import logging
from typing import List

from sqlmodel import select, func

from app.bootstrap import app
from app.database_models import Role, Permission, RolePermission
from chongming_permission import require_permission
from ..listeners import get_db_session_master, get_db_session_slave

from models import (
    RoleCreateInput, RoleCreateOutput,
    RoleGetInput, RoleGetOutput,
    RoleUpdateInput, RoleUpdateOutput,
    RoleDeleteInput, RoleDeleteOutput,
    RoleListInput, RoleListOutput,
    RoleAssignPermissionInput, RoleAssignPermissionOutput,
    RoleRevokePermissionInput, RoleRevokePermissionOutput,
)

logger = logging.getLogger("chongming.worker.user_auth")


@app.handler("role.create")
async def create_role(input: RoleCreateInput) -> RoleCreateOutput:
    """创建角色"""
    if not input.name or len(input.name.strip()) == 0:
        raise ValueError("角色名称不能为空")

    name = input.name.strip()

    async for session in get_db_session_master():
        # 检查是否已存在
        stmt = select(Role).where(Role.name == name)
        result = await session.execute(stmt)
        if result.scalar_one_or_none() is not None:
            raise ValueError(f"角色 '{name}' 已存在")

        role = Role(name=name, description=input.description or "")
        session.add(role)
        await session.commit()
        await session.refresh(role)

        logger.info("创建角色: id=%s, name=%s", role.id, role.name)
        return RoleCreateOutput(
            id=role.id, # type: ignore
            name=role.name,
            description=role.description or "",
            is_system=role.is_system,
        )

    raise RuntimeError("No database session available")


@app.handler("role.get")
async def get_role(input: RoleGetInput) -> RoleGetOutput:
    """获取角色详情（包含权限列表）"""
    async for session in get_db_session_slave():
        role = await session.get(Role, input.role_id)
        if role is None:
            raise ValueError(f"角色不存在: {input.role_id}")

        # 获取角色的权限列表
        rp_stmt = (
            select(Permission)
            .join(RolePermission, RolePermission.permission_id == Permission.id) # type: ignore
            .where(RolePermission.role_id == role.id)
        )
        rp_result = await session.exec(rp_stmt)
        permissions = [
            {
                "id": p.id,
                "name": p.name,
                "resource": p.resource,
                "action": p.action,
                "description": p.description,
            }
            for p in rp_result.all()
        ]

        return RoleGetOutput(
            id=role.id, # type: ignore
            name=role.name,
            description=role.description or "",
            is_system=role.is_system,
            permissions=permissions,
        )

    raise RuntimeError("No database session available")


@app.handler("role.update")
async def update_role(input: RoleUpdateInput) -> RoleUpdateOutput:
    """更新角色信息"""
    async for session in get_db_session_master():
        role = await session.get(Role, input.role_id)
        if role is None:
            raise ValueError(f"角色不存在: {input.role_id}")

        if input.name:
            role.name = input.name
        if input.description:
            role.description = input.description

        session.add(role)
        await session.commit()
        await session.refresh(role)

        logger.info("更新角色: id=%s", role.id)
        return RoleUpdateOutput(
            id=role.id, # type: ignore
            name=role.name,
            description=role.description or "",
            is_system=role.is_system,
        )

    raise RuntimeError("No database session available")


@app.handler("role.delete")
async def delete_role(input: RoleDeleteInput) -> RoleDeleteOutput:
    """删除角色（系统角色不可删除）"""
    async for session in get_db_session_master():
        role = await session.get(Role, input.role_id)
        if role is None:
            raise ValueError(f"角色不存在: {input.role_id}")
        if role.is_system:
            raise ValueError(f"系统角色 '{role.name}' 不可删除")

        # 级联删除关联
        rp_stmt = select(RolePermission).where(RolePermission.role_id == role.id)
        rp_result = await session.execute(rp_stmt)
        for rp in rp_result.scalars().all():
            await session.delete(rp)

        await session.delete(role)
        await session.commit()

        logger.info("删除角色: id=%s, name=%s", input.role_id, role.name)
        return RoleDeleteOutput(
            status=True,
            message=f"角色 '{role.name}' 已删除",
        )

    raise RuntimeError("No database session available")


@app.handler("role.list")
async def list_roles(input: RoleListInput) -> RoleListOutput:
    """获取角色列表"""
    async for session in get_db_session_slave():
        # 总数
        count_stmt = select(func.count()).select_from(Role)
        total_result = await session.execute(count_stmt)
        total = total_result.scalar() or 0

        # 列表
        stmt = select(Role).offset(input.offset).limit(input.limit)
        result = await session.execute(stmt)
        roles = result.scalars().all()

        return RoleListOutput(
            roles=[{
                "id": r.id,
                "name": r.name,
                "description": r.description or "",
                "is_system": r.is_system,
            } for r in roles],
            total=total,
        )

    raise RuntimeError("No database session available")


@app.handler("role.assign_permission")
async def assign_permission(input: RoleAssignPermissionInput) -> RoleAssignPermissionOutput:
    """为角色分配权限"""
    async for session in get_db_session_master():
        role = await session.get(Role, input.role_id)
        if role is None:
            raise ValueError(f"角色不存在: {input.role_id}")

        perm_stmt = select(Permission).where(Permission.name == input.permission_name)
        perm_result = await session.execute(perm_stmt)
        perm = perm_result.scalar_one_or_none()
        if perm is None:
            raise ValueError(f"权限不存在: {input.permission_name}")

        # 检查是否已分配
        rp_stmt = select(RolePermission).where(
            RolePermission.role_id == role.id,
            RolePermission.permission_id == perm.id,
        )
        rp_result = await session.execute(rp_stmt)
        if rp_result.scalar_one_or_none() is not None:
            return RoleAssignPermissionOutput(
                status=True,
                message=f"权限 '{input.permission_name}' 已分配给角色 '{role.name}'",
            )

        rp = RolePermission(role_id=role.id, permission_id=perm.id) # type: ignore
        session.add(rp)
        await session.commit()

        logger.info("分配权限: role=%s, permission=%s", role.name, input.permission_name)
        return RoleAssignPermissionOutput(
            status=True,
            message=f"权限 '{input.permission_name}' 已分配给角色 '{role.name}'",
        )

    raise RuntimeError("No database session available")


@app.handler("role.revoke_permission")
async def revoke_permission(input: RoleRevokePermissionInput) -> RoleRevokePermissionOutput:
    """撤销角色的权限"""
    async for session in get_db_session_master():
        role = await session.get(Role, input.role_id)
        if role is None:
            raise ValueError(f"角色不存在: {input.role_id}")

        perm_stmt = select(Permission).where(Permission.name == input.permission_name)
        perm_result = await session.execute(perm_stmt)
        perm = perm_result.scalar_one_or_none()
        if perm is None:
            raise ValueError(f"权限不存在: {input.permission_name}")

        rp_stmt = select(RolePermission).where(
            RolePermission.role_id == role.id,
            RolePermission.permission_id == perm.id,
        )
        rp_result = await session.execute(rp_stmt)
        rp = rp_result.scalar_one_or_none()
        if rp is None:
            return RoleRevokePermissionOutput(
                status=True,
                message=f"角色 '{role.name}' 未拥有权限 '{input.permission_name}'",
            )

        await session.delete(rp)
        await session.commit()

        logger.info("撤销权限: role=%s, permission=%s", role.name, input.permission_name)
        return RoleRevokePermissionOutput(
            status=True,
            message=f"权限 '{input.permission_name}' 已从角色 '{role.name}' 撤销",
        )

    raise RuntimeError("No database session available")
