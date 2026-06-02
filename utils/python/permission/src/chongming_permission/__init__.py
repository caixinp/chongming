"""🔐 Chongming Permission — 基于 NATS KV 的分布式权限缓存工具包

提供:
- ``require_permission`` 装饰器：基于缓存的权限校验
- ``init_permission_cache``：初始化全局权限缓存连接
- ``register_permission_loader``：注册业务侧权限加载函数
- ``invalidate_user_permissions``：主动清除用户权限缓存
- ``get_user_permissions``：获取用户权限列表（优先走缓存）
"""

from .decorator import (
    init_permission_cache,
    register_permission_loader,
    require_permission,
    invalidate_user_permissions,
    get_user_permissions,
)

__all__ = [
    "init_permission_cache",
    "register_permission_loader",
    "require_permission",
    "invalidate_user_permissions",
    "get_user_permissions",
]
