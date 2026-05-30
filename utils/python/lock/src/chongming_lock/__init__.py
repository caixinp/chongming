"""🔒 Chongming Lock — 基于 NATS JetStream KV 的分布式锁库

提供多种分布式锁类型，所有锁均基于 NATS JetStream KV 实现：
- **MutexLock** — 互斥锁（最基础的排他锁）
- **MutexLockWithWait** — 带等待通知的互斥锁
- **ReadWriteLock** — 读写锁（读共享、写互斥）
- **SemaphoreLock** — 信号量（限制并发数）
- **ReentrantLock** — 可重入锁（同一实例可多次加锁）
- **LeaseLock** — 租约锁（带 TTL 自动释放）
- **FencingTokenLock** — 栅栏令牌锁（防止僵尸节点）

所有锁均支持：
- 异步上下文管理器 ``async with``
- 可配置 TTL 与心跳续期
- 超时等待
- 过期自动抢夺（锁持有者崩溃后自动恢复）
- ``LockFactory`` 工厂模式快速创建
"""

from __future__ import annotations

from ._base import (
    ChongmingLock,
    LockFactory,
    _generate_instance_id,
    _encode_lock_key,
    _encode_lock_data,
    _decode_lock_data,
)
from ._exceptions import (
    LockError,
    LockNotAcquiredError,
    LockNotOwnedError,
    LockReleaseError,
    LockStateError,
)
from ._mutex import MutexLock, MutexLockWithWait
from ._rwlock import ReadWriteLock, _ReaderLock, _WriterLock
from ._semaphore import SemaphoreLock
from ._reentrant import ReentrantLock
from ._lease import LeaseLock
from ._fencing_token import FencingTokenLock

__version__ = "0.1.0"

__all__ = [
    # 基类
    "ChongmingLock",
    "LockFactory",

    # 锁类型
    "MutexLock",
    "MutexLockWithWait",
    "ReadWriteLock",
    "SemaphoreLock",
    "ReentrantLock",
    "LeaseLock",
    "FencingTokenLock",

    # 异常
    "LockError",
    "LockNotAcquiredError",
    "LockNotOwnedError",
    "LockReleaseError",
    "LockStateError",

    # 工具函数
    "_generate_instance_id",
    "_encode_lock_key",
    "_encode_lock_data",
    "_decode_lock_data",
]
