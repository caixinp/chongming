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
    auth_service = get_auth_service()
    token = credentials.credentials
    await auth_service.logout(token)
    return {"message": "登出成功", "code": 200}


@router.post("/logout-all", summary="登出所有设备", response_model=Userlogout)
async def logout_all(current_user: TokenData = Depends(get_current_user)):
    auth_service = get_auth_service()
    await auth_service.logout_all(current_user.user_id)

    return {"message": "所有设备已登出", "code": 200}


@router.get("/sessions", summary="获取用户会话")
async def get_sessions(current_user: TokenData = Depends(get_current_user)):
    """获取用户的所有活跃会话"""
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
    """获取当前登录用户的信息"""
    user = await UserService.get_user_by_id(UUID(current_user.user_id), session)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=Detail(message="用户不存在", code=404).model_dump(),
        )

    return user
