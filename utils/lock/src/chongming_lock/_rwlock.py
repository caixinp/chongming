"""🔒 ReadWriteLock — 分布式读写锁

允许多个读操作并发执行，写操作互斥。

原理：
    - 读锁：允许多个读操作同时加锁（共享锁）
    - 写锁：与任何其他读/写操作互斥（独占锁）
    - 使用两个 KV 键实现：
        * __lock__:<name>:write — 写锁键（create 原子性）
        * __lock__:<name>:readers — 读锁列表（存储所有读者 instance_id）
    - 写锁等待时，所有正在进行的读锁完成后才能获取
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from nats.js.errors import KeyWrongLastSequenceError

from ._base import ChongmingLock, _encode_lock_data, _decode_lock_data, _encode_lock_key, _encode_reader_key, _encode_writer_key
from ._exceptions import LockNotOwnedError, LockReleaseError


logger = logging.getLogger("chongming-lock")


# 使用 _base 中的 _encode_reader_key / _encode_writer_key


class ReadWriteLock(ChongmingLock):
    """分布式读写锁

    适用于读多写少的场景：
    - 读锁：共享锁，可被多个持有者同时获取
    - 写锁：独占锁，需等待所有读锁释放

    用法::

        rwlock = ReadWriteLock(cache, "my-resource", ttl=30)
        
        # 读锁 — 可并发
        async with rwlock.reader(timeout=5.0):
            data = read_shared_resource()
            
        # 写锁 — 互斥
        async with rwlock.writer(timeout=5.0):
            write_shared_resource(data)
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
        self._readers_key = _encode_reader_key(lock_name)
        self._writer_key = _encode_writer_key(lock_name)
        self._mode: str | None = None  # "read" or "write"

    async def _try_acquire(self) -> bool:
        """基础 acquire 不应直接调用，使用 reader()/writer() 替代"""
        raise RuntimeError("请使用 .reader() 或 .writer() 获取读写锁")

    async def _do_release(self) -> None:
        """基础 release 不应直接调用"""
        raise RuntimeError("请使用对应的 ReaderLock/WriterLock 释放")

    # ── 读锁 & 写锁上下文 ─────────────────────────────────

    def reader(self, timeout: float | None = None):
        """获取读锁上下文管理器"""
        return _ReaderLockContext(self, timeout)

    def writer(self, timeout: float | None = None):
        """获取写锁上下文管理器"""
        return _WriterLockContext(self, timeout)


class _ReaderLockContext:
    """读锁上下文管理器"""

    def __init__(self, rwlock: ReadWriteLock, timeout: float | None = None):
        self._rwlock = rwlock
        self._timeout = timeout
        self._reader_lock = _ReaderLock(rwlock)

    async def __aenter__(self):
        await self._reader_lock._acquire(timeout=self._timeout)
        return self._reader_lock

    async def __aexit__(self, *args):
        await self._reader_lock._release()


class _WriterLockContext:
    """写锁上下文管理器"""

    def __init__(self, rwlock: ReadWriteLock, timeout: float | None = None):
        self._rwlock = rwlock
        self._timeout = timeout
        self._writer_lock = _WriterLock(rwlock)

    async def __aenter__(self):
        await self._writer_lock._acquire(timeout=self._timeout)
        return self._writer_lock

    async def __aexit__(self, *args):
        await self._writer_lock._release()


class _ReaderLock:
    """读锁 — 共享锁实现"""

    def __init__(self, rwlock: ReadWriteLock):
        self._rwlock = rwlock
        self._cache = rwlock._cache
        self._readers_key = rwlock._readers_key
        self._writer_key = rwlock._writer_key
        self._instance_id = rwlock._instance_id
        self._lock_name = rwlock._lock_name
        self._acquired = False

    async def _acquire(self, timeout: float | None = None) -> None:
        """获取读锁"""
        deadline = None if timeout is None else asyncio.get_event_loop().time() + timeout

        while True:
            # 1. 检查是否有写锁
            write_entry = await self._cache.get(self._writer_key)
            if write_entry is not None:
                # 有写锁，检查是否过期
                data = ChongmingLock._parse_lock_data(write_entry.value)
                if data:
                    if time.time() < data.get("expires_at", 0):
                        # 写锁未过期，等待
                        await self._check_deadline(deadline, timeout)
                        await asyncio.sleep(0.2)
                        continue

            # 2. 尝试注册为读者
            try:
                readers_data = await self._get_readers_list()
                if self._instance_id in readers_data["readers"]:
                    # 已经注册了
                    self._acquired = True
                    return

                readers_data["readers"].append(self._instance_id)
                readers_data["updated_at"] = datetime.now(timezone.utc).isoformat()

                if readers_data.get("revision") is not None:
                    await self._cache.update(
                        self._readers_key,
                        _encode_lock_data(readers_data),
                        readers_data["revision"],
                    )
                else:
                    await self._cache.put(
                        self._readers_key,
                        _encode_lock_data(readers_data),
                    )
                self._acquired = True
                logger.info("📖 获取读锁成功: %s (reader=%s)", self._lock_name, self._instance_id)
                return

            except (KeyWrongLastSequenceError, Exception) as e:
                logger.debug("📖 获取读锁重试: %s", e)
                await self._check_deadline(deadline, timeout)
                await asyncio.sleep(0.2)

    async def _release(self) -> None:
        """释放读锁"""
        if not self._acquired:
            return

        try:
            readers_data = await self._get_readers_list()
            if self._instance_id in readers_data["readers"]:
                readers_data["readers"].remove(self._instance_id)
                readers_data["updated_at"] = datetime.now(timezone.utc).isoformat()

                if readers_data["readers"]:
                    # 还有别的读者，更新列表
                    await self._cache.update(
                        self._readers_key,
                        _encode_lock_data(readers_data),
                        readers_data["revision"],
                    )
                else:
                    # 没有读者了，删除键
                    await self._cache.delete(self._readers_key)

            self._acquired = False
            logger.info("📖 释放读锁: %s (reader=%s)", self._lock_name, self._instance_id)
        except Exception as e:
            logger.warning("📖 释放读锁异常: %s", e)
            self._acquired = False

    async def _get_readers_list(self) -> dict:
        """获取当前读者列表"""
        entry = await self._cache.get(self._readers_key)
        if entry is None:
            return {"readers": [], "revision": None}
        data = ChongmingLock._parse_lock_data(entry.value)
        if data is None:
            return {"readers": [], "revision": None}
        data["revision"] = entry.revision
        if "readers" not in data:
            data["readers"] = []
        return data

    async def _check_deadline(self, deadline, timeout):
        if deadline is not None and asyncio.get_event_loop().time() >= deadline:
            from ._exceptions import LockNotAcquiredError
            raise LockNotAcquiredError(
                f"获取读锁超时: {self._lock_name} (timeout={timeout}s)"
            )


