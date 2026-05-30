"""🔒 ReentrantLock — 分布式可重入锁

允许同一个实例多次获取（重入）同一把锁，不可重入的锁会导致死锁。
使用重入计数器跟踪同一实例的加锁次数。

原理：
    - 使用 KV 存储锁持有者和重入计数 (__lock__:<name>:reentrant)
    - 同一 instance_id 可多次 acquire，每次计数 +1
    - release 时计数 -1，减到 0 才真正释放锁
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from nats.js.errors import KeyWrongLastSequenceError

from ._base import ChongmingLock, _encode_lock_data, _encode_lock_key
from ._exceptions import LockNotOwnedError, LockReleaseError, LockStateError


logger = logging.getLogger("chongming-lock")


def _build_reentrant_key(lock_name: str) -> str:
    return f"__lock__:{lock_name}:reentrant"


class ReentrantLock(ChongmingLock):
    """分布式可重入锁（Reentrant Lock / Recursive Lock）

    同一实例可多次获取同一把锁而不会死锁，适用于：
    - 递归函数中需要加锁
    - 同一个服务中多个方法相互调用，都需要同一把锁
    - 需要锁重入语义的场景

    用法::

        rlock = ReentrantLock(cache, "my-resource", ttl=30)
        async with rlock(timeout=5.0):
            # 第一次获取
            async with rlock(timeout=5.0):
                # 重入 — 同一个实例再次获取同一把锁，不会死锁
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
        self._reentrant_key = _build_reentrant_key(lock_name)
        self._local_count = 0  # 本地重入计数

    @property
    def reentrant_count(self) -> int:
        """当前重入次数"""
        return self._local_count

    async def acquire(
        self,
        timeout: float | None = None,
        blocking: bool = True,
    ) -> bool:
        """获取锁（支持可重入）

        如果当前实例已经持有锁，直接增加本地计数并返回，
        不会实际访问远程 KV 存储。
        """
        # 本地重入检测
        if self._acquired:
            self._local_count += 1
            logger.debug(
                "🔁 重入锁 +1: %s (count=%d, instance=%s)",
                self._lock_name, self._local_count, self._instance_id,
            )
            return True

        return await super().acquire(timeout=timeout, blocking=blocking)

    async def _try_acquire(self) -> bool:
        """尝试获取可重入锁"""
        try:
            # 1. 读取当前锁状态
            entry = await self._cache.get(self._reentrant_key)
            now = __import__("time").time()

            if entry is None:
                # 锁不存在，直接创建
                lock_data = self._build_lock_data(count=1)
                self._revision = await self._cache.create(self._reentrant_key, lock_data)
                self._local_count = 1
                return True

            # 锁已存在
            data = self._parse_lock_data(entry.value) # type: ignore
            if data is None:
                return False

            # 检查是否是自己持有的
            if data.get("instance_id") == self._instance_id:
                # 这种情况不应发生，基类的 acquire 已处理本地重入
                self._local_count = data.get("count", 1)
                return True

            # 检查锁是否过期
            if now >= data.get("expires_at", 0):
                # 锁已过期，CAS 抢夺
                try:
                    lock_data = self._build_lock_data(count=1, stolen_from=data.get("instance_id"))
                    self._revision = await self._cache.update(
                        self._reentrant_key, lock_data, entry.revision # type: ignore
                    )
                    self._local_count = 1
                    logger.info(
                        "🔁 抢夺过期可重入锁: %s (原持有者: %s)",
                        self._lock_name,
                        data.get("instance_id", "unknown"),
                    )
                    return True
                except KeyWrongLastSequenceError:
                    return False

            # 锁被其他实例持有且未过期
            return False

        except KeyWrongLastSequenceError:
            return False
        except Exception as e:
            logger.debug("🔁 可重入锁获取异常: %s", e)
            return False

    async def release(self) -> None:
        """释放锁（支持重入计数递减）"""
        if not self._acquired:
            logger.warning("🔁 %s: 锁未被持有，无法释放", self._lock_name)
            return

        if self._local_count > 1:
            # 本地重入，只减计数
            self._local_count -= 1
            logger.debug(
                "🔁 重入锁 -1: %s (count=%d)",
                self._lock_name, self._local_count,
            )
            # 同步更新远程计数
            await self._sync_remote_count()
            return

        # 最后一级释放
        await self._stop_renew_loop()
        await self._do_release()
        self._acquired = False
        self._revision = None
        self._local_count = 0
        logger.info("🔁 释放可重入锁: %s (instance=%s)", self._lock_name, self._instance_id)

    async def _do_release(self) -> None:
        """执行实际释放"""
        try:
            await self._cache.delete(self._reentrant_key)
            logger.debug("🗑️  删除可重入锁键: %s", self._reentrant_key)
        except Exception as e:
            raise LockReleaseError(f"释放可重入锁失败: {self._lock_name}") from e

    async def _sync_remote_count(self) -> None:
        """同步重入计数到远端"""
        if self._revision is None:
            return

        try:
            entry = await self._cache.get(self._reentrant_key)
            if entry is None:
                return

            data = self._parse_lock_data(entry.value) # type: ignore
            if data is None or data.get("instance_id") != self._instance_id:
                return

            data["count"] = self._local_count
            data["updated_at"] = __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat()

            self._revision = await self._cache.update(
                self._reentrant_key,
                _encode_lock_data(data),
                entry.revision, # type: ignore
            )

        except KeyWrongLastSequenceError:
            pass
        except Exception as e:
            logger.debug("🔁 同步远程计数异常: %s", e)

    async def _do_renew(self) -> None:
        """续期：更新过期时间并同步重入计数"""
        if self._revision is None:
            return

        try:
            entry = await self._cache.get(self._reentrant_key)
            if entry is None:
                logger.warning("❤️‍🩹 可重入锁键已丢失: %s", self._lock_name)
                self._acquired = False
                return

            data = self._parse_lock_data(entry.value) # type: ignore
            if data is None:
                return

            if data.get("instance_id") != self._instance_id:
                logger.warning(
                    "❤️‍🩹 可重入锁已被其他实例持有: %s",
                    data.get("instance_id"),
                )
                self._acquired = False
                return

            # 更新时间戳和计数
            data["expires_at"] = __import__("time").time() + self._ttl
            data["count"] = self._local_count
            data["updated_at"] = __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat()

            self._revision = await self._cache.update(
                self._reentrant_key,
                _encode_lock_data(data),
                entry.revision, # type: ignore
            )
            logger.debug(
                "❤️ 可重入锁续期成功: %s (count=%d, rev=%s)",
                self._lock_name, self._local_count, self._revision,
            )

        except KeyWrongLastSequenceError:
            pass
        except Exception as e:
            logger.exception("❤️‍🩹 可重入锁续期异常: %s", e)
