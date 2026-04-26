"""
认证服务 - 处理用户认证和 Token 管理
"""

from typing import Optional
from fastapi import Request
import bcrypt
from sqlalchemy.ext.asyncio import AsyncSession

from ..model.user import User
from ..core.config import get_config
from .user import UserService

from plugins.jwt.jwt_cache import get_jwt_cache, TokenResponse, TokenData


class AuthService:
    """认证服务"""

    def __init__(self):
        self.jwt_cache = get_jwt_cache()
        self.settings = get_config()

    async def authenticate_user(
        self, email: str, password: str, session: AsyncSession
    ) -> Optional[User]:
        """
        验证用户凭据

        通过邮箱和密码验证用户身份，使用 bcrypt 进行密码哈希比对。

        Args:
            email: 用户邮箱地址
            password: 用户明文密码
            session: 数据库异步会话对象

        Returns:
            验证成功返回 User 对象，失败返回 None
        """
        user = await UserService.get_user_by_email(email, session)
        if not user:
            return None
        if not bcrypt.checkpw(
            password.encode("utf-8"), user.hashed_password.encode("utf-8")
        ):
            return None

        return user

    async def create_tokens(
        self,
        user: User,
        request: Optional[Request] = None,
        device_id: Optional[str] = None,
    ) -> TokenResponse:
        """
        为用户创建访问和刷新令牌

        根据用户信息和请求上下文生成 JWT access token 和 refresh token，
        同时记录设备信息用于安全审计。

        Args:
            user: 已验证的用户对象
            request: FastAPI 请求对象，用于提取客户端信息（可选）
            device_id: 设备唯一标识符（可选）

        Returns:
            TokenResponse 对象，包含 access_token、refresh_token 及过期时间
        """

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
        """
        验证访问令牌

        校验 JWT access token 的有效性和完整性，提取用户身份信息。

        Args:
            token: JWT access token 字符串

        Returns:
            验证成功返回 TokenData 对象（包含 user_id、username、email），失败返回 None
        """
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
        """
        使用刷新令牌获取新的访问令牌

        验证 refresh token 的有效性，确认用户仍然存在，然后生成新的 access token。
        保持原有的设备信息以确保会话连续性。

        Args:
            refresh_token: JWT refresh token 字符串
            session: 数据库异步会话对象
            request: FastAPI 请求对象，用于提取客户端信息（可选）

        Returns:
            验证成功返回新的 access token 字符串，失败返回 None
        """
        validation = self.jwt_cache.validate_token(refresh_token, token_type="refresh")
        if not validation:
            return None

        user_id = validation["user_id"]

        # 获取用户
        user = await UserService.get_user_by_id(user_id, session)
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
        """
        用户登出 - 使令牌失效

        将指定的 token 加入黑名单，使其立即失效。

        Args:
            token: 需要失效的 JWT token 字符串
        """
        self.jwt_cache.invalidate_token(token)

    async def logout_all(self, user_id: str):
        """
        使用户的所有令牌失效

        强制注销用户的所有活跃会话，适用于密码修改或安全事件场景。

        Args:
            user_id: 用户 ID 字符串
        """
        self.jwt_cache.invalidate_user_tokens(str(user_id))

    async def get_user_sessions(self, user_id: str):
        """
        获取用户的活跃会话

        查询指定用户当前所有有效的 token 会话信息。

        Args:
            user_id: 用户 ID 字符串

        Returns:
            用户活跃会话列表
        """
        return self.jwt_cache.get_user_sessions(str(user_id))


# 全局认证服务实例
_auth_service = None


def get_auth_service() -> AuthService:
    """
    获取认证服务实例（单例模式）

    确保整个应用中只有一个 AuthService 实例，避免重复初始化。

    Returns:
        AuthService 单例实例
    """
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service
