import jwt
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, TypedDict
from sqlitedict import SqliteDict
from pydantic import BaseModel
from dataclasses import dataclass, asdict

# from pydantic import BaseModel
import hashlib
import threading
from pathlib import Path

from .config import get_config


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
        if self.created_at is None:
            self.created_at = datetime.utcnow().isoformat()
        if self.last_used is None:
            self.last_used = datetime.utcnow().isoformat()


class JWTCache:
    """JWT Token 缓存管理器"""

    def __init__(self, db_path: Optional[str] = None):
        self.config = get_config()

        if db_path is None:
            db_path = self.config["security"]["jwt_cache_db_path"]

        db_file_path = Path(db_path)
        db_file_path.mkdir(parents=True, exist_ok=True)

        self.lock = threading.RLock()

        # 主 Token 缓存
        self.token_db = SqliteDict(
            rf"{db_path}/tokens.cache",
            tablename="tokens",
            autocommit=True,
            encode=self._json_encode,
            decode=self._json_decode,
            journal_mode="WAL",
        )

        # 黑名单缓存
        self.blacklist_db = SqliteDict(
            rf"{db_path}/blacklist.cache",
            tablename="blacklist",
            autocommit=True,
            encode=json.dumps,
            decode=json.loads,
            journal_mode="WAL",
        )

        # 用户会话索引
        self.user_sessions_db = SqliteDict(
            rf"{db_path}/user_sessions.cache",
            tablename="user_sessions",
            autocommit=True,
            encode=json.dumps,
            decode=json.loads,
            journal_mode="WAL",
        )

        self.secret_key = self.config["security"]["secret_key"]
        self.algorithm = self.config["security"]["algorithm"]

    def _json_encode(self, obj):
        """自定义 JSON 编码器，处理 datetime 对象"""

        def convert_datetime(o):
            if isinstance(o, datetime):
                return o.isoformat()
            raise TypeError(
                f"Object of type {o.__class__.__name__} is not JSON serializable"
            )

        return json.dumps(obj, default=convert_datetime)

    def _json_decode(self, s):
        """自定义 JSON 解码器"""
        return json.loads(s)

    def _hash_token(self, token: str) -> str:
        """Token 哈希化（避免存储明文 Token）"""
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
        """
        创建并缓存 JWT Token

        Args:
            user_id: 用户ID
            user_data: 用户数据
            token_type: Token 类型（access 或 refresh）
            device_id: 设备ID
            user_agent: 用户代理
            ip_address: IP地址

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
            self.token_db[token_hash] = asdict(cache_data)

            # 更新用户会话索引
            self._update_user_session_index(user_id, token_hash, token_type)

            # 检查用户会话数限制
            self._enforce_session_limit(user_id)

            return token

    def _generate_jti(self) -> str:
        """生成唯一的 JWT ID"""
        import uuid

        return str(uuid.uuid4())

    def _update_user_session_index(
        self, user_id: str, token_hash: str, token_type: str
    ):
        """更新用户会话索引"""
        with self.lock:
            key = f"{user_id}:{token_type}"
            user_tokens = self.user_sessions_db.get(key, [])

            # 添加新 token
            user_tokens.append(token_hash)

            # 只保留最近的一定数量的 token
            max_tokens = 100  # 每个用户每种类型最多保留100个 token
            if len(user_tokens) > max_tokens:
                user_tokens = user_tokens[-max_tokens:]

            self.user_sessions_db[key] = user_tokens

    def _enforce_session_limit(self, user_id: str):
        """强制用户会话限制"""
        max_sessions = self.config["security"]["max_sessions_per_user"]

        access_key = f"{user_id}:access"
        refresh_key = f"{user_id}:refresh"

        # 检查 access token 数量
        access_tokens = self.user_sessions_db.get(access_key, [])
        if len(access_tokens) > max_sessions:
            # 删除最早的 token
            tokens_to_remove = access_tokens[:-max_sessions]
            for token_hash in tokens_to_remove:
                if token_hash in self.token_db:
                    del self.token_db[token_hash]

            # 更新索引
            self.user_sessions_db[access_key] = access_tokens[-max_sessions:]

        # 检查 refresh token 数量
        refresh_tokens = self.user_sessions_db.get(refresh_key, [])
        if len(refresh_tokens) > max_sessions:
            tokens_to_remove = refresh_tokens[:-max_sessions]
            for token_hash in tokens_to_remove:
                if token_hash in self.token_db:
                    del self.token_db[token_hash]

            self.user_sessions_db[refresh_key] = refresh_tokens[-max_sessions:]

    def validate_token(
        self, token: str, token_type: str = "access"
    ) -> Optional[Dict[str, Any]]:
        """
        验证 JWT Token

        Args:
            token: JWT Token
            token_type: 期望的 Token 类型

        Returns:
            验证成功返回用户数据，失败返回 None
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

            # 检查黑名单
            token_hash = self._hash_token(token)
            if self._is_blacklisted(token_hash):
                return None

            # 检查缓存
            with self.lock:
                cache_data = self.token_db.get(token_hash)
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
                    self.token_db[token_hash] = cache_data
                    return None

                # 更新最后使用时间
                cache_data["last_used"] = datetime.utcnow().isoformat()
                self.token_db[token_hash] = cache_data

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

    def add_to_blacklist(self, token: str, reason: str = "logout"):
        """添加 Token 到黑名单"""
        token_hash = self._hash_token(token)
        expire_time = datetime.utcnow() + timedelta(days=7)  # 黑名单保留7天

        self.blacklist_db[token_hash] = {
            "reason": reason,
            "blacklisted_at": datetime.utcnow().isoformat(),
            "expires_at": expire_time.isoformat(),
        }

    def _is_blacklisted(self, token_hash: str) -> bool:
        """检查 Token 是否在黑名单中"""
        with self.lock:
            if token_hash not in self.blacklist_db:
                return False

            blacklist_data = self.blacklist_db[token_hash]
            expires_at = datetime.fromisoformat(blacklist_data["expires_at"])

            # 如果黑名单条目已过期，删除它
            if datetime.utcnow() > expires_at:
                del self.blacklist_db[token_hash]
                return False

            return True

    def invalidate_token(self, token: str):
        """使单个 Token 失效"""
        with self.lock:
            token_hash = self._hash_token(token)

            # 添加到黑名单
            self.add_to_blacklist(token)

            # 标记为不活跃
            if token_hash in self.token_db:
                cache_data = self.token_db[token_hash]
                cache_data["is_active"] = False
                self.token_db[token_hash] = cache_data

    def invalidate_user_tokens(self, user_id: str, token_type: Optional[str] = None):
        """使用户的所有 Token 失效"""
        with self.lock:
            if token_type:
                keys = [f"{user_id}:{token_type}"]
            else:
                keys = [f"{user_id}:access", f"{user_id}:refresh"]

            for key in keys:
                token_hashes = self.user_sessions_db.get(key, [])
                for token_hash in token_hashes:
                    # 添加到黑名单
                    # 注意：这里我们只有 token_hash，没有原始 token
                    # 所以只能标记为不活跃
                    if token_hash in self.token_db:
                        cache_data = self.token_db[token_hash]
                        cache_data["is_active"] = False
                        self.token_db[token_hash] = cache_data

                # 清空用户会话索引
                self.user_sessions_db[key] = []

    def get_user_sessions(self, user_id: str) -> List[Dict[str, Any]]:
        """获取用户的所有活跃会话"""
        with self.lock:
            sessions = []

            for token_type in ["access", "refresh"]:
                key = f"{user_id}:{token_type}"
                token_hashes = self.user_sessions_db.get(key, [])

                for token_hash in token_hashes:
                    if token_hash in self.token_db:
                        cache_data = self.token_db[token_hash]

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
        """清理过期数据"""
        with self.lock:
            cleaned_count = 0
            current_time = datetime.utcnow()

            # 清理过期 Token
            for token_hash, data in list(self.token_db.items()):
                expires_at = datetime.fromisoformat(data["expires_at"])
                if current_time > expires_at:
                    del self.token_db[token_hash]
                    cleaned_count += 1

            # 清理过期黑名单
            for token_hash, data in list(self.blacklist_db.items()):
                expires_at = datetime.fromisoformat(data["expires_at"])
                if current_time > expires_at:
                    del self.blacklist_db[token_hash]
                    cleaned_count += 1

            return cleaned_count

    def close(self):
        with self.lock:
            """关闭所有数据库连接"""
            self.token_db.close()
            self.blacklist_db.close()
            self.user_sessions_db.close()


# 全局缓存实例
_jwt_cache = None


def get_jwt_cache() -> JWTCache:
    """获取 JWT 缓存实例（单例模式）"""
    global _jwt_cache
    if _jwt_cache is None:
        _jwt_cache = JWTCache()
    return _jwt_cache


# Token 响应模型
class TokenResponse(BaseModel):
    """Token 响应模型"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_expires_in: int


# Token 数据模型
class TokenData(BaseModel):
    """Token 数据模型"""

    user_id: str
    username: Optional[str] = None
    email: Optional[str] = None
    scopes: List[str] = []
