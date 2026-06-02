"""
Snowflake ID 生成器
=====================

基于雪花算法生成全局唯一的、趋势递增的 64 位整数 ID。

结构（共 64 位）:
```
 0 ─ 0000000000 0000000000 0000000000 0000000000 0 ─ 000000 ─ 000000000000
|─ 1 bit ─|──────── 41 bits 时间戳 (ms) ────────|─ 10 bits ─|─ 12 bits ─|
| 符号位   | 自定义起始纪元 2024-01-01 00:00:00  | 节点 ID   | 序列号     |
| 固定 0   | 最大可用至 2081 年                  | 0-1023    | 0-4095    |
```

特性：
- 全局唯一：不同 worker 节点分配不同节点 ID，不会冲突
- 趋势递增：基于时间戳，时间越晚 ID 越大
- 分布式友好：节点 ID 通过 NATS KV 自动注册与释放
- 高性能：纯内存计算，毫秒级最高生成 4096 个 ID

节点 ID 分配策略：
- 使用 NATS KV 桶 ``_worker_id_`` 中的键 ``snowflake.{node_id}`` 做 CAS 注册
- 启动时扫描 0-1023 寻找空位，用 ``create()`` 抢占
- 注册时写入当前 worker 名称 + 时间戳作为心跳
- 关闭时 ``delete()`` 释放 ID

使用方法::

    # 在 bootstrap.py 中初始化
    sf = SnowflakeGenerator(registration)
    await sf.register(app_name="user_auth")

    # 生成 ID
    user_id = sf.next_id()
"""

import time
import logging
from typing import Optional

logger = logging.getLogger("chongming.worker.user_auth.snowflake")


# ── 常量 ──────────────────────────────────────────────────────────

# 自定义起始纪元：2024-01-01 00:00:00 UTC
EPOCH = 1704067200000

# 各部分的位数
TIMESTAMP_BITS = 41
WORKER_ID_BITS = 10
SEQUENCE_BITS = 12

# 各部分的偏移量（等于右边部分的位数之和）
SEQUENCE_MASK = (1 << SEQUENCE_BITS) - 1          # 0xFFF = 4095
WORKER_ID_SHIFT = SEQUENCE_BITS                   # 12
TIMESTAMP_SHIFT = SEQUENCE_BITS + WORKER_ID_BITS  # 22

# 节点 ID 范围
MAX_WORKER_ID = (1 << WORKER_ID_BITS) - 1          # 1023


# ── Snowflake 生成器 ─────────────────────────────────────────────


