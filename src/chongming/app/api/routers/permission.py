from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_session
from ...model.permission import Permission, PermissionCreate, PermissionUpdate
from ...model.http_error import HTTPError, Detail
from ...service.permission import PermissionService
from ..deps import get_current_user, PermissionChecker
from ...constant.permission import PermissionMgtConstant, RoleConstant

from plugins.jwt.jwt_cache import TokenData


router = APIRouter(tags=["permission"])


@router.post(
    "",
    response_model=Permission,
    responses={
        400: {"model": HTTPError, "description": "权限名称已存在"},
    },
    summary="创建权限",
)
async def create_permission(
    permission_data: PermissionCreate,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(PermissionChecker(PermissionMgtConstant.PERMISSION_CREATE, require_superuser=True)),
    __: TokenData = Depends(get_current_user),
):
    """
    创建权限

    创建新的权限项，权限名称格式应为"资源:操作"，如"user:create"。

    Args:
        permission_data: 权限创建数据，包含名称、资源、操作和描述等信息
        session: 数据库会话对象
        current_user: 当前登录用户

    Returns:
        Permission: 创建成功的权限对象

    Raises:
        HTTPException: 当权限名称已存在时抛出400错误
    """
    existing = await PermissionService.get_permission_by_name(
        session, permission_data.name
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=Detail(
                message="权限名称已存在", code=status.HTTP_400_BAD_REQUEST
            ).model_dump(),
        )

    permission = await PermissionService.create_permission(
        session=session,
        name=permission_data.name,
        resource=permission_data.resource,
        action=permission_data.action,
        description=permission_data.description,
    )
    return permission


@router.get(
    "",
    response_model=list[Permission],
    summary="获取权限列表",
)
async def list_permissions(
    skip: int = 0,
    limit: int = 100,
    resource: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(PermissionChecker([PermissionMgtConstant.PERMISSION_READ, RoleConstant.ROLE_READ], require_all=False)),
    __: TokenData = Depends(get_current_user),
):
    """
    获取权限列表

    返回系统中的所有权限项，支持分页和按资源名称筛选。

    Args:
        skip: 跳过的记录数，用于分页
        limit: 返回的最大记录数，用于分页
        resource: 资源名称筛选条件，可选
        session: 数据库会话对象
        current_user: 当前登录用户

    Returns:
        list[Permission]: 权限对象列表
    """
    permissions = await PermissionService.list_permissions(
        session=session,
        skip=skip,
        limit=limit,
        resource=resource,
    )
    return list(permissions)


@router.get(
    "/{permission_id}",
    response_model=Permission,
    responses={
        404: {"model": HTTPError, "description": "权限不存在"},
    },
    summary="获取权限详情",
)
async def get_permission(
    permission_id: int,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(PermissionChecker(PermissionMgtConstant.PERMISSION_READ)),
    __: TokenData = Depends(get_current_user),
):
    """
    获取权限详情

    根据权限ID获取指定权限的详细信息。

    Args:
        permission_id: 权限ID
        session: 数据库会话对象
        current_user: 当前登录用户

    Returns:
        Permission: 权限对象

    Raises:
        HTTPException: 当权限不存在时抛出404错误
    """
    permission = await PermissionService.get_permission_by_id(session, permission_id)
    if not permission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=Detail(
                message="权限不存在", code=status.HTTP_404_NOT_FOUND
            ).model_dump(),
        )
    return permission


@router.put(
    "/{permission_id}",
    response_model=Permission,
    responses={
        404: {"model": HTTPError, "description": "权限不存在"},
    },
    summary="更新权限",
)
async def update_permission(
    permission_id: int,
    permission_update: PermissionUpdate,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(PermissionChecker(PermissionMgtConstant.PERMISSION_UPDATE, require_superuser=True)),
    __: TokenData = Depends(get_current_user),
):
    """
    更新权限信息

    更新指定权限的名称、描述、资源或操作等信息。

    Args:
        permission_id: 权限ID
        permission_update: 权限更新数据，所有字段可选
        session: 数据库会话对象
        current_user: 当前登录用户

    Returns:
        Permission: 更新后的权限对象

    Raises:
        HTTPException: 当权限不存在时抛出404错误
    """
    permission = await PermissionService.update_permission(
        session=session,
        permission_id=permission_id,
        permission_update=permission_update,
    )
    return permission


