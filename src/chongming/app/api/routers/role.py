from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_session
from ...model.role import Role, RoleUpdate
from ...model.http_error import HTTPError, Detail
from ...service.role import RoleService
from ...service.permission import PermissionService
from ..deps import get_current_user, PermissionChecker
from ...constant.permission import RoleConstant

from plugins.jwt.jwt_cache import TokenData


router = APIRouter(tags=["role"])


@router.post(
    "",
    response_model=Role,
    responses={
        400: {"model": HTTPError, "description": "角色名称已存在"},
    },
    summary="创建角色",
)
async def create_role(
    name: str,
    description: Optional[str] = None,
    is_only_user: bool = False,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(PermissionChecker(RoleConstant.ROLE_CREATE, require_superuser=True)),
    __: TokenData = Depends(get_current_user),
):
    """
    创建角色

    创建新的角色，如 admin、manager、operator 等。

    Args:
        name: 角色名称
        description: 角色描述，可选
        is_only_user: 是否仅用于单个用户，默认为False
        session: 数据库会话对象
        current_user: 当前登录用户

    Returns:
        Role: 创建成功的角色对象

    Raises:
        HTTPException: 当角色名称已存在时抛出400错误
    """
    existing = await RoleService.get_role_by_name(session, name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=Detail(
                message="角色名称已存在", code=status.HTTP_400_BAD_REQUEST
            ).model_dump(),
        )

    role = await RoleService.create_role(
        session=session,
        name=name,
        description=description,
        is_only_user=is_only_user,
    )
    return role


@router.get(
    "",
    response_model=list[Role],
    summary="获取角色列表",
)
async def list_roles(
    skip: int = 0,
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(PermissionChecker(RoleConstant.ROLE_READ)),
    __: TokenData = Depends(get_current_user),
):
    """
    获取角色列表

    返回系统中的所有角色，支持分页。

    Args:
        skip: 跳过的记录数，用于分页
        limit: 返回的最大记录数，用于分页
        session: 数据库会话对象
        current_user: 当前登录用户

    Returns:
        list[Role]: 角色对象列表
    """
    roles = await RoleService.list_roles(
        session=session,
        skip=skip,
        limit=limit,
    )
    return list(roles)


@router.get(
    "/{role_id}",
    response_model=Role,
    responses={
        404: {"model": HTTPError, "description": "角色不存在"},
    },
    summary="获取角色详情",
)
async def get_role(
    role_id: int,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(PermissionChecker(RoleConstant.ROLE_READ)),
    __: TokenData = Depends(get_current_user),
):
    """
    获取角色详情

    根据角色ID获取指定角色的详细信息。

    Args:
        role_id: 角色ID
        session: 数据库会话对象
        current_user: 当前登录用户

    Returns:
        Role: 角色对象

    Raises:
        HTTPException: 当角色不存在时抛出404错误
    """
    role = await RoleService.get_role_by_id(session, role_id)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=Detail(
                message="角色不存在", code=status.HTTP_404_NOT_FOUND
            ).model_dump(),
        )
    return role


@router.put(
    "/{role_id}",
    response_model=Role,
    responses={
        404: {"model": HTTPError, "description": "角色不存在"},
    },
    summary="更新角色",
)
async def update_role(
    role_id: int,
    role_update: RoleUpdate,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(PermissionChecker(RoleConstant.ROLE_UPDATE, require_superuser=True)),
    __: TokenData = Depends(get_current_user),
):
    """
    更新角色信息

    更新指定角色的名称或描述等信息。

    Args:
        role_id: 角色ID
        role_update: 角色更新数据，所有字段可选
        session: 数据库会话对象
        current_user: 当前登录用户

    Returns:
        Role: 更新后的角色对象

    Raises:
        HTTPException: 当角色不存在时抛出404错误
    """
    role = await RoleService.update_role(
        session=session,
        role_id=role_id,
        role_update=role_update,
    )
    return role


@router.delete(
    "/{role_id}",
    responses={
        400: {"model": HTTPError, "description": "角色不为空，无法删除"},
        404: {"model": HTTPError, "description": "角色不存在"},
    },
    summary="删除角色",
)
async def delete_role(
    role_id: int,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(PermissionChecker(RoleConstant.ROLE_DELETE, require_superuser=True)),
    __: TokenData = Depends(get_current_user),
):
    """
    删除角色

    删除指定角色。如果角色已被分配给用户，则无法删除。

    Args:
        role_id: 角色ID
        session: 数据库会话对象
        current_user: 当前登录用户

    Returns:
        dict: 删除成功响应消息

    Raises:
        HTTPException: 当角色被用户使用时抛出400错误，角色不存在时抛出404错误
    """
    await RoleService.delete_role(
        role_id=role_id,
        session=session,
    )
    return {"message": "角色删除成功", "code": 200}


@router.post(
    "/{role_id}/assign-to-user/{user_id}",
    summary="将角色分配给用户",
    responses={
        404: {"model": HTTPError, "description": "角色或用户不存在"},
    },
)
async def assign_role_to_user(
    role_id: int,
    user_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(PermissionChecker(RoleConstant.ROLE_BIND, require_superuser=True)),
    __: TokenData = Depends(get_current_user),
):
    """
    将角色分配给用户

    将指定角色分配给指定用户。

    Args:
        role_id: 角色ID
        user_id: 用户UUID
        session: 数据库会话对象
        current_user: 当前登录用户

    Returns:
        dict: 分配成功响应消息

    Raises:
        HTTPException: 当角色或用户不存在时抛出404错误
    """
    # 检查角色是否存在
    role = await RoleService.get_role_by_id(session, role_id)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=Detail(
                message="角色不存在", code=status.HTTP_404_NOT_FOUND
            ).model_dump(),
        )

    # 检查用户是否存在
    from ...service.user import UserService
    user = await UserService.get_user_by_id(user_id, session)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=Detail(
                message="用户不存在", code=status.HTTP_404_NOT_FOUND
            ).model_dump(),
        )

    await RoleService.assign_role_to_user(
        session=session,
        user_id=user_id,
        role_id=role_id,
    )
    return {"message": "角色分配成功", "code": 200}


@router.post(
    "/{role_id}/unbind-from-user/{user_id}",
    summary="从用户解除角色绑定",
    responses={
        404: {"model": HTTPError, "description": "用户不存在"},
    },
)
async def unbind_role_from_user(
    role_id: int,
    user_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(PermissionChecker(RoleConstant.ROLE_UNBIND, require_superuser=True)),
    __: TokenData = Depends(get_current_user),
):
    """
    从用户解除角色绑定

    将指定角色从指定用户中移除。

    Args:
        role_id: 角色ID
        user_id: 用户UUID
        session: 数据库会话对象
        current_user: 当前登录用户

    Returns:
        dict: 解绑成功响应消息

    Raises:
        HTTPException: 当用户不存在时抛出404错误
    """
    await RoleService.unbind_role_from_user(
        session=session,
        user_id=user_id,
        role_id=role_id,
    )
    return {"message": "角色解除绑定成功", "code": 200}


@router.get(
    "/{role_id}/permissions",
    response_model=list,
    summary="获取角色的权限列表",
)
async def get_role_permissions(
    role_id: int,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(PermissionChecker(RoleConstant.ROLE_READ)),
    __: TokenData = Depends(get_current_user),
):
    """
    获取指定角色的所有权限

    Args:
        role_id: 角色ID
        session: 数据库会话对象
        current_user: 当前登录用户

    Returns:
        list: 权限对象列表
    """
    permissions = await PermissionService.get_permissions_by_role(
        session=session,
        role_id=role_id,
    )
    return list(permissions)