class SnowflakeGenerator:
    """雪花算法 ID 生成器（线程安全）

    使用时需先调用 ``register()`` 注册节点 ID，然后调用 ``next_id()`` 生成 ID。
    """

    def __init__(self) -> None:
        self._worker_id: int = -1          # 待注册
        self._sequence: int = 0            # 当前毫秒序列号
        self._last_timestamp: int = -1     # 上次生成 ID 的时间戳

    # ── 属性 ──────────────────────────────────────────────────

    @property
    def worker_id(self) -> int:
        if self._worker_id == -1:
            raise RuntimeError("SnowflakeGenerator 尚未注册，请先调用 register()")
        return self._worker_id

    @property
    def is_registered(self) -> bool:
        return self._worker_id != -1

    @property
    def config(self) -> dict:
        """返回当前生成器的配置信息"""
        return {
            "worker_id": self._worker_id,
            "epoch": EPOCH,
            "timestamp_bits": TIMESTAMP_BITS,
            "worker_id_bits": WORKER_ID_BITS,
            "sequence_bits": SEQUENCE_BITS,
            "max_sequence": SEQUENCE_MASK,
        }

    # ── 节点注册 ─────────────────────────────────────────────

    async def register(
        self,
        app_name: str = "user_auth",
        cache=None,
        preferred_worker_id: Optional[int] = None,
    ) -> int:
        """注册节点 ID（通过 NATS KV CAS 抢占）

        当使用 ``cache=None`` 且未提供 ``preferred_worker_id`` 时，
        使用 **当前进程 PID % 1024** 作为节点 ID ——
        仅适用于单机开发环境。生产环境必须提供已连接到
        ``_worker_id_`` KV 桶的 cache 实例。

        :param app_name:  当前 worker 名称，用于注册信息标识
        :param cache:     ChongmingCache 实例（已连接到 ``_worker_id_`` 桶）
        :param preferred_worker_id: 首选节点 ID（可选），可用于 K8s StatefulSet
                                   pod 序号等场景

        :returns: 已注册的节点 ID
        :raises RuntimeError: 所有 1024 个节点 ID 都已占满
        """
        if cache is None:
            # 开发模式：使用 PID 作为节点 ID
            import os
            self._worker_id = os.getpid() % (MAX_WORKER_ID + 1)
            logger.warning(
                "Snowflake 使用 PID 作为节点 ID (worker_id=%d) — "
                "仅适用于单机开发环境",
                self._worker_id,
            )
            return self._worker_id

        # 如果有首选 node_id，先尝试
        if preferred_worker_id is not None:
            if await self._try_register(cache, app_name, preferred_worker_id):
                return self._worker_id

        # 扫描 0..1023 寻找可用 ID
        for node_id in range(MAX_WORKER_ID + 1):
            if await self._try_register(cache, app_name, node_id):
                return self._worker_id

        raise RuntimeError(
            f"所有 {MAX_WORKER_ID + 1} 个 Snowflake 节点 ID 已被占用，无法注册"
        )

    async def _try_register(
        self,
        cache,
        app_name: str,
        node_id: int,
    ) -> bool:
        """尝试注册一个节点 ID，成功返回 True"""
        key = f"snowflake.{node_id}"
        value = f"{app_name}|{time.time() * 1000:.0f}".encode()
        try:
            await cache.create(key, value)
            self._worker_id = node_id
            logger.info(
                "Snowflake 节点注册成功: worker_id=%d, app=%s",
                node_id,
                app_name,
            )
            return True
        except Exception:
            return False

    async def unregister(self, cache=None) -> None:
        """释放节点 ID（Worker 关闭时调用）"""
        if self._worker_id == -1:
            return

        if cache is not None:
            try:
                await cache.delete(f"snowflake.{self._worker_id}")
                logger.info(
                    "Snowflake 节点已释放: worker_id=%d",
                    self._worker_id,
                )
            except Exception as e:
                logger.warning(
                    "Snowflake 节点释放失败 (worker_id=%d): %s",
                    self._worker_id,
                    e,
                )
        self._worker_id = -1

    # ── ID 生成 ─────────────────────────────────────────────

    def next_id(self) -> int:
        """生成下一个唯一的 Snowflake ID

        线程安全：Python 的 GIL 保证 ``next_id()`` 调用天然原子，
        无需额外加锁。如需更高并发（如 asyncio 多协程），调用方
        可自行在外层加锁。

        :returns: 64 位唯一 ID
        :raises RuntimeError: 单毫秒内序列号耗尽（超过 4096）
        """
        timestamp = self._current_timestamp()

        if timestamp < self._last_timestamp:
            # 时钟回拨保护
            clock_back = self._last_timestamp - timestamp
            logger.warning(
                "检测到时钟回拨 %d ms，等待中...",
                clock_back,
            )
            self._wait_until(self._last_timestamp)
            timestamp = self._current_timestamp()

        if timestamp == self._last_timestamp:
            # 同一毫秒内，递增序列号
            self._sequence = (self._sequence + 1) & SEQUENCE_MASK
            if self._sequence == 0:
                # 序列号耗尽（4096 个/ms），等待下一毫秒
                self._wait_until(timestamp + 1)
                timestamp = self._current_timestamp()
        else:
            # 新的一毫秒，序列号归零
            self._sequence = 0

        self._last_timestamp = timestamp

        # 组装 ID
        snowflake_id = (
            ((timestamp - EPOCH) << TIMESTAMP_SHIFT)
            | (self._worker_id << WORKER_ID_SHIFT)
            | self._sequence
        )
        return snowflake_id

    # ── 内部工具 ─────────────────────────────────────────────

    @staticmethod
    def _current_timestamp() -> int:
        """获取当前毫秒时间戳"""
        return int(time.time() * 1000)

    @staticmethod
    def _wait_until(target_timestamp: int) -> None:
        """忙等待直到指定毫秒时间戳"""
        while int(time.time() * 1000) < target_timestamp:
            pass

    # ── ID 解析（调试用） ───────────────────────────────────

    @staticmethod
    def parse(snowflake_id: int) -> dict:
        """解析 Snowflake ID，返回各部分值（用于调试）

        用法::

            >>> SnowflakeGenerator.parse(1234567890123456)
            {
                "timestamp": 1712345678012,
                "datetime": "2024-04-06 12:34:38.012",
                "worker_id": 42,
                "sequence": 1234,
            }
        """
        sequence = snowflake_id & SEQUENCE_MASK
        worker_id = (snowflake_id >> WORKER_ID_SHIFT) & MAX_WORKER_ID
        timestamp = (snowflake_id >> TIMESTAMP_SHIFT) + EPOCH

        from datetime import datetime

        return {
            "timestamp": timestamp,
            "datetime": datetime.fromtimestamp(timestamp / 1000).strftime(
                "%Y-%m-%d %H:%M:%S.%f"
            )[:-3],
            "worker_id": worker_id,
            "sequence": sequence,
        }


# ── 全局实例 ─────────────────────────────────────────────────────

# 供 bootstrap.py 和其他模块导入使用
snowflake_generator: SnowflakeGenerator = SnowflakeGenerator()
