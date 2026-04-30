from typing import List, Set, Union

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from ..service.auth import get_auth_service
from ..service.permission import PermissionService
from ..service.user import UserService
from ..core.database import get_session

from plugins.jwt.jwt_cache import TokenData


access_scheme = HTTPBearer(scheme_name="AccessToken")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(access_scheme),
) -> TokenData:
    """
    获取当前用户依赖项

    验证访问令牌并返回用户信息

    Args:
        credentials: HTTP授权凭证，包含Bearer token

    Returns:
        TokenData: 验证通过后的用户令牌数据

    Raises:
        HTTPException: 当访问令牌无效时抛出401未授权异常
    """
    auth_service = get_auth_service()

    # 提取并验证访问令牌
    token = credentials.credentials
    token_data = await auth_service.validate_access_token(token)

    # 令牌验证失败时抛出未授权异常
    if token_data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的访问令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token_data


class PermissionChecker:
    """
    权限校验依赖类

    用于校验当前用户是否拥有访问特定接口所需的权限。
    支持以下特性：
    - 超级用户自动拥有所有权限（需要额外注入 RequireSuperuser 或由业务层检查）
    - 支持单权限校验
    - 支持多权限校验（all模式：需要拥有全部权限；any模式：拥有任一权限即可）

    使用示例:
        ```python
        # 单权限校验
        @router.get("/orders")
        async def list_orders(
            _: bool = Depends(PermissionChecker("sales_order:read")),
        ):
            ...

        # 多权限 all 模式（需要同时拥有创建和审核权限）
        @router.post("/outbounds")
        async def create_outbound(
            _: bool = Depends(PermissionChecker(
                ["sales_outbound:create", "sales_outbound:approve"],
                require_all=True
            )),
        ):
            ...

        # 多权限 any 模式（拥有任一权限即可）
        @router.get("/reports/sales")
        async def view_sales_report(
            _: bool = Depends(PermissionChecker(
                ["report_sales:view", "sales_order:read"],
                require_all=False
            )),
        ):
            ...
        ```
    """

    def __init__(
        self,
        permissions: Union[str, List[str]],
        require_all: bool = True,
        require_superuser: bool = False,
    ):
        """
        初始化权限校验器

        Args:
            permissions: 所需的权限标识符，可以是单个字符串或字符串列表
                        - 字符串格式：resource:action（如 "sales_order:read"）
                        - 列表格式：["perm1:action1", "perm2:action2"]
            require_all: 多权限校验模式
                        - True: 用户必须拥有所有指定权限
                        - False: 用户只需拥有任一指定权限
            require_superuser: 是否要求超级用户身份（超级用户自动拥有所有权限）
        """
        self.permissions = [permissions] if isinstance(permissions, str) else permissions
        self.require_all = require_all
        self.require_superuser = require_superuser

    async def __call__(
        self,
        current_user: TokenData = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
    ) -> bool:
        """
        执行权限校验

        Args:
            current_user: 当前登录用户的Token数据
            session: 数据库会话对象

        Returns:
            bool: 权限校验通过返回True

        Raises:
            HTTPException: 权限不足时抛出403禁止访问异常
        """
        from uuid import UUID

        # 1. 如果配置了超级用户要求，先检查超级用户
        if self.require_superuser:
            user = await UserService.get_user_by_id(UUID(current_user.user_id), session)
            if user and user.is_superuser:
                return True
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "message": "仅超级管理员可执行此操作",
                    "code": status.HTTP_403_FORBIDDEN,
                },
            )

        # 2. 如果没有需要校验的权限，直接放行
        if not self.permissions:
            return True

        # 3. 获取用户的权限列表（通过角色链汇总）
        user_permissions = await PermissionService.get_permissions_by_user(
            session=session,
            user_id=UUID(current_user.user_id),
        )

        # 构建用户拥有的权限名称集合
        user_perm_names: Set[str] = {perm.name for perm in user_permissions}

        # 4. 权限匹配检查
        if self.require_all:
            # all模式：必须拥有所有指定权限
            missing = [perm for perm in self.permissions if perm not in user_perm_names]
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "message": "权限不足",
                        "code": status.HTTP_403_FORBIDDEN,
                        "missing_permissions": missing,
                    },
                )
        else:
            # any模式：拥有任一权限即可
            has_any = any(perm in user_perm_names for perm in self.permissions)
            if not has_any:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "message": "权限不足",
                        "code": status.HTTP_403_FORBIDDEN,
                        "required_permissions": self.permissions,
                    },
                )

        return True


class RequireSuperuser:
    """
    超级用户校验依赖

    要求当前用户必须是超级用户（is_superuser=True），否则返回403。
    通常用于系统管理类接口。

    使用示例:
        ```python
        @router.delete("/users/{user_id}")
        async def delete_user(
            _: bool = Depends(RequireSuperuser()),
        ):
            ...
        ```
    """

    async def __call__(
        self,
        current_user: TokenData = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
    ) -> bool:
        from uuid import UUID

        user = await UserService.get_user_by_id(UUID(current_user.user_id), session)
        if not user or not user.is_superuser:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "message": "仅超级管理员可执行此操作",
                    "code": status.HTTP_403_FORBIDDEN,
                },
            )
        return True
