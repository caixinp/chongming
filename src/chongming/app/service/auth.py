"""
认证服务 - 处理用户认证和 Token 管理
"""

from typing import Optional
from fastapi import Request
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from ..model.user import User
from .user import UserService
from ..core.jwt_cache import get_jwt_cache, TokenResponse, TokenData
from ..core.config import get_config


class AuthService:
    """认证服务"""

    def __init__(self):
        self.jwt_cache = get_jwt_cache()
        self.settings = get_config()
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    async def authenticate_user(
        self, email: str, password: str, session: AsyncSession
    ) -> Optional[User]:
        """验证用户凭据"""
        user = await UserService.get_user_by_email(email, session)
        if not user:
            return None
        if not self.pwd_context.verify(password, user.hashed_password):
            return None

        return user

    async def create_tokens(
        self,
        user: User,
        request: Optional[Request] = None,
        device_id: Optional[str] = None,
    ) -> TokenResponse:
        """为用户创建访问和刷新令牌"""

        # 获取用户数据
        user_data = {
            "username": user.username,
            "email": user.email,
            "is_superuser": user.is_superuser,
        }

        # 获取设备信息
        user_agent = None
        ip_address = None
        if request:
            user_agent = request.headers.get("user-agent")
            ip_address = request.client.host if request.client else None

        # 创建访问令牌
        access_token = self.jwt_cache.create_token(
            user_id=str(user.id),
            user_data=user_data,
            token_type="access",
            device_id=device_id,
            user_agent=user_agent,
            ip_address=ip_address,
        )

        # 创建刷新令牌
        refresh_token = self.jwt_cache.create_token(
            user_id=str(user.id),
            user_data=user_data,
            token_type="refresh",
            device_id=device_id,
            user_agent=user_agent,
            ip_address=ip_address,
        )

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self.settings["security"]["access_token_expire_minutes"] * 60,
            refresh_expires_in=getattr(self.settings, "refresh_token_expire_days", 7)
            * 24
            * 60
            * 60,
        )

    async def validate_access_token(self, token: str) -> Optional[TokenData]:
        """验证访问令牌"""
        validation = self.jwt_cache.validate_token(token, token_type="access")
        if not validation:
            return None

        return TokenData(
            user_id=validation["user_id"],
            username=validation["payload"]["data"].get("username"),
            email=validation["payload"]["data"].get("email"),
            scopes=[],  # 可以根据需要添加权限范围
        )

    async def refresh_access_token(
        self,
        refresh_token: str,
        session: AsyncSession,
        request: Optional[Request] = None,
    ) -> Optional[str]:
        """使用刷新令牌获取新的访问令牌"""
        validation = self.jwt_cache.validate_token(refresh_token, token_type="access")
        if not validation:
            return None

        user_id = validation["user_id"]

        # 获取用户
        user = await UserService.get_user_by_id(int(user_id), session)
        if not user:
            return None

        # 创建新的访问令牌
        user_data = {
            "username": user.username,
            "email": user.email,
            "is_superuser": user.is_superuser,
        }

        device_id = validation.get("device_id")
        user_agent = None
        ip_address = None
        if request:
            user_agent = request.headers.get("user-agent")
            ip_address = request.client.host if request.client else None

        new_access_token = self.jwt_cache.create_token(
            user_id=user_id,
            user_data=user_data,
            token_type="access",
            device_id=device_id,
            user_agent=user_agent,
            ip_address=ip_address,
        )

        return new_access_token

    async def logout(self, token: str):
        """用户登出 - 使令牌失效"""
        self.jwt_cache.invalidate_token(token)

    async def logout_all(self, user_id: str):
        """使用户的所有令牌失效"""
        self.jwt_cache.invalidate_user_tokens(str(user_id))

    async def get_user_sessions(self, user_id: str):
        """获取用户的活跃会话"""
        return self.jwt_cache.get_user_sessions(str(user_id))


# 全局认证服务实例
_auth_service = None


def get_auth_service() -> AuthService:
    """获取认证服务实例（单例模式）"""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service
