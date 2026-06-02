"""
Distributed Permission Cache Decorator
=======================================

基于 NATS JetStream KV 的分布式权限缓存核心实现。

架构
-----
权限缓存层位于数据库之上，通过 KV 桶 ``_permission_cache_``
存储用户权限列表。装饰器 ``require_permission`` 优先从缓存读取，
缓存未命中时调用注册的加载函数从数据库拉取。

系统设计绕过了常见的数据复制和一致性挑战:

1. 用户角色变更时, 通过 ``invalidate_user_permissions()`` 主动使缓存失效
2. 缓存条目带有 TTL 过期时间，确保过期后自动刷新(兜底策略)
3. 多 Worker 共享同一 KV 桶，天然支持分布式部署
"""

import json
import logging
from functools import wraps
from typing import Any, Awaitable, Callable, Optional, List

from chongming_cache import ChongmingCache

logger = logging.getLogger("chongming.permission")


# ── 全局状态 ──────────────────────────────────────────────────

_cache: Optional[ChongmingCache] = None
_ttl: int = 300  # 默认缓存 TTL（秒）
_loader: Optional[Callable[[str], Awaitable[List[str]]]] = None

# 缓存键前缀
_CACHE_KEY_PREFIX = "user_perms:"


# ── 初始化 ──────────────────────────────────────────────────


def init_permission_cache(
    cache: ChongmingCache,
    ttl: int = 300,
) -> None:
    """初始化全局权限缓存

    在 Worker 启动时调用，传入已连接的 ``ChongmingCache`` 实例。

    Args:
        cache: 已连接到 NATS 的缓存实例（桶名应为 ``_permission_cache_``）
        ttl: 缓存过期时间（秒），默认 300 秒（5 分钟）
    """
    global _cache, _ttl
    _cache = cache
    _ttl = ttl
    logger.info(
        "🔐 Permission cache initialized (bucket=%s, ttl=%ds)",
        cache._bucket_name if hasattr(cache, '_bucket_name') else 'unknown',
        ttl,
    )


def register_permission_loader(
    callback: Callable[[str], Awaitable[List[str]]],
) -> None:
    """注册权限加载函数

    业务侧需提供一个异步函数，接受 ``user_id``（str），
    返回该用户的权限名称列表（``List[str]``）。

    典型实现::

        async def load_permissions_from_db(user_id: str) -> List[str]:
            async for session in get_db_session_slave():
                ...  # 查询用户权限并返回
                return permissions

        register_permission_loader(load_permissions_from_db)
    """
    global _loader
    _loader = callback
    logger.info("🔐 Permission loader registered")


# ── 核心 API ──────────────────────────────────────────────


async def get_user_permissions(user_id: str) -> List[str]:
    """获取用户权限列表（优先从缓存读取）

    缓存未命中时，自动调用注册的加载函数从数据库拉取，
    并将结果写入缓存后返回。

    Args:
        user_id: 用户 ID（字符串形式）

    Returns:
        权限名称列表

    Raises:
        RuntimeError: 权限缓存未初始化或加载器未注册
        PermissionError: 用户 ID 无效
    """
    global _cache, _loader

    if _cache is None:
        raise RuntimeError("Permission cache not initialized. Call init_permission_cache() first.")
    if _loader is None:
        raise RuntimeError("Permission loader not registered. Call register_permission_loader() first.")

    cache_key = f"{_CACHE_KEY_PREFIX}{user_id}"

    # 1. 尝试从缓存读取
    try:
        entry = await _cache.get(cache_key)
        if entry is not None and entry.value is not None:
            permissions = json.loads(entry.value.decode())
            logger.debug("🔍 Cache HIT: %s -> %d permissions", cache_key, len(permissions))
            return permissions
    except Exception as e:
        logger.warning("⚠️  Cache read error for %s: %s, falling back to DB", cache_key, e)

    # 2. 缓存未命中，从数据库加载
    logger.debug("🔍 Cache MISS: %s, loading from DB...", cache_key)
    try:
        permissions = await _loader(user_id)
    except Exception as e:
        logger.error("❌ Failed to load permissions for user %s: %s", user_id, e)
        raise

    # 3. 写入缓存
    try:
        value = json.dumps(permissions).encode()
        await _cache.put(cache_key, value)
        logger.debug("💾 Cached permissions for %s (%d perms)", cache_key, len(permissions))
    except Exception as e:
        logger.warning("⚠️  Failed to write cache for %s: %s", cache_key, e)

    return permissions


async def invalidate_user_permissions(user_id: str) -> None:
    """主动清除指定用户的权限缓存

    在用户角色变更（分配/撤销角色）后调用，
    确保下次权限校验时重新从数据库加载。

    Args:
        user_id: 用户 ID（字符串形式）
    """
    global _cache

    if _cache is None:
        logger.warning("Permission cache not initialized, skipping invalidation")
        return

    cache_key = f"{_CACHE_KEY_PREFIX}{user_id}"
    try:
        await _cache.delete(cache_key)
        logger.info("🗑️  Invalidated permission cache for user %s", user_id)
    except Exception as e:
        logger.warning("⚠️  Failed to invalidate cache for %s: %s", user_id, e)


# ── 权限校验装饰器 ────────────────────────────────────────


def require_permission(permission_name: str) -> Callable:
    """权限校验装饰器（基于缓存）

    在 handler 上使用，要求当前用户拥有指定权限。
    需要 handler 的 kwargs 中包含 ``_user_id`` 字段（由网关注入）。

    用法::

        @app.handler("user.delete")
        @require_permission("user.delete")
        async def delete_user(input: UserDeleteInput) -> UserDeleteOutput:
            ...

    注意：装饰器必须放在 ``@app.handler`` 之下，
    因为需要先通过 handler 框架注入 ``_user_id``。
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # 从 kwargs 中获取 _user_id（框架注入）
            # 或者从第一个参数（input）中获取 _user_id 属性
            user_id = kwargs.get("_user_id")
            if user_id is None and args:
                input_obj = args[0]
                user_id = getattr(input_obj, "_user_id", None)
            if user_id is None:
                raise PermissionError("无法获取用户身份信息")

            # 从缓存（或降级到数据库）获取权限
            try:
                permissions = await get_user_permissions(str(user_id))
            except Exception as e:
                logger.error(
                    "❌ Permission check failed for user %s: %s",
                    user_id, e,
                )
                raise PermissionError("权限校验失败，请稍后重试") from e

            # 校验权限
            if permission_name not in permissions:
                raise PermissionError(
                    f"权限不足: 需要 '{permission_name}' 权限"
                )

            return await func(*args, **kwargs)
        return wrapper
    return decorator
