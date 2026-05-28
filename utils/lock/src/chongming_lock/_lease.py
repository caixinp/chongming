"""🔒 LeaseLock — 分布式租约锁

带 TTL 自动释放的锁。持有者在租约期内独享资源，
到期自动释放，无需显式调用 release()。
适用于 leader election、分布式调度等场景。

原理：
    - 使用 KV create() 创建租约键
    - 后台心跳续期延长租约
    - 心跳停止后 KV 键 TTL 到期自动删除（依靠应用级续期）
    - 不依赖 NATS KV 内置 TTL（因为需要心跳续期）
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from nats.js.errors import KeyWrongLastSequenceError

from ._base import ChongmingLock, _encode_lock_data
from ._exceptions import LockNotAcquiredError, LockReleaseError


logger = logging.getLogger("chongming-lock")


def _build_lease_key(lock_name: str) -> str:
    return f"__lock__:{lock_name}:lease"


class LeaseLock(ChongmingLock):
    """分布式租约锁

    持有者在租约期内拥有资源，到期自动释放。
    与普通互斥锁的区别：
    - 租房约的目的是「在租约期内独占」，而不是「永久持有直到释放」
    - 更适用于 leader election、任务调度等场景

    用法::

        lease = LeaseLock(cache, "leader-election", ttl=30)
        
        # 获取租约
        async with lease(timeout=5.0):
            # 当前节点是 leader，持续心跳续期
            while lease.is_acquired:
                await do_leader_work()
                await asyncio.sleep(5)
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
        self._lease_key = _build_lease_key(lock_name)
        self._lease_start: float = 0.0
        self._lease_expires: float = 0.0

    @property
    def lease_start_time(self) -> float:
        """租约开始时间戳"""
        return self._lease_start

    @property
    def lease_expires_at(self) -> float:
        """租约到期时间戳"""
        return self._lease_expires

    @property
    def remaining_lease_time(self) -> float:
        """剩余租约时间（秒）"""
        remaining = self._lease_expires - __import__("time").time()
        return max(0.0, remaining)

    async def _try_acquire(self) -> bool:
        """尝试获取租约"""
        now = __import__("time").time()
        lock_data = self._build_lock_data(
            lease_start=now,
            ttl=self._ttl,
        )

        try:
            self._revision = await self._cache.create(self._lease_key, lock_data)
            self._lease_start = now
            self._lease_expires = now + self._ttl
            return True
        except KeyWrongLastSequenceError:
            # 租约已存在，检查是否过期
            return await self._try_steal()

    async def _try_steal(self) -> bool:
        """检查租约是否过期，过期则抢夺"""
        entry = await self._cache.get(self._lease_key)
        if entry is None:
            return False

        data = self._parse_lock_data(entry.value)
        if data is None:
            return False

        now = __import__("time").time()
        expires_at = data.get("expires_at", 0)

        if now < expires_at:
            # 租约仍有效
            return False

        # 租约过期，CAS 抢夺
        lock_data = self._build_lock_data(
            lease_start=now,
            ttl=self._ttl,
            stolen_from=data.get("instance_id", "unknown"),
        )

        try:
            self._revision = await self._cache.update(
                self._lease_key, lock_data, entry.revision
            )
            self._lease_start = now
            self._lease_expires = now + self._ttl
            logger.info(
                "🔒 抢夺过期租约: %s (原持有者: %s)",
                self._lock_name,
                data.get("instance_id", "unknown"),
            )
            return True
        except KeyWrongLastSequenceError:
            return False

    async def _do_release(self) -> None:
        """释放租约"""
        try:
            await self._cache.delete(self._lease_key)
            self._lease_start = 0.0
            self._lease_expires = 0.0
            logger.info("🔒 释放租约: %s (instance=%s)", self._lock_name, self._instance_id)
        except Exception as e:
            raise LockReleaseError(f"释放租约失败: {self._lock_name}") from e

    async def _do_renew(self) -> None:
        """续期租约"""
        if self._revision is None:
            return

        entry = await self._cache.get(self._lease_key)
        if entry is None:
            logger.warning("❤️‍🩹 租约键已丢失: %s", self._lock_name)
            self._acquired = False
            return

        data = self._parse_lock_data(entry.value)
        if data is None:
            return

        if data.get("instance_id") != self._instance_id:
            logger.warning(
                "❤️‍🩹 租约已被其他实例抢夺: %s (新持有者: %s)",
                self._lock_name,
                data.get("instance_id"),
            )
            self._acquired = False
            return

        # 续期
        now = __import__("time").time()
        data["expires_at"] = now + self._ttl
        data["updated_at"] = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()
        data["lease_renew_count"] = data.get("lease_renew_count", 0) + 1

        try:
            self._revision = await self._cache.update(
                self._lease_key,
                _encode_lock_data(data),
                entry.revision,
            )
            self._lease_expires = now + self._ttl
            logger.debug("❤️ 租约续期成功: %s (到期时间: %s)", self._lock_name, self._lease_expires)
        except KeyWrongLastSequenceError:
            # CAS 冲突，下个周期重试
            pass
        except Exception as e:
            logger.exception("❤️‍🩹 租约续期异常: %s", e)

    async def get_lease_info(self) -> dict | None:
        """获取当前租约信息（不改变租约状态）"""
        entry = await self._cache.get(self._lease_key)
        if entry is None:
            return None

        data = self._parse_lock_data(entry.value)
        if data is None:
            return None

        now = __import__("time").time()
        return {
            "holder": data.get("instance_id"),
            "lock_name": data.get("lock_name"),
            "created_at": data.get("created_at"),
            "expires_at": data.get("expires_at"),
            "remaining_seconds": max(0.0, data.get("expires_at", 0) - now),
            "is_expired": now >= data.get("expires_at", 0),
            "renew_count": data.get("lease_renew_count", 0),
        }
