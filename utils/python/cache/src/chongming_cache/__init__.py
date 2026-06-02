"""🚀 Chongming Cache — 基于 NATS JetStream KV 的轻量级缓存库

支持:
- 标准 KV 操作：get / put / update / delete
- 🔔 Watch 监听键值变化（跨进程实时通知）
- 📜 历史版本追溯（history）
- 🪣 自动管理 KV 桶（create / delete）
- 🔄 异步上下文管理器（async with）
- 👥 **多进程并发安全**（底层 NATS JetStream 天然支持分布式）

多进程/多实例并发说明
──────────────────────
NATS JetStream KV 是 **服务端存储**，多个客户端（进程/容器/机器）
可以同时连接同一个 NATS 集群的同一个 KV 桶，完全支持：

1. **读写并发** — 每个进程独立连接，同时读写不受限
2. **CAS 乐观锁** — 使用 `update(key, value, revision)` 进行原子更新，
   写入冲突时会抛出异常，需要重试
3. **Watch 跨进程通知** — 进程 A 修改值后，进程 B 的 watcher 立即收到通知
4. **连接隔离** — 每个进程有独立 NATS 连接，互不干扰
"""

from __future__ import annotations

import os
import asyncio
import logging
from functools import wraps
from logging import Logger
from typing import Any, AsyncIterator, Awaitable, Callable, Optional, Sequence, TypeVar

import nats
import nats.js.errors
from nats.js.errors import (
    APIError,
    BadRequestError,
    BucketNotFoundError,
    KeyWrongLastSequenceError,
)
from nats.js import JetStreamContext
from nats.js.api import KeyValueConfig
from nats.js.kv import KeyValue

from chongming_config import load_config, Config


DEFAULT_NATS_URL = "nats://localhost:4222"
DEFAULT_BUCKET = "app_config"


# ── CAS 重试工具 ──────────────────────────────────────────

T = TypeVar("T")


