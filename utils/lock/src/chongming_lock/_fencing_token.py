"""🔒 FencingTokenLock — 分布式栅栏令牌锁

提供单调递增的栅栏令牌（Fencing Token），用于防止分布式系统中的
「幽灵客户端」问题（delayed requests）。

每次成功获取锁时生成一个全局唯一且单调递增的令牌号，
客户端在执行写操作时需将该令牌传递给后端资源（如数据库），
后端拒絕任何令牌值小于等于已处理最大令牌的请求。

原理：
    - 使用 NATS KV 的 revision 作为栅栏令牌（单调递增）
    - 每次 acquire 获得一个新的 revision
    - 在需要 fence 的资源操作中传递 revision 作为令牌
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from nats.js.errors import KeyWrongLastSequenceError

from ._base import ChongmingLock, _encode_lock_data
from ._exceptions import LockNotAcquiredError, LockReleaseError


logger = logging.getLogger("chongming-lock")


def _build_fencing_key(lock_name: str) -> str:
    """栅栏锁的数据键"""
    return f"__lock__:{lock_name}:fencing"


def _build_token_counter_key(lock_name: str) -> str:
    """全局单调递增计数器键"""
    return f"__lock__:{lock_name}:token_counter"


class FencingTokenLock(ChongmingLock):
    """分布式栅栏令牌锁（Fencing Token Lock）

    每次获取锁时生成一个 **严格单调递增** 的栅栏令牌（token），
    该 token 可以用于解决分布式系统中的「僵尸节点」问题。

    用法::

        ft_lock = FencingTokenLock(cache, "db-write-lock", ttl=30)
        
        async with ft_lock(timeout=5.0):
            token = ft_lock.fencing_token  # 单调递增的令牌
            # 将 token 传给数据库，数据库拒绝旧令牌的写操作
            await db.write_with_fencing(data, token)

    保护模式：
        后端资源（如数据库）应记录「已处理的最高令牌号」，
        拒绝任何令牌 ≤ 已记录最高令牌的请求。
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
        self._fencing_key = _build_fencing_key(lock_name)
        self._counter_key = _build_token_counter_key(lock_name)
        self._token: int | None = None  # 当前栅栏令牌

    @property
    def fencing_token(self) -> int | None:
        """获取当前栅栏令牌（单调递增的 revision）

        在 ``async with lock:`` 块内调用，返回此次获取锁时
        生成的唯一令牌号。
        """
        return self._token

    @property
    def token(self) -> int | None:
        """fencing_token 的别名"""
        return self._token

    async def _try_acquire(self) -> bool:
        """尝试获取栅栏锁并生成令牌"""
        # 使用 create 尝试获取锁（互斥）
        now = __import__("time").time()
        lock_data = self._build_lock_data(token=None)

        try:
            self._revision = await self._cache.create(self._fencing_key, lock_data)
            # 成功获取锁，生成递增令牌
            self._token = await self._next_token()
            # 更新锁数据中的令牌值
            await self._update_lock_token(self._token)
            return True
        except KeyWrongLastSequenceError:
            # 锁已存在，检查过期
            return await self._try_steal()

    async def _try_steal(self) -> bool:
        """检查锁是否过期，过期则抢夺并生成新令牌"""
        entry = await self._cache.get(self._fencing_key)
        if entry is None:
            return False

        data = self._parse_lock_data(entry.value)
        if data is None:
            return False

        now = __import__("time").time()
        expires_at = data.get("expires_at", 0)

        if now < expires_at:
            return False

        # 锁过期，CAS 抢夺
        lock_data = self._build_lock_data(
            token=None,
            stolen_from=data.get("instance_id", "unknown"),
        )

        try:
            self._revision = await self._cache.update(
                self._fencing_key, lock_data, entry.revision
            )
            # 生成新令牌
            self._token = await self._next_token()
            await self._update_lock_token(self._token)
            logger.info(
                "🔒 抢夺过期栅栏锁: %s (原持有者: %s, token=%d)",
                self._lock_name,
                data.get("instance_id", "unknown"),
                self._token,
            )
            return True
        except KeyWrongLastSequenceError:
            return False

    async def _next_token(self) -> int:
        """生成下一个全局单调递增令牌

        使用 CAS 更新计数器：
        1. 读取当前计数值
        2. 值 +1
        3. CAS 写入
        4. 如果冲突则重试
        """
        for attempt in range(10):
            try:
                entry = await self._cache.get(self._counter_key)
                if entry is None:
                    # 首次使用，从 1 开始
                    rev = await self._cache.create(self._counter_key, b"1")
                    return 1

                current = int(entry.value.decode())
                next_val = current + 1
                await self._cache.update(
                    self._counter_key,
                    str(next_val).encode(),
                    entry.revision,
                )
                return next_val
            except KeyWrongLastSequenceError:
                await asyncio.sleep(0.05 * (2 ** attempt))
            except (ValueError, UnicodeDecodeError):
                # 计数器数据异常，重置
                try:
                    await self._cache.delete(self._counter_key)
                except Exception:
                    pass

        raise LockNotAcquiredError(
            f"无法获取栅栏令牌计数器: {self._lock_name}"
        )

    async def _update_lock_token(self, token: int) -> None:
        """更新锁数据中的令牌值"""
        if self._revision is None:
            return

        try:
            entry = await self._cache.get(self._fencing_key)
            if entry is None:
                return

            data = self._parse_lock_data(entry.value)
            if data is None or data.get("instance_id") != self._instance_id:
                return

            data["token"] = token
            data["updated_at"] = __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat()

            self._revision = await self._cache.update(
                self._fencing_key,
                _encode_lock_data(data),
                entry.revision,
            )
        except KeyWrongLastSequenceError:
            pass
        except Exception as e:
            logger.debug("🔒 更新锁令牌异常: %s", e)

    async def _do_release(self) -> None:
        """释放栅栏锁"""
        try:
            await self._cache.delete(self._fencing_key)
            logger.info(
                "🔒 释放栅栏锁: %s (instance=%s, token=%d)",
                self._lock_name, self._instance_id, self._token or -1,
            )
        except Exception as e:
            raise LockReleaseError(f"释放栅栏锁失败: {self._lock_name}") from e

    async def _do_renew(self) -> None:
        """续期锁"""
        if self._revision is None:
            return

        entry = await self._cache.get(self._fencing_key)
        if entry is None:
            logger.warning("❤️‍🩹 栅栏锁键已丢失: %s", self._lock_name)
            self._acquired = False
            return

        data = self._parse_lock_data(entry.value)
        if data is None:
            return

        if data.get("instance_id") != self._instance_id:
            self._acquired = False
            return

        now = __import__("time").time()
        data["expires_at"] = now + self._ttl
        data["updated_at"] = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()

        try:
            self._revision = await self._cache.update(
                self._fencing_key,
                _encode_lock_data(data),
                entry.revision,
            )
            logger.debug("❤️ 栅栏锁续期成功: %s (token=%d)", self._lock_name, self._token or -1)
        except KeyWrongLastSequenceError:
            pass
        except Exception as e:
            logger.exception("❤️‍🩹 栅栏锁续期异常: %s", e)

    async def get_current_token(self) -> int | None:
        """获取当前计数器的令牌值（不获取锁）"""
        entry = await self._cache.get(self._counter_key)
        if entry is None:
            return None
        try:
            return int(entry.value.decode())
        except (ValueError, UnicodeDecodeError):
            return None

    async def verify_token(self, token: int) -> bool:
        """验证给定的令牌是否仍然有效（大于已记录的最大令牌？）

        注意：这只是一个辅助检查，真正的 fencing 验证
        应在后端资源（如数据库）中实现。
        """
        current_max = await self.get_current_token()
        if current_max is None:
            return True
        return token >= current_max
