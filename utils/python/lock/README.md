# 🔒 chongming-lock — 基于 NATS JetStream KV 的分布式锁库

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![NATS JetStream](https://img.shields.io/badge/NATS-JetStream-green.svg)](https://nats.io/)

提供 **6 种分布式锁类型**，所有锁均基于 `chongming-cache`（NATS JetStream KV）实现，天然支持多进程 / 多实例并发、崩溃自动恢复和心跳续期。

---

## 安装

```bash
uv add chongming-lock
```

---

## 快速开始

```python
import asyncio
import logging
from chongming_cache import ChongmingCache
from chongming_lock import MutexLock

logging.basicConfig(level=logging.INFO)

async def main():
    async with ChongmingCache(logger, bucket="my_locks") as cache:
        # 获取分布式互斥锁，超时 5 秒
        async with MutexLock(cache, "resource-a", ttl=30)(timeout=5.0):
            print("独占访问 resource-a")

asyncio.run(main())
```

---

## 锁类型一览

| 锁类型 | 类名 | 特点 | 适用场景 |
|--------|------|------|----------|
| 🥇 **互斥锁** | `MutexLock` | 同一时刻只有一个持有者 | 资源独占访问 |
| 📖 **读写锁** | `ReadWriteLock` | 读共享、写互斥 | 读多写少场景 |
| 🔢 **信号量** | `SemaphoreLock` | 限制最大并发数 | 连接池、限流 |
| 🔁 **可重入锁** | `ReentrantLock` | 同一实例可多次加锁 | 递归调用 |
| ⏱️ **租约锁** | `LeaseLock` | 带 TTL 自动释放 | Leader Election |
| 🛡️ **栅栏令牌锁** | `FencingTokenLock` | 单调递增令牌，防僵尸节点 | 数据一致性保护 |

---

## 详细用法

### MutexLock — 互斥锁

基于 KV `create()` 原子操作实现，最基础、最高频使用的锁。

```python
from chongming_lock import MutexLock

lock = MutexLock(cache, "my-resource", ttl=30)

# async with 自动管理生命周期
async with lock(timeout=5.0):
    await do_something()

# 手动管理
await lock.acquire(timeout=5.0)
try:
    await do_something()
finally:
    await lock.release()

# 非阻塞尝试
if await lock.acquire(blocking=False):
    try:
        await do_something()
    finally:
        await lock.release()
```

**特性：** 🔄 后台心跳续期 | 💀 崩溃自动过期 | 🏷️ 实例唯一 ID 追踪

---

### ReadWriteLock — 读写锁

读锁可多实例同时持有，写锁需等待所有读锁释放。

```python
from chongming_lock import ReadWriteLock

rwlock = ReadWriteLock(cache, "shared-data", ttl=30)

# 读锁 — 可并发
async with rwlock.reader(timeout=5.0):
    data = read_from_storage()

# 写锁 — 互斥
async with rwlock.writer(timeout=5.0):
    write_to_storage(new_data)
```

**特性：** 📖 读并发 | ✍️ 写互斥 | 💀 过期自动抢夺

---

### SemaphoreLock — 信号量

限制同时访问资源的实例数量。

```python
from chongming_lock import SemaphoreLock

sem = SemaphoreLock(cache, "db-pool", max_count=5, ttl=30)

async def query(idx):
    async with sem(timeout=10.0):
        await db.execute()

# 10 个任务最多 5 个并发
await asyncio.gather(*[query(i) for i in range(10)])
```

额外 API：

```python
# 当前活跃持有者
for h in await sem.get_active_holders():
    print(f"  - {h['instance_id']} (expires: {h['expires_at']})")

# 当前可用额度
available = await sem.available_permits_remote()
print(f"可用: {available}/{sem.max_count}")
```

**特性：** 🔢 精确限流 | 🧹 自动清理过期持有者 | 📊 可查询状态

---

### ReentrantLock — 可重入锁

同一实例可多次获取同一把锁，避免递归死锁。

```python
from chongming_lock import ReentrantLock

rlock = ReentrantLock(cache, "my-resource", ttl=30)

async def outer():
    async with rlock(timeout=5.0):
        await inner()  # 不会死锁！

async def inner():
    async with rlock(timeout=5.0):
        pass

await outer()
```

**特性：** 🔁 同一实例可重入 | 🔢 重入计数 `rlock.reentrant_count` | 💀 过期自动抢夺

---

### LeaseLock — 租约锁

带 TTL 的锁，持有者在租约期内工作，到期自动释放。适合 Leader Election。

```python
from chongming_lock import LeaseLock

lease = LeaseLock(cache, "leader-election", ttl=30)

async with lease(timeout=5.0):
    # 当前节点是 leader
    while lease.is_acquired and lease.remaining_lease_time > 5:
        await do_leader_work()
        await asyncio.sleep(5)
```

额外 API：

```python
info = await lease.get_lease_info()
print(f"持有者: {info['holder']}")
print(f"剩余时间: {info['remaining_seconds']:.1f}s")
print(f"续期次数: {info['renew_count']}")
```

**特性：** ⏱️ 到期自动释放 | ❤️ 后台续期 | 📊 可查询状态

---

### FencingTokenLock — 栅栏令牌锁

**解决僵尸节点问题：** 每次获取锁生成严格单调递增的令牌，数据库记录最高令牌值，拒绝过期写入。

```python
from chongming_lock import FencingTokenLock

ft_lock = FencingTokenLock(cache, "db-write-lock", ttl=30)

async with ft_lock(timeout=5.0):
    token = ft_lock.fencing_token  # 单调递增令牌
    await db.write_with_fencing(data, token)
```

数据库端 fence 验证：

```sql
UPDATE resource_with_fence
SET data = $1, last_fencing_token = $2
WHERE id = 1 AND last_fencing_token < $2;
-- affected_rows == 0 → 拒绝
```

**特性：** 🔢 单调递增令牌 | 🛡️ 防止僵尸节点 | 💀 过期自动抢夺

---

## LockFactory — 工厂模式

```python
from chongming_lock import LockFactory

factory = LockFactory(cache)

async with factory.mutex("resource", ttl=30)(timeout=5.0):
    pass

async with factory.rwlock("config", ttl=30).reader(timeout=5.0):
    pass

async with factory.semaphore("pool", max_count=10)(timeout=5.0):
    pass

async with factory.reentrant("recursive", ttl=30)(timeout=5.0):
    pass

async with factory.lease("leader", ttl=30)(timeout=5.0):
    pass

async with factory.fencing_token("fenced-write", ttl=30)(timeout=5.0):
    token = factory.fencing_token
```

---

## 通用参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `cache` | `ChongmingCache` | — | 已连接缓存实例 |
| `lock_name` | `str` | — | 锁名称（同名锁互斥） |
| `ttl` | `float` | `30.0` | TTL（秒），超时自动释放 |
| `renew_interval` | `float` | `10.0` | 心跳续期间隔，应 < TTL/2 |
| `instance_id` | `str` | 自动 | 实例唯一 ID（hostname:pid:uuid） |

## 异常处理

```python
from chongming_lock import (
    LockNotAcquiredError,    # 获取锁超时或失败
    LockNotOwnedError,       # 释放不属于自己的锁
    LockReleaseError,        # 释放操作失败
    LockStateError,          # 状态异常
)
```

---

## 架构设计

```
┌───────────────────────────────────────┐
│          Your Application             │
├───────────────────────────────────────┤
│  chongming-lock — 6 种锁类型           │
├───────────────────────────────────────┤
│  chongming-cache — NATS JetStream KV  │
├───────────────────────────────────────┤
│  NATS Cluster — 多节点高可用           │
└───────────────────────────────────────┘
```

### 工作原理

1. **基于 NATS JetStream KV**：分布式 KV 存储实现锁持久化和同步
2. **CAS 乐观锁**：`create()` / `update()` 原子操作保证互斥
3. **后台心跳续期**：持有者定期续期，崩溃后自动释放
4. **过期抢夺**：锁过期后其他实例可 CAS 抢夺
5. **实例 ID**：全局唯一 ID 确保锁归属确认

---

## 最佳实践

1. **选择合适的 TTL**：大于业务处理时间，尽量小以便崩溃后快速恢复
2. **设置 timeout**：避免死等
3. **使用 `async with`**：自动管理生命周期
4. **Fencing 保护写操作**：重要数据使用 `FencingTokenLock`
5. **信号量使用后释放**：`async with` 自动处理

---

## 依赖

- Python 3.12+
- `nats-py>=2.14.0`
- `chongming-config`
- `chongming-cache`
