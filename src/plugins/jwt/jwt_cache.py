import json
import threading
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict

from pydantic import BaseModel
import jwt


@dataclass
class TokenCacheData:
    """Token 缓存数据结构"""

    token_hash: str
    user_id: str
    device_id: Optional[str] = None
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: Optional[str] = None
    expires_at: Optional[str] = None
    last_used: Optional[str] = None
    is_active: bool = True
    payload_data: Optional[Dict[str, Any]] = None
    token_type: str = "access"  # access 或 refresh

    def __post_init__(self):
        """初始化后处理，设置默认时间戳"""
        if self.created_at is None:
            self.created_at = datetime.utcnow().isoformat()
        if self.last_used is None:
            self.last_used = datetime.utcnow().isoformat()


class JWTCache:
    """JWT Token 缓存管理器

    负责 JWT Token 的创建、验证、失效和会话管理。
    使用 Redis 缓存存储 Token 哈希和用户会话索引，支持多设备登录和会话限制。
    """

    def __init__(self, config, cache):
        """初始化 JWT 缓存管理器

        Args:
            config: 配置字典，包含 security 相关配置项
            cache: 缓存实例，提供 get/set/delete/exists/keys 等方法
        """
        self.config = config

        self.lock = threading.RLock()

        self.cache = cache

        self.secret_key = self.config["security"]["secret_key"]
        self.algorithm = self.config["security"]["algorithm"]

    def _json_encode(self, obj):
        """自定义 JSON 编码器，处理 datetime 对象

        Args:
            obj: 需要序列化的对象

        Returns:
            JSON 字符串
        """

        def convert_datetime(o):
            if isinstance(o, datetime):
                return o.isoformat()
            raise TypeError(
                f"Object of type {o.__class__.__name__} is not JSON serializable"
            )

        return json.dumps(obj, default=convert_datetime)

    def _json_decode(self, s):
        """自定义 JSON 解码器

        Args:
            s: JSON 字符串

        Returns:
            解码后的 Python 对象
        """
        return json.loads(s)

    def _hash_token(self, token: str) -> str:
        """Token 哈希化（避免存储明文 Token）

        Args:
            token: 原始 JWT Token 字符串

        Returns:
            SHA256 哈希值（十六进制字符串）
        """
        return hashlib.sha256(token.encode()).hexdigest()

    def create_token(
        self,
        user_id: str,
        user_data: Dict[str, Any],
        token_type: str = "access",
        device_id: Optional[str] = None,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> str:
        """创建并缓存 JWT Token

        生成新的 JWT Token，将其哈希值和元数据存储到缓存中，
        并更新用户会话索引。如果超出会话限制，会自动清理最早的会话。

        Args:
            user_id: 用户ID
            user_data: 用户数据，将嵌入到 Token payload 中
            token_type: Token 类型（access 或 refresh）
            device_id: 设备ID，用于标识登录设备
            user_agent: 用户代理字符串，记录客户端信息
            ip_address: IP地址，记录登录来源

        Returns:
            JWT Token 字符串
        """
        with self.lock:
            # 计算过期时间
            if token_type == "access":
                expire_minutes = self.config["security"]["access_token_expire_minutes"]
                expires_delta = timedelta(minutes=expire_minutes)
            else:
                expire_days = self.config["security"]["refresh_token_expire_days"]
                expires_delta = timedelta(days=expire_days)

            expire = datetime.utcnow() + expires_delta

            # 构建 payload
            payload = {
                "sub": user_id,
                "exp": expire,
                "iat": datetime.utcnow(),
                "type": token_type,
                "data": user_data,
                "device_id": device_id,
                "jti": self._generate_jti(),  # JWT ID，唯一标识
            }

            # 生成 JWT Token
            token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
            if isinstance(token, bytes):
                token = token.decode("utf-8")

            # 创建缓存数据
            token_hash = self._hash_token(token)
            cache_data = TokenCacheData(
                token_hash=token_hash,
                user_id=user_id,
                device_id=device_id,
                user_agent=user_agent,
                ip_address=ip_address,
                expires_at=expire.isoformat(),  # 转换为字符串
                payload_data=payload,
                token_type=token_type,
            )

            # 存储到缓存
            self.cache.set(f"token:{token_hash}", asdict(cache_data))

            # 更新用户会话索引
            self._update_user_session_index(user_id, token_hash, token_type)

            # 检查用户会话数限制
            self._enforce_session_limit(user_id)

            return token

    def _generate_jti(self) -> str:
        """生成唯一的 JWT ID

        Returns:
            UUID v4 字符串，用作 Token 的唯一标识符
        """
        import uuid

        return str(uuid.uuid4())

    def _update_user_session_index(
        self, user_id: str, token_hash: str, token_type: str
    ):
        """更新用户会话索引

        维护每个用户每种 Token 类型的会话列表，限制最大数量为 100。
        当超过限制时，保留最新的 100 个会话。

        Args:
            user_id: 用户ID
            token_hash: Token 的 SHA256 哈希值
            token_type: Token 类型（access 或 refresh）
        """
        with self.lock:
            key = f"user:{user_id}:{token_type}"
            user_tokens = self.cache.get(key, [])

            # 添加新 token
            user_tokens.append(token_hash)

            # 只保留最近的一定数量的 token
            max_tokens = 100  # 每个用户每种类型最多保留100个 token
            if len(user_tokens) > max_tokens:
                user_tokens = user_tokens[-max_tokens:]

            self.cache.set(key, user_tokens)

    def _enforce_session_limit(self, user_id: str):
        """强制用户会话限制

        检查用户的 access 和 refresh token 数量，如果超过配置的最大会话数，
        则删除最早的会话以维持限制。

        Args:
            user_id: 用户ID
        """
        max_sessions = self.config["security"]["max_sessions_per_user"]

        access_key = f"user:{user_id}:access"
        refresh_key = f"user:{user_id}:refresh"

        # 检查 access token 数量
        access_tokens = self.cache.get(access_key, [])
        if len(access_tokens) > max_sessions:
            # 删除最早的 token
            tokens_to_remove = access_tokens[:-max_sessions]
            for token_hash in tokens_to_remove:
                if self.cache.exists(f"token:{token_hash}"):
                    self.cache.delete(f"token:{token_hash}")

            # 更新索引
            self.cache.set(access_key, access_tokens[-max_sessions:])

        # 检查 refresh token 数量
        refresh_tokens = self.cache.get(refresh_key, [])
        if len(refresh_tokens) > max_sessions:
            tokens_to_remove = refresh_tokens[:-max_sessions]
            for token_hash in tokens_to_remove:
                if self.cache.exists(f"token:{token_hash}"):
                    self.cache.delete(f"token:{token_hash}")

            self.cache.set(refresh_key, refresh_tokens[-max_sessions:])

    def validate_token(
        self, token: str, token_type: str = "access"
    ) -> Optional[Dict[str, Any]]:
        """验证 JWT Token

        执行多层验证：JWT 签名验证、类型检查、缓存存在性检查、
        活跃状态检查和过期时间检查。验证成功后更新最后使用时间。

        Args:
            token: JWT Token 字符串
            token_type: 期望的 Token 类型（access 或 refresh）

        Returns:
            验证成功返回包含用户信息的字典，包含以下字段：
            - user_id: 用户ID
            - device_id: 设备ID
            - payload: JWT payload 数据
            - cache_data: 缓存中的完整会话数据
            验证失败返回 None
        """
        try:
            # 解码验证 Token
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])

            # 检查 Token 类型
            print(f"payload: {payload}")
            if payload.get("type") != token_type:
                return None

            user_id = payload.get("sub")
            jti = payload.get("jti")

            if not user_id or not jti:
                return None

            token_hash = self._hash_token(token)

            # 检查缓存
            with self.lock:
                cache_data = self.cache.get(f"token:{token_hash}")
                if not cache_data:
                    return None

                # 检查 Token 是否激活
                if not cache_data.get("is_active", True):
                    return None

                # 检查是否过期
                expires_at = datetime.fromisoformat(cache_data["expires_at"])
                if datetime.utcnow() > expires_at:
                    # 标记为不活跃
                    cache_data["is_active"] = False
                    self.cache.set(f"token:{token_hash}", cache_data)
                    return None

                # 更新最后使用时间
                cache_data["last_used"] = datetime.utcnow().isoformat()
                self.cache.set(f"token:{token_hash}", cache_data)

            return {
                "user_id": user_id,
                "device_id": cache_data.get("device_id"),
                "payload": payload,
                "cache_data": cache_data,
            }

        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
        except Exception:
            return None

    def invalidate_token(self, token: str):
        """使单个 Token 失效

        通过标记缓存中的 Token 为非活跃状态来实现失效，
        而不是直接删除，以便保留审计信息。

        Args:
            token: 需要失效的 JWT Token 字符串
        """
        with self.lock:
            token_hash = self._hash_token(token)

            # 标记为不活跃
            if self.cache.exists(f"token:{token_hash}"):
                cache_data = self.cache.get(f"token:{token_hash}")
                cache_data["is_active"] = False
                self.cache.set(f"token:{token_hash}", cache_data)

    def invalidate_user_tokens(self, user_id: str, token_type: Optional[str] = None):
        """使用户的所有 Token 失效

        批量失效指定用户的所有 Token，可用于用户登出、密码修改等场景。
        可以指定失效特定类型的 Token，或者同时失效 access 和 refresh token。

        Args:
            user_id: 用户ID
            token_type: 可选，指定要失效的 Token 类型（access 或 refresh）。
                       如果不指定，则失效该用户的所有类型 Token
        """
        with self.lock:
            if token_type:
                keys = [f"user:{user_id}:{token_type}"]
            else:
                keys = [f"user:{user_id}:access", f"user:{user_id}:refresh"]

            for key in keys:
                token_hashes = self.cache.get(key, [])
                for token_hash in token_hashes:
                    # 添加到黑名单
                    # 注意：这里我们只有 token_hash，没有原始 token
                    # 所以只能标记为不活跃
                    if self.cache.exists(f"token:{token_hash}"):
                        cache_data = self.cache.get(f"token:{token_hash}")
                        cache_data["is_active"] = False
                        self.cache.set(f"token:{token_hash}", cache_data)

                # 清空用户会话索引
                self.cache.set(key, [])

    def get_user_sessions(self, user_id: str) -> List[Dict[str, Any]]:
        """获取用户的所有活跃会话

        遍历用户的所有 Token 会话，过滤出当前活跃且未过期的会话，
        返回包含设备信息、时间戳等详细信息的会话列表。

        Args:
            user_id: 用户ID

        Returns:
            活跃会话列表，每个会话包含以下字段：
            - token_type: Token 类型
            - device_id: 设备ID
            - user_agent: 用户代理
            - ip_address: IP地址
            - created_at: 创建时间
            - last_used: 最后使用时间
            - expires_at: 过期时间
        """
        with self.lock:
            sessions = []

            for token_type in ["access", "refresh"]:
                key = f"user:{user_id}:{token_type}"
                token_hashes = self.cache.get(key, [])

                for token_hash in token_hashes:
                    if self.cache.exists(f"token:{token_hash}"):
                        cache_data = self.cache.get(f"token:{token_hash}")

                        # 检查是否活跃且未过期
                        if cache_data.get("is_active", True):
                            expires_at = datetime.fromisoformat(
                                cache_data["expires_at"]
                            )
                            if datetime.utcnow() <= expires_at:
                                sessions.append(
                                    {
                                        "token_type": token_type,
                                        "device_id": cache_data.get("device_id"),
                                        "user_agent": cache_data.get("user_agent"),
                                        "ip_address": cache_data.get("ip_address"),
                                        "created_at": cache_data["created_at"],
                                        "last_used": cache_data["last_used"],
                                        "expires_at": cache_data["expires_at"],
                                    }
                                )

            return sessions

    def cleanup_expired(self):
        """清理过期数据

        扫描所有 Token 缓存，删除已过期的 Token 记录。
        建议定期调用此方法以释放缓存空间。

        Returns:
            清理的过期 Token 数量
        """
        with self.lock:
            cleaned_count = 0
            current_time = datetime.utcnow()

            # 清理过期 Token
            for token_hash in self.cache.keys("token:*"):
                expires_at = datetime.fromisoformat(self.cache.get(token_hash))
                if current_time > expires_at:
                    self.cache.delete(token_hash)
                    cleaned_count += 1

            return cleaned_count