class _WriterLock:
    """写锁 — 独占锁实现"""

    def __init__(self, rwlock: ReadWriteLock):
        self._rwlock = rwlock
        self._cache = rwlock._cache
        self._readers_key = rwlock._readers_key
        self._writer_key = rwlock._writer_key
        self._instance_id = rwlock._instance_id
        self._lock_name = rwlock._lock_name
        self._lock_key = rwlock._writer_key
        self._revision: int | None = None
        self._acquired = False

    async def _acquire(self, timeout: float | None = None) -> None:
        """获取写锁"""
        deadline = None if timeout is None else asyncio.get_event_loop().time() + timeout

        while True:
            # 1. 检查是否有读者正在读取
            readers_entry = await self._cache.get(self._readers_key)
            if readers_entry is not None:
                readers_data = ChongmingLock._parse_lock_data(readers_entry.value)
                if readers_data and readers_data.get("readers"):
                    # 有活跃读者，等待
                    await self._check_deadline(deadline, timeout)
                    await asyncio.sleep(0.2)
                    continue

            # 2. 尝试创建写锁（原子写入）
            lock_data = {
                "instance_id": self._instance_id,
                "lock_name": self._lock_name,
                "lock_type": "WriterLock",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": time.time() + self._rwlock._ttl,
            }

            try:
                entry = await self._cache.create(self._writer_key, _encode_lock_data(lock_data))
                self._revision = entry
                self._acquired = True
                logger.info("✍️  获取写锁成功: %s (writer=%s)", self._lock_name, self._instance_id)
                return
            except KeyWrongLastSequenceError:
                # 写锁已存在，检查是否过期
                write_entry = await self._cache.get(self._writer_key)
                if write_entry is not None:
                    data = ChongmingLock._parse_lock_data(write_entry.value)
                    if data:
                        if time.time() < data.get("expires_at", 0):
                            # 未过期
                            await self._check_deadline(deadline, timeout)
                            await asyncio.sleep(0.2)
                            continue

                        # 过期了，CAS 抢夺
                        try:
                            new_data = _encode_lock_data({
                                **lock_data,
                                "stolen_from": data.get("instance_id", "unknown"),
                            })
                            self._revision = await self._cache.update(
                                self._writer_key, new_data, write_entry.revision
                            )
                            self._acquired = True
                            logger.info(
                                "✍️  抢夺过期写锁成功: %s (原持有者: %s)",
                                self._lock_name,
                                data.get("instance_id", "unknown"),
                            )
                            return
                        except KeyWrongLastSequenceError:
                            pass

                await self._check_deadline(deadline, timeout)
                await asyncio.sleep(0.2)

    async def _release(self) -> None:
        """释放写锁"""
        if not self._acquired:
            return

        try:
            await self._cache.delete(self._writer_key)
            self._acquired = False
            self._revision = None
            logger.info("✍️  释放写锁: %s (writer=%s)", self._lock_name, self._instance_id)
        except Exception as e:
            logger.warning("✍️  释放写锁异常: %s", e)
            self._acquired = False

    async def _check_deadline(self, deadline, timeout):
        if deadline is not None and asyncio.get_event_loop().time() >= deadline:
            from ._exceptions import LockNotAcquiredError
            raise LockNotAcquiredError(
                f"获取写锁超时: {self._lock_name} (timeout={timeout}s)"
            )

    @property
    def fencing_token(self) -> int | None:
        return self._revision