def cas_retry(
    max_retries: int = 3,
    base_delay: float = 0.05,
    max_delay: float = 0.5,
) -> Callable:
    """CAS（Compare-And-Swap）乐观锁重试装饰器

    当多个进程同时更新同一个 key 时，只有一个能成功，
    其余会收到 ``KeyWrongLastSequenceError``，此装饰器自动重试。

    用法::

        @cas_retry(max_retries=5)
        async def update_timeout(cache: ChongmingCache, key: str, new_value: bytes):
            entry = await cache.get(key)
            if entry is None:
                await cache.put(key, new_value)
            else:
                await cache.update(key, new_value, entry.revision)
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except KeyWrongLastSequenceError as e:
                    last_exc = e
                    if attempt < max_retries - 1:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        await asyncio.sleep(delay)
            raise last_exc  # type: ignore[union-attr]
        return wrapper
    return decorator


class ChongmingCache:
    """基于 NATS JetStream KV 的缓存客户端

    用法::

        cache = ChongmingCache(logger, bucket="my_cache")
        await cache.connect()
        await cache.put("key", b"value")
        val = await cache.get("key")
        await cache.close()
    """

    def __init__(
        self,
        logger: Logger,
        bucket: str = DEFAULT_BUCKET,
        nats_url: str | None = None,
    ) -> None:
        self.logger = logger
        if os.path.exists("config.toml"):
            self._config: Config = load_config("config.toml")
        else:
            self._config = {"nats": {"urls": [DEFAULT_NATS_URL]}}  # 默认配置，适合本地开发  # type: ignore
        self._bucket_name = bucket

        # 优先使用传入的 nats_url，否则从配置中读取
        if nats_url is not None:
            self._nats_url = nats_url
        else:
            urls = self._config.get("nats", {}).get("urls", [DEFAULT_NATS_URL])
            self._nats_url = urls[0] if urls else DEFAULT_NATS_URL

        self._nc: nats.NATS | None = None # type: ignore
        self._js: JetStreamContext | None = None
        self._kv: KeyValue | None = None

    # ── 生命周期 ──────────────────────────────────────────────

    async def connect(self) -> None:
        """连接到 NATS 并打开/创建 KV 桶"""
        self._nc = await nats.connect(self._nats_url)
        self._js = self._nc.jetstream()

        # 尝试打开已有桶，不存在则创建
        try:
            self._kv = await self._js.key_value(self._bucket_name)
            self.logger.info("📦 打开已有 KV 桶: %s", self._bucket_name)
        except BucketNotFoundError:
            self._kv = await self._js.create_key_value(
                KeyValueConfig(
                    bucket=self._bucket_name,
                    history=5,
                    ttl=3600,
                    max_value_size=1024,
                )
            )
            self.logger.info("✅ 创建新 KV 桶: %s", self._bucket_name)

    async def close(self) -> None:
        """关闭 NATS 连接"""
        if self._nc and self._nc.is_connected:
            await self._nc.close()
            self.logger.info("🔌 NATS 连接已关闭")

    async def __aenter__(self) -> "ChongmingCache":
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    # ── KV 核心操作 ─────────────────────────────────────────

    async def put(self, key: str, value: bytes) -> int:
        """写入键值对，返回版本号（revision）

        注意 ``put()`` 是 upsert 语义：无论键是否存在都会写入。
        如需"仅创建不存在"（create-if-not-exists），请使用 ``create()``。
        """
        entry = await self._kv.put(key, value) # type: ignore
        self.logger.debug("✏️  写入 %s = %s (版本 %d)", key, value, entry)
        return entry

    async def create(self, key: str, value: bytes) -> int:
        """创建键值对，仅当键不存在时成功

        这是真正的"创建锁"——如果键已存在，抛出
        ``KeyWrongLastSequenceError``，适合多进程同时初始化场景。

        用法::

            # 只有一个进程会创建成功，其余收到异常
            rev = await cache.create("app.lock", b"init")
        """
        entry = await self._kv.create(key, value) # type: ignore
        self.logger.info("🆕 创建 %s = %s (版本 %d)", key, value, entry)
        return entry

    async def get(self, key: str) -> Optional[KeyValue.Entry]:
        """获取指定键的值，不存在返回 None"""
        try:
            entry = await self._kv.get(key) # type: ignore
            return entry
        except (KeyWrongLastSequenceError, nats.js.errors.Error):
            return None

    async def update(self, key: str, value: bytes, revision: int) -> int:
        """基于版本号更新键值，CAS 乐观锁

        当有其他进程/协程在此期间修改了该 key 的值，
        revision 不匹配时会抛出 ``KeyWrongLastSequenceError``。
        请配合 ``cas_update()`` 或 ``@cas_retry`` 使用。
        """
        entry = await self._kv.update(key, value, revision) # type: ignore
        return entry

    async def cas_update(
        self,
        key: str,
        new_value: bytes,
        max_retries: int = 5,
    ) -> int:
        """原子性的 CAS 更新：get → CAS update → 自动重试

        这是多进程并发安全的更新方式，内部自动：

        1. 读取当前值和版本号
        2. 用版本号执行 CAS update
        3. 如果冲突则等待后重试（最多 *max_retries* 次）

        用法::

            rev = await cache.cas_update("counter", new_value, max_retries=5)
        """
        last_exc = None
        for attempt in range(max_retries):
            try:
                entry = await self.get(key)
                if entry is None:
                    # 键不存在，直接 put（相当于创建）
                    return await self.put(key, new_value)
                else:
                    return await self.update(key, new_value, entry.revision) # type: ignore
            except (KeyWrongLastSequenceError, BadRequestError) as e:
                last_exc = e
                if attempt < max_retries - 1:
                    delay = min(0.05 * (2 ** attempt), 0.5)
                    await asyncio.sleep(delay)
        raise last_exc  # type: ignore[union-attr]

    async def delete(self, key: str) -> None:
        """删除指定键"""
        await self._kv.delete(key) # type: ignore
        self.logger.debug("🗑️  删除键: %s", key)

    async def purge(self, key: str) -> None:
        """彻底清除键的所有历史记录"""
        await self._kv.purge(key) # type: ignore
        self.logger.debug("🧹 清除键的所有历史: %s", key)

    async def exists(self, key: str) -> bool:
        """检查键是否存在"""
        try:
            await self._kv.get(key) # type: ignore
            return True
        except (KeyWrongLastSequenceError, nats.js.errors.Error):
            return False

    # ── 批量操作 ─────────────────────────────────────────────

    async def put_batch(self, items: dict[str, bytes]) -> list[int]:
        """批量写入多个键值对，返回版本号列表"""
        revisions = []
        for key, value in items.items():
            rev = await self.put(key, value)
            revisions.append(rev)
        return revisions

    async def keys(self) -> list[str]:
        """列出桶中所有键（返回快照集）"""
        return await self._kv.keys() # type: ignore

    # ── 监听 & 历史 ─────────────────────────────────────────

    async def watch(
        self, key: str = ">"
    ) -> AsyncIterator[KeyValue.Entry]:
        """监听某个键（或所有键）的变化，返回异步迭代器

        用法::

            async with cache.watch("feature.flag") as watcher:
                async for change in watcher:
                    print(f"{change.key} = {change.value}")
        """
        watcher = await self._kv.watch(key) # type: ignore
        try:
            while True:
                entry = await watcher.updates()
                if entry is None:
                    break
                yield entry # type: ignore
        finally:
            await watcher.stop()

    async def subscribe(
        self,
        key: str,
        callback: Callable[[KeyValue.Entry], Awaitable[None]],
        *,
        include_current: bool = False,
    ) -> asyncio.Task:
        """订阅键变化，后台持续监听，有变更时自动触发回调

        这是 ``watch()`` 的简化版本 —— 不需要手动 for 循环，
        后台协程持续运行，每次键变化都会自动调用回调。

        用法::

            async def on_change(entry: KeyValue.Entry):
                print(f"{entry.key} = {entry.value.decode()}")

            task = await cache.subscribe("mykey", on_change)
            ...
            task.cancel()  # 停止监听

        :param key: 要监听的键（支持 ``>`` 通配符匹配所有键）
        :param callback: 异步回调函数，接收 KeyValue.Entry
        :param include_current: 是否把当前值作为第一次回调触发
              默认 False，仅监听后续变更
        :returns: asyncio.Task 对象，可用于后续取消监听
        """
        watcher = await self._kv.watch(key) # type: ignore

        async def _listen():
            try:
                skip_snapshot = not include_current  # 初始快照标记
                while True:
                    entry = await watcher.updates()
                    if entry is None:
                        # None 是初始同步完成的标记，继续等待
                        continue
                    if skip_snapshot:
                        # 第一个非 None 的条目是初始快照，跳过
                        skip_snapshot = False
                        continue
                    await callback(entry) # type: ignore
            except asyncio.CancelledError:
                pass  # 外部调用 task.cancel() 时正常退出
            except Exception:
                pass  # 关闭过程中可能发生 TimeoutError 等异常（如 NATS 连接被 drain），安全忽略
            finally:
                await watcher.stop()

        task = asyncio.create_task(_listen())
        return task

    async def history(self, key: str) -> Sequence[KeyValue.Entry]:
        """获取指定键的历史版本列表"""
        return await self._kv.history(key) # type: ignore

    # ── 桶管理 ──────────────────────────────────────────────

    async def recreate_bucket(
        self,
        history: int = 5,
        ttl: int = 3600,
        max_value_size: int = 1024,
    ) -> None:
        """删除并重新创建 KV 桶（⚠️ 会清空所有数据）"""
        if self._nc is None:
            raise RuntimeError("未连接，请先调用 connect()")
        js = self._nc.jetstream()

        try:
            await js.delete_key_value(self._bucket_name)
            self.logger.info("🗑️  删除旧 KV 桶: %s", self._bucket_name)
        except nats.js.errors.Error:
            pass

        self._kv = await js.create_key_value(
            KeyValueConfig(
                bucket=self._bucket_name,
                history=history,
                ttl=ttl,
                max_value_size=max_value_size,
            )
        )
        self.logger.info("✅ 重新创建 KV 桶: %s", self._bucket_name)


# ── 使用示例 / 测试 ─────────────────────────────────────────

async def _demo() -> None:
    """演示 ChongmingCache 的完整用法（两种方式）"""
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )
    logger = logging.getLogger("chongming-cache-demo")

    # ════════════════════════════════════════════════════════
    # 方式一：async with 上下文管理器（推荐）
    # ─ 自动 connect / close，生命周期最安全
    # ════════════════════════════════════════════════════════
    logger.info("=" * 60)
    logger.info("📌 方式一：async with 上下文管理器（自动 connect/close）")
    logger.info("=" * 60)

    async with ChongmingCache(logger) as cache:
        # 写入
        await cache.put("feature.flag", b"true")
        await cache.put("timeout.sec", b"30")
        logger.info("✅ 写入两个键值对")

        # 读取
        entry = await cache.get("feature.flag")
        if entry:
            logger.info("feature.flag = %s (版本 %d)", entry.value.decode(), entry.revision) # type: ignore

        # 带版本号的更新（CAS）
        current = await cache.get("timeout.sec")
        if current:
            await cache.update("timeout.sec", b"60", current.revision) # type: ignore
            logger.info("✅ timeout.sec 已更新为 60")

        # subscribe 后台持续监听，写入新值自动触发回调
        async def on_flag_change(entry: KeyValue.Entry):
            logger.info("🔔 收到变更: %s = %s (版本 %d)", entry.key, entry.value.decode(), entry.revision) # type: ignore

        sub_task = await cache.subscribe("feature.flag", on_flag_change)
        logger.info("👂 已订阅 feature.flag，写入新值看效果...")

        # 写入新值 → subscribe 后台自动触发回调
        await cache.put("feature.flag", b"false")
        await asyncio.sleep(0.1)

        # 取消订阅，准备退出
        sub_task.cancel()

        # 历史版本
        logger.info("📜 feature.flag 的历史版本:")
        for entry in await cache.history("feature.flag"):
            logger.info("   版本 %d: %s", entry.revision, entry.value.decode()) # type: ignore

        # 删除
        await cache.delete("feature.flag")
        logger.info("✅ 已删除 feature.flag")

    # ════════════════════════════════════════════════════════
    # 方式二：手动 connect / close
    # ─ 适合需要精细控制连接生命周期的场景（如长期运行的服务）
    # ════════════════════════════════════════════════════════
    logger.info("")
    logger.info("=" * 60)
    logger.info("📌 方式二：手动管理生命周期（connect/close）")
    logger.info("=" * 60)

    cache = ChongmingCache(logger, bucket="demo_manual")
    try:
        await cache.connect()
        logger.info("✅ 手动连接成功")

        # 使用 cas_update 做原子更新（多进程安全）
        rev = await cache.cas_update("myapp.config.refresh_interval", b"30")
        logger.info("✅ cas_update 刷新间隔 = 30 (版本 %d)", rev)

        entry = await cache.get("myapp.config.refresh_interval")
        if entry:
            logger.info("读取到: %s = %s", entry.key, entry.value.decode()) # type: ignore

        # 批量写入
        revs = await cache.put_batch({
            "myapp.config.max_retry": b"3",
            "myapp.config.timeout": b"5000",
        })
        logger.info("✅ 批量写入 %d 个键", len(revs))

        # 列出所有键
        keys = await cache.keys()
        logger.info("📋 当前桶中所有键: %s", keys)

        # 检查键是否存在
        exists = await cache.exists("myapp.config.max_retry")
        logger.info("🔍 myapp.config.max_retry 是否存在: %s", exists)

    finally:
        await cache.close()
        logger.info("🔌 手动关闭连接")

    # ════════════════════════════════════════════════════════
    # 方式三：create() 多进程并发创建 — 仅一个成功
    # ════════════════════════════════════════════════════════
    logger.info("")
    logger.info("=" * 60)
    logger.info("📌 方式三：create() 多进程并发创建 — 仅一个成功")
    logger.info("=" * 60)

    @cas_retry(max_retries=3)
    async def init_app_config(cache: ChongmingCache, worker_id: int):
        """模拟多进程启动时同时初始化配置"""
        try:
            rev = await cache.create("app.init.lock", f"worker-{worker_id}".encode())
            logger.info("✅ worker-%d 创建成功 (版本 %d)", worker_id, rev)
            return True
        except KeyWrongLastSequenceError:
            logger.info("⏭️  worker-%d 发现 key 已存在，跳过初始化", worker_id)
            return False

    async with ChongmingCache(logger, bucket="demo_create") as c:
        # 先清除可能残留的 key
        if await c.exists("app.init.lock"):
            await c.delete("app.init.lock")

        logger.info("👥 模拟 5 个 worker 同时启动，尝试创建 app.init.lock...")
        results = await asyncio.gather(
            init_app_config(c, 1),
            init_app_config(c, 2),
            init_app_config(c, 3),
            init_app_config(c, 4),
            init_app_config(c, 5),
        )
        success = sum(1 for r in results if r)
        logger.info("📊 %d 个创建成功，%d 个跳过", success, len(results) - success)

    # ════════════════════════════════════════════════════════
    # 方式四（进阶）：@cas_retry 装饰器 + 并发更新
    # ════════════════════════════════════════════════════════
    logger.info("")
    logger.info("=" * 60)
    logger.info("📌 方式四（进阶）：@cas_retry 装饰器演示并发更新")
    logger.info("=" * 60)

    @cas_retry(max_retries=3)
    async def atomic_set_debug(cache: ChongmingCache, value: bytes):
        entry = await cache.get("debug.mode")
        if entry is None:
            await cache.put("debug.mode", value)
        else:
            await cache.update("debug.mode", value, entry.revision) # type: ignore

    async with ChongmingCache(logger, bucket="demo_retry") as cache:
        await atomic_set_debug(cache, b"true")
        logger.info("✅ @cas_retry 装饰器方式写入成功")

        # 模拟多进程并发：同时启动 3 个协程，共享同一个连接
        # 每个协程都尝试更新 shared.counter，CAS 自动处理冲突重试
        async def concurrent_updater(pid: int, c: ChongmingCache):
            for i in range(3):
                rev = await c.cas_update(
                    "shared.counter",
                    f"proc-{pid}-update-{i}".encode(),
                    max_retries=8,
                )
                logger.info("   🧵 进程 %d 第 %d 次更新成功 (版本 %d)", pid, i, rev)
                # await asyncio.sleep(0.05)

        async with ChongmingCache(logger, bucket="demo_concurrent") as c:
            # 先创建 key 的基础值
            await c.put("shared.counter", b"init")
            logger.info("👥 模拟 3 个进程并发更新 shared.counter（CAS 自动处理冲突）...")

            await asyncio.gather(
                concurrent_updater(1, c),
                concurrent_updater(2, c),
                concurrent_updater(3, c),
            )

            final = await c.get("shared.counter")
            if final:
                logger.info("✅ 最终 shared.counter = %s (版本 %d)", final.value.decode(), final.revision) # type: ignore

    logger.info("")
    logger.info("🎉 演示结束 — ChongmingCache 支持两种使用方式，且天然多进程安全！")


if __name__ == "__main__":
    asyncio.run(_demo())
