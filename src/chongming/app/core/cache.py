"""
磁盘缓存模块

基于 diskcache 实现的本地磁盘缓存系统，提供类似 Redis 的 API 接口。
支持过期时间设置、TTL 查询、键模式匹配等功能。
"""

import time
from typing import Any, Optional

import diskcache

from ..core.config import get_config


class Cache:
    """
    磁盘缓存类

    封装 diskcache 提供统一的缓存操作接口，支持：
    - 键值对存储与检索
    - 过期时间管理（秒/毫秒）
    - TTL 查询
    - 键模式匹配
    - 批量操作

    Attributes:
        _cache: diskcache.Cache 实例，负责实际的磁盘缓存操作
    """

    def __init__(self):
        """
        初始化缓存实例

        从配置中读取缓存存储路径，创建 diskcache.Cache 实例。

        Raises:
            KeyError: 当配置中缺少 cache.cache_store_path 时
        """
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

        将键值对存储到缓存中，可选设置过期时间。内部使用元组 (value, expire_at)
        存储，以支持自定义的过期检查逻辑。

        Args:
            key: 缓存键，字符串类型
            value: 缓存值，可以是任意可序列化的 Python 对象
            ex: 过期时间（秒），与 px 互斥，优先使用 ex
            px: 过期时间（毫秒），当 ex 为 None 时生效
            raw: 是否原始存储（当前未使用，保留参数兼容性）

        Returns:
            bool: 设置成功返回 True，发生异常返回 False

        Note:
            - ex 和 px 不能同时设置，ex 优先级更高
            - 过期时间在存储时计算绝对时间戳，便于后续检查
            - 异常会被捕获并打印错误信息，不会抛出异常
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
        获取缓存值

        根据键获取缓存值，自动检查并清理已过期的缓存项。
        如果键不存在或已过期，返回默认值。

        Args:
            key: 缓存键
            default: 当键不存在或已过期时的返回值，默认为 None

        Returns:
            Any: 缓存的值，如果key不存在或已过期返回default

        Note:
            - 发现过期数据时会主动删除，避免脏数据累积
            - 异常情况下返回 default 值，保证调用安全性
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
        删除一个或多个缓存键

        批量删除指定的缓存键，返回成功删除的数量。

        Args:
            *keys: 可变参数，要删除的键列表

        Returns:
            int: 成功删除的键数量

        Note:
            - 逐个删除，某个键删除失败不影响其他键
            - 只统计实际存在的键的删除操作
        """
        deleted = 0
        for key in keys:
            if self._cache.delete(key):
                deleted += 1
        return deleted

    def exists(self, key: str) -> bool:
        """
        检查键是否存在且未过期

        通过尝试获取值来判断键的有效性，比直接检查更可靠，
        因为会触发过期检查和清理逻辑。

        Args:
            key: 要检查的缓存键

        Returns:
            bool: 键存在且未过期返回 True，否则返回 False
        """
        return self.get(key, None) is not None

    def expire(self, key: str, _time: int) -> bool:
        """
        更新键的过期时间

        重新设置指定键的过期时间，保持原值不变。
        如果键不存在，操作失败。

        Args:
            key: 缓存键
            _time: 新的过期时间（秒），从当前时间开始计算

        Returns:
            bool: 设置成功返回 True，键不存在或异常返回 False

        Note:
            - 需要先读取原值，再重新存储以更新过期时间
            - 原子性不保证，高并发场景可能有问题
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
        获取键的剩余生存时间（Time To Live）

        计算键距离过期的剩余秒数。

        Args:
            key: 缓存键

        Returns:
            int: 剩余秒数，返回值含义：
                 - >= 0: 剩余存活秒数
                 - -1: 键存在但永不过期
                 - -2: 键不存在

        Note:
            - 返回值为整数，向下取整
            - 即使剩余时间为负数也返回 0，表示即将过期
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
        获取所有缓存键，支持通配符模式匹配

        遍历所有缓存键，可根据前缀模式过滤。

        Args:
            pattern: 匹配模式，仅支持前缀通配，如 "user:*" 匹配所有 "user:" 开头的键
                    None 或空字符串返回所有键

        Returns:
            list: 匹配的键列表，按迭代顺序排列

        Note:
            - 仅支持简单的 "*" 后缀通配，不支持复杂模式
            - 大量键时性能较差，建议谨慎使用
            - pattern 中的 "*" 会被替换为空字符串作为前缀
        """
        all_keys = list(self._cache.iterkeys())

        if pattern and "*" in pattern:
            prefix = pattern.replace("*", "")
            all_keys = [k for k in all_keys if k.startswith(prefix)]  # type: ignore

        return all_keys

    def clear(self) -> bool:
        """
        清空所有缓存

        删除缓存目录中的所有数据，包括未过期的项。

        Returns:
            bool: 清空成功返回 True，异常返回 False

        Warning:
            此操作不可逆，会删除所有缓存数据
        """
        try:
            self._cache.clear()
            return True
        except Exception as e:
            print(f"[缓存] clear 错误: {e}")
            return False

    def size(self) -> int:
        """
        获取当前有效缓存项数量

        统计当前未过期的缓存键数量。

        Returns:
            int: 有效缓存项的数量

        Note:
            - 不包含已过期但尚未清理的项
            - 需要遍历所有键，大数据量时可能有性能开销
        """
        # diskcache 的 __len__ 会返回当前有效条目数
        return len(list(self._cache.iterkeys()))

    def get_all(self) -> dict:
        """
        获取所有未过期的缓存数据

        遍历所有缓存键，返回有效的键值对字典。
        自动过滤过期数据。

        Returns:
            dict: 所有有效缓存的键值对，格式为 {key: value}

        Note:
            - 会触发每个键的过期检查
            - 大数据量时内存占用较高，谨慎使用
            - 返回的是快照，不保证原子性
        """
        result = {}
        for key in self._cache.iterkeys():
            value = self.get(str(key))  # get 内部会检查并清理过期
            if value is not None:
                result[key] = value
        return result

    def close(self):
        """
        关闭缓存连接

        释放 diskcache 占用的资源，包括文件句柄等。
        应在应用退出时调用。

        Note:
            关闭后不应再使用该实例，除非重新初始化
        """
        self._cache.close()


_cache: Optional[Cache] = None


def get_cache() -> Cache:
    """
    获取全局缓存单例

    使用懒加载模式创建缓存实例，确保整个应用中只有一个 Cache 实例。

    Returns:
        Cache: 全局缓存实例

    Note:
        - 线程不安全，多线程环境需要额外同步
        - 首次调用时初始化，后续调用返回同一实例
    """
    global _cache
    if _cache is None:
        _cache = Cache()
    return _cache


# 装饰器：缓存函数结果
def cached(ttl: Optional[int] = None):
    """
    函数结果缓存装饰器

    自动缓存函数的返回值，相同参数的调用直接从缓存返回，
    避免重复计算。适用于纯函数或副作用小的函数。

    Args:
        ttl: 缓存生存时间（秒），None 表示永不过期

    Returns:
        callable: 装饰器函数

    Example:
        >>> @cached(ttl=60)
        ... def get_user(user_id: int):
        ...     return {"id": user_id, "name": "test"}
        >>>
        >>> # 第一次调用执行函数并缓存
        >>> get_user(1)
        >>> # 60秒内再次调用直接返回缓存结果
        >>> get_user(1)

    Note:
        - 缓存键由函数名 + 位置参数 + 关键字参数组成
        - 参数必须是可哈希的，否则会导致错误
        - 不适合缓存大型对象或频繁变化的数据
        - 不同参数组合会生成不同的缓存键
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
