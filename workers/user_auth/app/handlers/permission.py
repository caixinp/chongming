"""
权限管理 Handler
=================

权限的增删改查。
"""
import logging

from sqlmodel import select, func

from app.bootstrap import app
from app.database_models import Permission
from ..listeners import get_db_session_master, get_db_session_slave

from models import (
    PermissionCreateInput, PermissionCreateOutput,
    PermissionListInput, PermissionListOutput,
    PermissionDeleteInput, PermissionDeleteOutput,
)

logger = logging.getLogger("chongming.worker.user_auth")


@app.handler("permission.create")
async def create_permission(input: PermissionCreateInput) -> PermissionCreateOutput:
    """创建权限"""
    if not input.name or len(input.name.strip()) == 0:
        raise ValueError("权限名称不能为空")

    name = input.name.strip()

    async for session in get_db_session_master():
        stmt = select(Permission).where(Permission.name == name)
        result = await session.execute(stmt)
        if result.scalar_one_or_none() is not None:
            raise ValueError(f"权限 '{name}' 已存在")

        perm = Permission(
            name=name,
            resource=input.resource,
            action=input.action,
            description=input.description or "",
        )
        session.add(perm)
        await session.commit()
        await session.refresh(perm)

        logger.info("创建权限: id=%s, name=%s", perm.id, perm.name)
        return PermissionCreateOutput(
            id=perm.id, # type: ignore
            name=perm.name,
            resource=perm.resource,
            action=perm.action,
            description=perm.description or "",
        )

    raise RuntimeError("No database session available")


@app.handler("permission.list")
async def list_permissions(input: PermissionListInput) -> PermissionListOutput:
    """获取权限列表"""
    async for session in get_db_session_slave():
        # 构建查询
        base_stmt = select(Permission)
        count_base = select(func.count()).select_from(Permission)

        if input.resource:
            resource_filter = Permission.resource == input.resource
            base_stmt = base_stmt.where(resource_filter)
            count_base = count_base.where(resource_filter)

        # 总数
        total_result = await session.exec(count_base)
        total = total_result.one_or_none() or 0

        # 列表
        stmt = base_stmt.offset(input.offset).limit(input.limit)
        result = await session.execute(stmt)
        permissions = result.scalars().all()

        return PermissionListOutput(
            permissions=[{
                "id": p.id,
                "name": p.name,
                "resource": p.resource,
                "action": p.action,
                "description": p.description or "",
            } for p in permissions],
            total=total,
        )

    raise RuntimeError("No database session available")


@app.handler("permission.delete")
async def delete_permission(input: PermissionDeleteInput) -> PermissionDeleteOutput:
    """删除权限"""
    async for session in get_db_session_master():
        perm = await session.get(Permission, input.permission_id)
        if perm is None:
            raise ValueError(f"权限不存在: {input.permission_id}")

        # 级联删除角色权限关联（外键 ondelete=CASCADE 自动处理）
        await session.delete(perm)
        await session.commit()

        logger.info("删除权限: id=%s, name=%s", input.permission_id, perm.name)
        return PermissionDeleteOutput(
            status=True,
            message=f"权限 '{perm.name}' 已删除",
        )

    raise RuntimeError("No database session available")
