import time
from typing import Any, Optional

import diskcache

from ..core.config import get_config


class Cache:
    def __init__(self):
        config = get_config()
        cache_dir = config["cache"]["cache_store_path"]
        self._cache = diskcache.Cache(cache_dir)

    def set(
        self,
        key: str,
        value: Any,
        ex: Optional[int] = None,
        px: Optional[int] = None,
        raw: bool = False,
    ) -> bool:
        """
        设置缓存

        Args:
            key: 键
            value: 值
            ex: 过期时间（秒）
            px: 过期时间（毫秒）

        Returns:
            bool: 是否设置成功
        """
        try:
            expire_at = None
            expire_seconds = None

            if ex is not None:
                expire_seconds = ex
                expire_at = time.time() + ex
            elif px is not None:
                expire_seconds = px / 1000.0
                expire_at = time.time() + expire_seconds

            stored_value = (value, expire_at)

            self._cache.set(key, stored_value, expire=expire_seconds)
            return True

        except Exception as e:
            print(f"[缓存] set 错误: {e}")
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取缓存

        Args:
            key: 键
            default: 默认值

        Returns:
            缓存的值，如果key不存在或已过期返回default
        """
        try:
            stored = self._cache.get(key)
            if stored is None:
                return default
            value, expire_at = stored  # type: ignore

            if expire_at is not None and time.time() > expire_at:  # type: ignore
                self._cache.delete(key)
                return default

            return value

        except Exception as e:
            print(f"[缓存] get 错误: {e}")
            return default

    def delete(self, *keys: str) -> int:
        """
        删除一个或多个key

        Args:
            keys: 要删除的key

        Returns:
            成功删除的数量
        """
        deleted = 0
        for key in keys:
            if self._cache.delete(key):
                deleted += 1
        return deleted

    def exists(self, key: str) -> bool:
        """
        检查key是否存在且未过期

        Args:
            key: 键

        Returns:
            bool: 是否存在
        """
        return self.get(key, None) is not None

    def expire(self, key: str, _time: int) -> bool:
        """
        设置过期时间

        Args:
            key: 键
            time: 过期时间（秒）

        Returns:
            bool: 是否设置成功
        """
        try:
            stored = self._cache.get(key)
            if stored is None:
                return False
            value, _ = stored  # type: ignore
            expire_at = time.time() + _time
            new_stored = (value, expire_at)
            self._cache.set(key, new_stored, expire=_time)
            return True
        except Exception as e:
            print(f"[缓存] expire 错误: {e}")
            return False

    def ttl(self, key: str) -> int:
        """
        获取key的剩余存活时间

        Args:
            key: 键

        Returns:
            int: 剩余秒数，-1表示永不过期，-2表示key不存在
        """
        try:
            stored = self._cache.get(key)
            if stored is None:
                return -2

            _, expire_at = stored  # type: ignore
            if expire_at is None:
                return -1

            remaining = expire_at - time.time()  # type: ignore
            return max(0, int(remaining))
        except Exception as e:
            print(f"[缓存] ttl 错误: {e}")
            return -2

    def keys(self, pattern: Optional[str] = None) -> list:
        """
        获取所有key，支持简单的通配符匹配（*）

        Args:
            pattern: 匹配模式，如 "user:*"

        Returns:
            list: key列表
        """
        all_keys = list(self._cache.iterkeys())

        if pattern and "*" in pattern:
            prefix = pattern.replace("*", "")
            all_keys = [k for k in all_keys if k.startswith(prefix)]  # type: ignore

        return all_keys

    def clear(self) -> bool:
        """清空所有缓存。"""
        try:
            self._cache.clear()
            return True
        except Exception as e:
            print(f"[缓存] clear 错误: {e}")
            return False

    def size(self) -> int:
        """获取当前缓存数量（不含过期但尚未清理的项）。"""
        # diskcache 的 __len__ 会返回当前有效条目数
        return len(list(self._cache.iterkeys()))

    def get_all(self) -> dict:
        """获取所有未过期的缓存数据。"""
        result = {}
        for key in self._cache.iterkeys():
            value = self.get(str(key))  # get 内部会检查并清理过期
            if value is not None:
                result[key] = value
        return result

    def close(self):
        """关闭缓存。"""
        self._cache.close()


_cache: Optional[Cache] = None


def get_cache() -> Cache:
    global _cache
    if _cache is None:
        _cache = Cache()
    return _cache


# 装饰器：缓存函数结果
def cached(ttl: Optional[int] = None):
    """
    函数结果缓存装饰器

    Args:
        ttl: 缓存时间（秒），None表示永不过期

    Example:
        @cached(ttl=60)
        def get_user(user_id: int):
            return {"id": user_id, "name": "test"}
    """

    def decorator(func):
        def wrapper(*args, **kwargs):
            # 生成缓存key
            key = f"{func.__name__}:{str(args)}:{str(kwargs)}"
            cache = get_cache()
            # 尝试从缓存获取
            result = cache.get(key)
            if result is not None:
                return result

            # 执行函数
            result = func(*args, **kwargs)

            # 存入缓存
            cache.set(key, result, ex=ttl)
            return result

        return wrapper

    return decorator
