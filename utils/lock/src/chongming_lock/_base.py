"""🔒 Chongming Lock — 锁基类 & 核心工具

所有分布式锁类型的基础抽象层，提供：
- NATS 连接管理
- 锁键的编码/解码（避免键冲突）
- 租约续期（heartbeat）机制
- 实例 ID 生成（用于区分锁所有者）
"""

from __future__ import annotations

import os
import asyncio
import json
import logging
import uuid
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from chongming_cache import ChongmingCache

from ._mutex import MutexLock
from ._rwlock import ReadWriteLock
from ._semaphore import SemaphoreLock
from ._reentrant import ReentrantLock
from ._lease import LeaseLock
from ._fencing_token import FencingTokenLock


logger = logging.getLogger("chongming-lock")


def _generate_instance_id() -> str:
    """生成全局唯一的实例 ID (hostname:pid:uuid)"""
    hostname = os.uname().nodename if hasattr(os, "uname") else "unknown"
    pid = os.getpid()
    uid = uuid.uuid4().hex[:8]
    return f"{hostname}:{pid}:{uid}"


def _sanitize_key_part(name: str) -> str:
    """将字符串消毒为 NATS JetStream KV 键名的合法部分

    NATS JetStream KV 键名只允许：字母、数字、'.', '-', '_', '/', '*', '>'
    """
    safe = "".join(
        c if c.isalnum() or c in "._-/*>" else "." for c in name
    )
    while ".." in safe:
        safe = safe.replace("..", ".")
    return safe.strip(".")


def _encode_lock_key(lock_name: str) -> str:
    """将锁名称编码为 KV 键，使用统一的前缀避免冲突"""
    return f"__lock__.{_sanitize_key_part(lock_name)}"


def _encode_reader_key(lock_name: str) -> str:
    """构建读锁 KV 键"""
    return f"__lock__.{_sanitize_key_part(lock_name)}.readers"


def _encode_writer_key(lock_name: str) -> str:
    """构建写锁 KV 键"""
    return f"__lock__.{_sanitize_key_part(lock_name)}.write"


def _encode_lock_data(data: dict[str, Any]) -> bytes:
    """将锁元数据编码为 bytes"""
    return json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")


def _decode_lock_data(raw: bytes) -> dict[str, Any]:
    """从 bytes 解码锁元数据"""
    return json.loads(raw.decode("utf-8"))


