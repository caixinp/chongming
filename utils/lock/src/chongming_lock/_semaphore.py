"""🔒 SemaphoreLock — 分布式信号量

允许多达 N 个客户端同时持有锁（计数器模式）。
适用于限流、资源池控制等场景。

原理：
    - 使用 KV 存储当前持有者的列表 (__lock__:<name>:semaphore)
    - 尝试向列表中添加自己的 instance_id
    - 列表达到 max_count 时，后续请求等待
    - 释放时从列表中移除自己
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from nats.js.errors import KeyWrongLastSequenceError

from ._base import ChongmingLock, _encode_lock_data
from ._exceptions import LockNotAcquiredError, LockReleaseError


logger = logging.getLogger("chongming-lock")


def _build_semaphore_key(lock_name: str) -> str:
    return f"__lock__:{lock_name}:semaphore"


class SemaphoreLock(ChongmingLock):
    """分布式信号量

    允许多个实例同时持有锁（最多 *max_count* 个），适用于：
    - 限制并发访问数据库连接池
    - 控制 API 限流
    - 资源配额管理

    用法::

        sem = SemaphoreLock(cache, "db-pool", max_count=5, ttl=30)
        async with sem(timeout=10.0):
            # 最多 5 个并发访问数据库
            await db.query(...)
    """

    def __init__(
        self,
        cache,
        lock_name: str,
        max_count: int = 5,
        *,
        ttl: float = 30.0,
        renew_interval: float = 10.0,
        instance_id: str | None = None,
    ) -> None:
        super().__init__(cache, lock_name, ttl=ttl, renew_interval=renew_interval, instance_id=instance_id)
        if max_count < 1:
            raise ValueError("max_count 必须 >= 1")
        self._max_count = max_count
        self._sem_key = _build_semaphore_key(lock_name)

    @property
    def max_count(self) -> int:
        return self._max_count

    async def _try_acquire(self) -> bool:
        """尝试获取信号量槽位"""
        try:
            sem_data = await self._get_sem_data()
            holders = sem_data.get("holders", [])
            now = __import__("time").time()

            # 清理过期持有者
            active_holders = [
                h for h in holders
                if h.get("expires_at", 0) > now
            ]

            # 检查是否还有空位
            if len(active_holders) >= self._max_count:
                return False

            # 检查自己是否已在列表中
            for h in active_holders:
                if h.get("instance_id") == self._instance_id:
                    # 已在列表中，续期
                    self._acquired = True
                    return True

            # 添加自己
            active_holders.append({
                "instance_id": self._instance_id,
                "expires_at": now + self._ttl,
                "created_at": __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat(),
            })

            new_data = {
                "holders": active_holders,
                "max_count": self._max_count,
                "updated_at": __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat(),
            }

            if sem_data.get("revision") is not None:
                self._revision = await self._cache.update(
                    self._sem_key,
                    _encode_lock_data(new_data),
                    sem_data["revision"],
                )
            else:
                self._revision = await self._cache.put(
                    self._sem_key,
                    _encode_lock_data(new_data),
                )
            return True

        except KeyWrongLastSequenceError:
            return False
        except Exception as e:
            logger.debug("🔢 信号量获取异常: %s", e)
            return False

    async def _do_release(self) -> None:
        """释放信号量槽位"""
        try:
            sem_data = await self._get_sem_data()
            holders = sem_data.get("holders", [])
            now = __import__("time").time()

            # 过滤：移除自己 + 清理过期
            new_holders = [
                h for h in holders
                if h.get("instance_id") != self._instance_id
                and h.get("expires_at", 0) > now
            ]

            if not new_holders:
                # 没有持有者了，删除键
                await self._cache.delete(self._sem_key)
            else:
                new_data = {
                    "holders": new_holders,
                    "max_count": self._max_count,
                    "updated_at": __import__("datetime").datetime.now(
                        __import__("datetime").timezone.utc
                    ).isoformat(),
                }
                await self._cache.update(
                    self._sem_key,
                    _encode_lock_data(new_data),
                    sem_data["revision"],
                )

            logger.info("🔢 释放信号量: %s (holder=%s)", self._lock_name, self._instance_id)

        except KeyWrongLastSequenceError:
            # CAS 失败，尝试直接删除
            try:
                await self._cache.delete(self._sem_key)
            except Exception:
                pass
        except Exception as e:
            raise LockReleaseError(f"释放信号量失败: {self._lock_name}") from e

    async def _do_renew(self) -> None:
        """续期：更新自己在持有者列表中的过期时间"""
        if self._revision is None:
            return

        try:
            sem_data = await self._get_sem_data()
            holders = sem_data.get("holders", [])
            now = __import__("time").time()

            # 更新自己的过期时间
            updated = False
            for h in holders:
                if h.get("instance_id") == self._instance_id:
                    h["expires_at"] = now + self._ttl
                    h["updated_at"] = __import__("datetime").datetime.now(
                        __import__("datetime").timezone.utc
                    ).isoformat()
                    updated = True
                    break

            if not updated:
                logger.warning("❤️‍🩹 信号量续期失败：找不到自己的槽位 %s", self._instance_id)
                self._acquired = False
                return

            new_data = {
                "holders": holders,
                "max_count": self._max_count,
                "updated_at": __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat(),
            }

            self._revision = await self._cache.update(
                self._sem_key,
                _encode_lock_data(new_data),
                sem_data["revision"],
            )
            logger.debug("❤️ 信号量续期成功: %s (revision=%s)", self._lock_name, self._revision)

        except KeyWrongLastSequenceError:
            # CAS 冲突，下个周期重试
            pass
        except Exception as e:
            logger.exception("❤️‍🩹 信号量续期异常: %s", e)

    async def _get_sem_data(self) -> dict:
        """获取当前信号量数据"""
        entry = await self._cache.get(self._sem_key)
        if entry is None:
            return {"holders": [], "revision": None}
        data = self._parse_lock_data(entry.value)
        if data is None:
            return {"holders": [], "revision": None}
        data["revision"] = entry.revision
        return data

    def available_permits(self) -> int | None:
        """获取当前可用的信号量额度"""
        # 注意：这是本地快照，不精确
        return None

    async def available_permits_remote(self) -> int:
        """从远程获取当前可用额度"""
        sem_data = await self._get_sem_data()
        holders = sem_data.get("holders", [])
        now = __import__("time").time()
        active_count = sum(1 for h in holders if h.get("expires_at", 0) > now)
        return max(0, self._max_count - active_count)

    async def get_active_holders(self) -> list[dict]:
        """获取当前活跃的持有者列表"""
        sem_data = await self._get_sem_data()
        holders = sem_data.get("holders", [])
        now = __import__("time").time()
        return [h for h in holders if h.get("expires_at", 0) > now]