@router.delete(
    "/{permission_id}",
    responses={
        400: {"model": HTTPError, "description": "权限已被角色使用，无法删除"},
        404: {"model": HTTPError, "description": "权限不存在"},
    },
    summary="删除权限",
)
async def delete_permission(
    permission_id: int,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(PermissionChecker(PermissionMgtConstant.PERMISSION_DELETE, require_superuser=True)),
    __: TokenData = Depends(get_current_user),
):
    """
    删除权限

    删除指定权限。如果权限已被分配给角色，则无法删除。

    Args:
        permission_id: 权限ID
        session: 数据库会话对象
        current_user: 当前登录用户

    Returns:
        dict: 删除成功响应消息

    Raises:
        HTTPException: 当权限被角色使用时抛出400错误，权限不存在时抛出404错误
    """
    await PermissionService.delete_permission(session=session, permission_id=permission_id)
    return {"message": "权限删除成功", "code": 200}


@router.post(
    "/{permission_id}/assign-to-role/{role_id}",
    summary="将权限分配给角色",
    responses={
        400: {"model": HTTPError, "description": "权限已分配给角色"},
        404: {"model": HTTPError, "description": "角色或权限不存在"},
    },
)
async def assign_permission_to_role(
    permission_id: int,
    role_id: int,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(PermissionChecker(PermissionMgtConstant.PERMISSION_BIND, require_superuser=True)),
    __: TokenData = Depends(get_current_user),
):
    """
    将权限分配给角色

    将指定权限分配给指定角色。

    Args:
        permission_id: 权限ID
        role_id: 角色ID
        session: 数据库会话对象
        current_user: 当前登录用户

    Returns:
        dict: 分配成功响应消息

    Raises:
        HTTPException: 当权限已分配给角色或角色/权限不存在时抛出错误
    """
    await PermissionService.assign_permission_to_role(
        session=session, role_id=role_id, permission_id=permission_id
    )
    return {"message": "权限分配成功", "code": 200}


@router.post(
    "/{permission_id}/unbind-from-role/{role_id}",
    summary="从角色解除权限绑定",
    responses={
        404: {"model": HTTPError, "description": "角色不存在"},
    },
)
async def unbind_permission_from_role(
    permission_id: int,
    role_id: int,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(PermissionChecker(PermissionMgtConstant.PERMISSION_UNBIND, require_superuser=True)),
    __: TokenData = Depends(get_current_user),
):
    """
    从角色解除权限绑定

    将指定权限从指定角色中移除。

    Args:
        permission_id: 权限ID
        role_id: 角色ID
        session: 数据库会话对象
        current_user: 当前登录用户

    Returns:
        dict: 解绑成功响应消息

    Raises:
        HTTPException: 当角色不存在时抛出404错误
    """
    await PermissionService.unbind_permission_from_role(
        session=session, role_id=role_id, permission_id=permission_id
    )
    return {"message": "权限解除绑定成功", "code": 200}


@router.post(
    "/{permission_id}/assign-to-user/{user_id}",
    summary="将权限分配给用户",
    responses={
        404: {"model": HTTPError, "description": "用户或权限不存在"},
    },
)
async def assign_permission_to_user(
    permission_id: int,
    user_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(PermissionChecker(PermissionMgtConstant.PERMISSION_BIND, require_superuser=True)),
    __: TokenData = Depends(get_current_user),
):
    """
    将权限分配给用户

    将指定权限分配给指定用户。如果用户没有专属角色，则会自动创建一个专属角色。

    Args:
        permission_id: 权限ID
        user_id: 用户UUID
        session: 数据库会话对象
        current_user: 当前登录用户

    Returns:
        dict: 分配成功响应消息

    Raises:
        HTTPException: 当用户或权限不存在时抛出404错误
    """
    await PermissionService.assign_permission_to_user(
        session=session, user_id=user_id, permission_id=permission_id
    )
    return {"message": "权限分配成功", "code": 200}


@router.post(
    "/{permission_id}/unbind-from-user/{user_id}",
    summary="从用户解除权限绑定",
    responses={
        404: {"model": HTTPError, "description": "用户或权限不存在"},
    },
)
async def unbind_permission_from_user(
    permission_id: int,
    user_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(PermissionChecker(PermissionMgtConstant.PERMISSION_UNBIND, require_superuser=True)),
    __: TokenData = Depends(get_current_user),
):
    """
    从用户解除权限绑定

    将指定权限从指定用户中移除。

    Args:
        permission_id: 权限ID
        user_id: 用户UUID
        session: 数据库会话对象
        current_user: 当前登录用户

    Returns:
        dict: 解绑成功响应消息

    Raises:
        HTTPException: 当用户或角色不存在时抛出404错误
    """
    await PermissionService.unbind_permission_from_user(
        session=session, user_id=user_id, permission_id=permission_id
    )
    return {"message": "权限解除绑定成功", "code": 200}