class ChongmingLock(ABC):
    """分布式锁抽象基类

    所有锁类型继承此类，共享：
    - NATS 连接（通过 chongming_cache 的 KV 桶）
    - 唯一实例 ID（用于确认锁归属）
    - 基础的生命周期管理（async with 支持）
    """

    def __init__(
        self,
        cache: ChongmingCache,
        lock_name: str,
        *,
        ttl: float = 30.0,
        renew_interval: float = 10.0,
        instance_id: str | None = None,
    ) -> None:
        """
        :param cache: ChongmingCache 实例（需已连接或将在 context 中连接）
        :param lock_name: 锁名称（同一名称的锁互斥）
        :param ttl: 锁的 TTL 秒数，超时自动释放（默认 30s）
        :param renew_interval: 心跳续期间隔（默认 10s，应小于 TTL）
        :param instance_id: 实例 ID，不传则自动生成
        """
        self._cache = cache
        self._lock_name = lock_name
        self._lock_key = _encode_lock_key(lock_name)
        self._ttl = ttl
        self._renew_interval = min(renew_interval, ttl / 2)
        self._instance_id = instance_id or _generate_instance_id()

        self._acquired = False
        self._renew_task: asyncio.Task[None] | None = None
        self._revision: int | None = None  # CAS 版本号

    # ── 属性 ────────────────────────────────────────────────

    @property
    def lock_name(self) -> str:
        return self._lock_name

    @property
    def instance_id(self) -> str:
        return self._instance_id

    @property
    def is_acquired(self) -> bool:
        return self._acquired

    # ── 抽象方法 ────────────────────────────────────────────

    @abstractmethod
    async def _try_acquire(self) -> bool:
        """尝试获取锁，返回是否成功"""
        ...

    @abstractmethod
    async def _do_release(self) -> None:
        """执行实际的锁释放操作"""
        ...

    # ── 公开 API ────────────────────────────────────────────

    async def acquire(
        self,
        timeout: float | None = None,
        blocking: bool = True,
    ) -> bool:
        """尝试获取锁

        :param timeout: 超时秒数，None 表示无限等待
        :param blocking: 是否阻塞等待，False 表示仅尝试一次
        :returns: 是否成功获得锁
        :raises LockNotAcquiredError: 超时未获取到
        """
        if self._acquired:
            logger.warning("🔒 %s: 锁已被当前实例持有", self._lock_name)
            return True

        deadline = None if timeout is None else asyncio.get_event_loop().time() + timeout

        while True:
            success = await self._try_acquire()
            if success:
                self._acquired = True
                self._start_renew_loop()
                logger.info(
                    "🔒 获取锁成功: %s (instance=%s, rev=%s)",
                    self._lock_name,
                    self._instance_id,
                    self._revision,
                )
                return True

            if not blocking:
                return False

            # 等待后重试
            if deadline is not None and asyncio.get_event_loop().time() >= deadline:
                from ._exceptions import LockNotAcquiredError
                raise LockNotAcquiredError(
                    f"获取锁超时: {self._lock_name} (timeout={timeout}s)"
                )

            await asyncio.sleep(0.2)

    async def release(self) -> None:
        """释放锁"""
        if not self._acquired:
            logger.warning("🔒 %s: 锁未被持有，无法释放", self._lock_name)
            return

        await self._stop_renew_loop()
        await self._do_release()
        self._acquired = False
        self._revision = None
        logger.info("🔒 释放锁成功: %s (instance=%s)", self._lock_name, self._instance_id)

    @asynccontextmanager
    async def __call__(self, timeout: float | None = None) -> AsyncIterator["ChongmingLock"]:
        """作为上下文装饰器使用::

            async with my_lock(timeout=5.0):
                # 持有锁的业务逻辑
                pass
        """
        await self.acquire(timeout=timeout)
        try:
            yield self
        finally:
            await self.release()

    # ── 租约续期 ────────────────────────────────────────────

    def _start_renew_loop(self) -> None:
        """启动后台心跳续期"""
        if self._renew_task is not None and not self._renew_task.done():
            return
        self._renew_task = asyncio.create_task(self._renew_loop())

    async def _stop_renew_loop(self) -> None:
        """停止心跳续期"""
        if self._renew_task and not self._renew_task.done():
            self._renew_task.cancel()
            try:
                await self._renew_task
            except asyncio.CancelledError:
                pass
            self._renew_task = None

    async def _renew_loop(self) -> None:
        """心跳续期循环"""
        try:
            while self._acquired:
                await asyncio.sleep(self._renew_interval)
                if not self._acquired:
                    break
                try:
                    await self._do_renew()
                except Exception:
                    logger.exception("❤️‍🩹 锁续期失败: %s", self._lock_name)
        except asyncio.CancelledError:
            pass

    async def _do_renew(self) -> None:
        """默认续期实现：使用 CAS 更新锁数据的过期时间"""
        if self._revision is None:
            return

        entry = await self._cache.get(self._lock_key)
        if entry is None:
            logger.warning("❤️‍🩹 锁键已丢失，无法续期: %s", self._lock_name)
            self._acquired = False
            return

        data = _decode_lock_data(entry.value) # type: ignore
        if data.get("instance_id") != self._instance_id:
            logger.warning(
                "❤️‍🩹 锁已被其他实例持有（%s），停止续期: %s",
                data.get("instance_id"),
                self._lock_name,
            )
            self._acquired = False
            return

        # 更新时间戳
        data["expires_at"] = (datetime.now(timezone.utc).timestamp() + self._ttl)
        data["updated_at"] = datetime.now(timezone.utc).isoformat()

        try:
            self._revision = await self._cache.update(
                self._lock_key, _encode_lock_data(data), entry.revision # type: ignore
            )
            logger.debug("❤️ 锁续期成功: %s (rev=%s)", self._lock_name, self._revision)
        except Exception:
            # CAS 失败，尝试重新续期
            raise

    # ── 工具方法 ────────────────────────────────────────────

    def _build_lock_data(self, **extra: Any) -> bytes:
        """构建锁数据 bytes"""
        data: dict[str, Any] = {
            "instance_id": self._instance_id,
            "lock_name": self._lock_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": datetime.now(timezone.utc).timestamp() + self._ttl,
            "lock_type": self.__class__.__name__,
            **extra,
        }
        return _encode_lock_data(data)

    @staticmethod
    def _parse_lock_data(entry_value: bytes) -> dict[str, Any] | None:
        """解析锁条目数据，失败返回 None"""
        try:
            return _decode_lock_data(entry_value)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None


class LockFactory:
    """锁工厂 — 方便快速创建各种锁类型

    用法::

        factory = LockFactory(cache)
        async with factory.mutex("resource-a", timeout=5.0):
            # ...
    """

    def __init__(self, cache: ChongmingCache) -> None:
        self._cache = cache

    def mutex(
        self,
        lock_name: str,
        *,
        ttl: float = 30.0,
        renew_interval: float = 10.0,
    ) -> MutexLock:
        return MutexLock(self._cache, lock_name, ttl=ttl, renew_interval=renew_interval)

    def rwlock(
        self,
        lock_name: str,
        *,
        ttl: float = 30.0,
        renew_interval: float = 10.0,
    ) -> ReadWriteLock:
        return ReadWriteLock(self._cache, lock_name, ttl=ttl, renew_interval=renew_interval)

    def semaphore(
        self,
        lock_name: str,
        max_count: int = 5,
        *,
        ttl: float = 30.0,
        renew_interval: float = 10.0,
    ) -> SemaphoreLock:
        return SemaphoreLock(self._cache, lock_name, max_count, ttl=ttl, renew_interval=renew_interval)

    def reentrant(
        self,
        lock_name: str,
        *,
        ttl: float = 30.0,
        renew_interval: float = 10.0,
    ) -> ReentrantLock:
        return ReentrantLock(self._cache, lock_name, ttl=ttl, renew_interval=renew_interval)

    def lease(
        self,
        lock_name: str,
        *,
        ttl: float = 30.0,
        renew_interval: float = 10.0,
    ) -> LeaseLock:
        return LeaseLock(self._cache, lock_name, ttl=ttl, renew_interval=renew_interval)

    def fencing_token(
        self,
        lock_name: str,
        *,
        ttl: float = 30.0,
        renew_interval: float = 10.0,
    ) -> FencingTokenLock:
        return FencingTokenLock(self._cache, lock_name, ttl=ttl, renew_interval=renew_interval)