# 全局缓存实例
_jwt_cache = None


def get_jwt_cache(config=None, cache=None) -> JWTCache:
    """获取 JWT 缓存实例（单例模式）

    确保整个应用中只有一个 JWTCache 实例，避免重复初始化和资源浪费。
    首次调用时必须提供 config 和 cache 参数。

    Args:
        config: 配置字典，仅在首次初始化时需要
        cache: 缓存实例，仅在首次初始化时需要

    Returns:
        JWTCache 单例实例

    Raises:
        ValueError: 首次调用时如果 config 或 cache 为空则抛出异常
    """
    global _jwt_cache
    if _jwt_cache is None:
        if config is None or cache is None:
            raise ValueError("参数 config 和 cache 不能为空")
        _jwt_cache = JWTCache(config, cache)
    return _jwt_cache


# Token 响应模型
class TokenResponse(BaseModel):
    """Token 响应模型

    用于登录接口返回 access token 和 refresh token
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_expires_in: int


class RefreshTokenResponse(BaseModel):
    """刷新 Token 响应模型

    用于刷新 token 接口，仅返回新的 access token
    """

    access_token: str
    token_type: str = "bearer"


# Token 数据模型
class TokenData(BaseModel):
    """Token 数据模型

    用于从 Token 中提取的用户身份信息
    """

    user_id: str
    username: Optional[str] = None
    email: Optional[str] = None
    scopes: List[str] = []
