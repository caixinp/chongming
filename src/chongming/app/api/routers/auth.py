from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_session
from ...core.security import verify_password
from ...service.user import UserService
from ...service.auth import get_auth_service
from ...model.user import UserCreate, UserRead, UserLogin, Userlogout, UserSession
from ...model.http_error import HTTPError, Detail
from ..deps import get_current_user

from plugins.jwt.jwt_cache import TokenData, TokenResponse, RefreshTokenResponse


router = APIRouter(tags=["authentication"])

access_scheme = HTTPBearer(scheme_name="AccessToken")
refresh_scheme = HTTPBearer(scheme_name="RefreshToken")


@router.post(
    "/register",
    response_model=UserRead,
    responses={400: {"model": HTTPError, "description": "邮箱已被注册"}},
)
async def register(
    user_data: UserCreate,
    session: AsyncSession = Depends(get_session),
):
    """
    用户注册接口

    创建新用户账户，检查邮箱是否已被注册，如果邮箱未被注册则创建新用户。

    Args:
        user_data: 用户注册数据，包含邮箱、密码、用户名和全名等信息
        session: 数据库会话对象，用于执行数据库操作

    Returns:
        UserRead: 创建成功的用户信息，包含用户ID、邮箱、用户名等字段

    Raises:
        HTTPException: 当邮箱已被注册时抛出400错误
    """
    existing = await UserService.get_user_by_email(user_data.email, session)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=Detail(
                message="邮箱已被注册", code=status.HTTP_400_BAD_REQUEST
            ).model_dump(),
        )

    user = await UserService.create_user(
        session=session,
        email=user_data.email,
        password=user_data.password,
        username=user_data.username,
        full_name=user_data.full_name,
    )
    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={
        400: {"model": HTTPError, "description": "邮箱不存在"},
        401: {"model": HTTPError, "description": "密码错误"},
        402: {"model": HTTPError, "description": "用户被禁用"},
    },
)
async def login(
    user_data: UserLogin,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """
    用户登录接口

    验证用户凭据并生成访问令牌和刷新令牌。依次检查邮箱是否存在、密码是否正确、用户是否被禁用。

    Args:
        user_data: 用户登录数据，包含邮箱和密码
        request: FastAPI请求对象，用于获取客户端信息
        session: 数据库会话对象，用于查询用户信息

    Returns:
        TokenResponse: 包含访问令牌(access_token)、刷新令牌(refresh_token)和令牌类型(token_type)的响应对象

    Raises:
        HTTPException:
            - 400错误：当邮箱不存在时
            - 401错误：当密码错误时
            - 402错误：当用户账户被禁用时
    """
    user = await UserService.get_user_by_email(user_data.email, session)
    if not user:
        raise HTTPException(
            status_code=400, detail=Detail(message="邮箱不存在", code=400).model_dump()
        )
    if not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(
            status_code=400, detail=Detail(message="密码错误", code=401).model_dump()
        )
    if not user.is_active:
        raise HTTPException(
            status_code=400, detail=Detail(message="用户被禁用", code=402).model_dump()
        )
    auth_service = get_auth_service()
    return await auth_service.create_tokens(user, request, device_id=None)


@router.post(
    "/refresh",
    response_model=RefreshTokenResponse,
    responses={
        401: {"model": HTTPError, "description": "无效的刷新令牌"},
    },
    summary="刷新访问令牌",
)
async def refresh_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(refresh_scheme),
    session: AsyncSession = Depends(get_session),
):
    """
    刷新访问令牌接口

    使用有效的刷新令牌获取新的访问令牌。验证刷新令牌的有效性，如果有效则生成新的访问令牌。

    Args:
        request: FastAPI请求对象，用于获取客户端信息
        credentials: HTTP认证凭证，从请求头中提取的刷新令牌
        session: 数据库会话对象，用于验证令牌状态

    Returns:
        RefreshTokenResponse: 包含新的访问令牌(access_token)和令牌类型(token_type)的响应对象

    Raises:
        HTTPException: 当刷新令牌无效或已过期时抛出401错误
    """
    auth_service = get_auth_service()

    refresh_token = credentials.credentials
    new_access_token = await auth_service.refresh_access_token(
        refresh_token, session, request
    )
    if not new_access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=Detail(message="无效的刷新令牌", code=401).model_dump(),
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"access_token": new_access_token, "token_type": "bearer"}


@router.post("/logout", response_model=Userlogout)
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(access_scheme),
):
    """
    用户登出接口

    使当前的访问令牌失效，实现单设备登出功能。

    Args:
        credentials: HTTP认证凭证，从请求头中提取的访问令牌

    Returns:
        Userlogout: 登出成功响应，包含成功消息和状态码200
    """
    auth_service = get_auth_service()
    token = credentials.credentials
    await auth_service.logout(token)
    return {"message": "登出成功", "code": 200}


@router.post("/logout-all", summary="登出所有设备", response_model=Userlogout)
async def logout_all(current_user: TokenData = Depends(get_current_user)):
    """
    登出所有设备接口

    使指定用户的所有活跃会话令牌失效，实现多设备同时登出功能。

    Args:
        current_user: 当前登录用户的令牌数据，包含用户ID等信息

    Returns:
        Userlogout: 登出成功响应，包含成功消息和状态码200
    """
    auth_service = get_auth_service()
    await auth_service.logout_all(current_user.user_id)

    return {"message": "所有设备已登出", "code": 200}


@router.get("/sessions", summary="获取用户会话")
async def get_sessions(current_user: TokenData = Depends(get_current_user)):
    """
    获取用户会话列表接口

    查询并返回指定用户的所有活跃会话信息，包括每个会话的设备信息和创建时间等。

    Args:
        current_user: 当前登录用户的令牌数据，包含用户ID等信息

    Returns:
        UserSession: 用户会话信息对象，包含用户ID、会话列表和会话总数
    """
    auth_service = get_auth_service()
    sessions = await auth_service.get_user_sessions(current_user.user_id)

    return UserSession(
        user_id=current_user.user_id, sessions=sessions, count=len(sessions)
    )


@router.get(
    "/me",
    response_model=UserRead,
    summary="获取当前用户信息",
    responses={404: {"model": HTTPError, "description": "用户不存在"}},
)
async def get_current_user_info(
    session: AsyncSession = Depends(get_session),
    current_user: TokenData = Depends(get_current_user),
):
    """
    获取当前用户信息接口

    根据当前登录用户的令牌信息，从数据库中查询并返回完整的用户资料。

    Args:
        session: 数据库会话对象，用于查询用户信息
        current_user: 当前登录用户的令牌数据，包含用户ID等信息

    Returns:
        UserRead: 用户详细信息，包含用户ID、邮箱、用户名、全名、激活状态等字段

    Raises:
        HTTPException: 当用户不存在时抛出404错误
    """
    user = await UserService.get_user_by_id(UUID(current_user.user_id), session)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=Detail(message="用户不存在", code=404).model_dump(),
        )

    return user
