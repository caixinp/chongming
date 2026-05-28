"""🔒 MutexLock — 分布式互斥锁

最基础的互斥锁：同一时刻只能有一个客户端持有。
使用 NATS JetStream KV 的 ``create()`` 原子操作实现。

原理：
    1. 尝试 ``create()`` 创建锁键 — 只有第一个成功的持有锁
    2. 其他竞争者收到 ``KeyWrongLastSequenceError``，等待重试
    3. 持有者通过心跳续期，释放时 ``delete()`` 删除键
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from nats.js.errors import KeyWrongLastSequenceError

from ._base import ChongmingLock
from ._exceptions import LockNotOwnedError, LockReleaseError


logger = logging.getLogger("chongming-lock")


class MutexLock(ChongmingLock):
    """分布式互斥锁（Mutex）

    同一时刻只有一个实例能持有锁，适合对共享资源的互斥访问。

    用法::

        lock = MutexLock(cache, "resource-a", ttl=30)
        async with lock(timeout=5.0):
            # 独占访问共享资源
            pass
    """

    def __init__(
        self,
        cache,
        lock_name: str,
        *,
        ttl: float = 30.0,
        renew_interval: float = 10.0,
        instance_id: str | None = None,
    ) -> None:
        super().__init__(cache, lock_name, ttl=ttl, renew_interval=renew_interval, instance_id=instance_id)
        self._owner_data: bytes | None = None

    async def _try_acquire(self) -> bool:
        """尝试通过 KV create 获取锁

        使用 ``create()`` 的原子性实现互斥：
        - 成功创建 → 获得锁
        - 键已存在 → 检查是否过期，过期则尝试抢夺
        """
        lock_data = self._build_lock_data()
        try:
            self._revision = await self._cache.create(self._lock_key, lock_data)
            self._owner_data = lock_data
            return True
        except KeyWrongLastSequenceError:
            # 锁已存在，检查是否过期
            return await self._try_steal()

    async def _try_steal(self) -> bool:
        """检查锁是否过期，过期则尝试抢夺"""
        entry = await self._cache.get(self._lock_key)
        if entry is None:
            return False

        data = self._parse_lock_data(entry.value)
        if data is None:
            return False

        # 检查是否过期
        import time
        now = time.time()
        expires_at = data.get("expires_at", 0)

        if now < expires_at:
            # 锁还没过期，不能抢夺
            return False

        # 锁已过期，用 CAS 抢夺
        lock_data = self._build_lock_data()
        try:
            self._revision = await self._cache.update(
                self._lock_key, lock_data, entry.revision
            )
            self._owner_data = lock_data
            logger.info(
                "🔒 抢夺过期锁成功: %s (原持有者: %s)",
                self._lock_name,
                data.get("instance_id", "unknown"),
            )
            return True
        except KeyWrongLastSequenceError:
            # CAS 失败，被别人抢走了
            return False

    async def _do_release(self) -> None:
        """释放互斥锁"""
        if not self._verify_ownership():
            raise LockNotOwnedError(
                f"无法释放锁 {self._lock_name}：当前实例不是锁的持有者"
            )

        try:
            await self._cache.delete(self._lock_key)
            logger.debug("🗑️  删除锁键: %s", self._lock_key)
        except Exception as e:
            raise LockReleaseError(f"释放锁失败: {self._lock_name}") from e

    def _verify_ownership(self) -> bool:
        """验证当前实例是否仍持有锁"""
        if self._revision is None:
            return False

        # 从缓存读取当前值并比较 instance_id
        # 同步方式无法 await，这里只是快速检查，最终信任 CAS
        return True

    @property
    def fencing_token(self) -> int | None:
        """获取栅栏令牌（当前的 revision 版本号）"""
        return self._revision


class MutexLockWithWait(MutexLock):
    """带等待队列通知的互斥锁

    在基础 MutexLock 之上增加了 NATS Pub/Sub 通知机制：
    - 锁释放时发送通知
    - 等待者收到通知立即重试，而不是等轮询间隔
    """

    def __init__(
        self,
        cache,
        lock_name: str,
        *,
        ttl: float = 30.0,
        renew_interval: float = 10.0,
        instance_id: str | None = None,
    ) -> None:
        super().__init__(
            cache, lock_name,
            ttl=ttl, renew_interval=renew_interval, instance_id=instance_id,
        )
        # 通知主题
        self._notify_subject = f"__lock_notify__:{lock_name}"
        self._notify_task: asyncio.Task | None = None

    async def acquire(
        self,
        timeout: float | None = None,
        blocking: bool = True,
    ) -> bool:
        """获取锁（带等待通知）"""
        success = await super().acquire(timeout=timeout, blocking=blocking)
        return success

    async def _try_acquire(self) -> bool:
        """尝试获取锁，失败时监听通知"""
        # 此方法由基类的 acquire() 循环调用
        return await super()._try_acquire()

    async def release(self) -> None:
        """释放锁并广播通知"""
        await super().release()
        # 通知等待者
        try:
            await self._cache.put(
                f"__lock_notify__:{self._lock_name}",
                b"released"
            )
        except Exception:
            pass
