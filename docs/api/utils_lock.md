# Utils Lock — chongming-lock

**Package:** `chongming_lock`  
**Location:** `utils/lock/src/chongming_lock/`

基于 NATS JetStream KV 的分布式锁库，提供 6 种锁类型。所有锁均支持异步上下文管理器、可配置 TTL 与心跳续期、超时等待、过期自动抢夺。

---

## 锁类型

| 锁类型 | 类名 | 特点 | 适用场景 |
|--------|------|------|----------|
| 互斥锁 | `MutexLock` | 排他锁，同时仅一个持有者 | 资源独占访问 |
| 等待互斥锁 | `MutexLockWithWait` | 带等待队列通知 | 锁释放时广播通知等待者 |
| 读写锁 | `ReadWriteLock` | 读共享、写互斥 | 读多写少场景 |
| 信号量 | `SemaphoreLock` | 限制并发数 | 连接池、限流 |
| 可重入锁 | `ReentrantLock` | 同一实例可多次加锁 | 递归调用 |
| 租约锁 | `LeaseLock` | 带 TTL 自动释放 | Leader Election |
| 栅栏令牌锁 | `FencingTokenLock` | 防僵尸节点 | 数据一致性保护 |

---

## 核心锁 API

### `MutexLock`

```python
from chongming_lock import MutexLock

lock = MutexLock(cache, "resource-a", ttl=30)
async with lock(timeout=5.0):
    pass  # 独占访问
```

**构造参数：**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `cache` | ChongmingCache | — | 缓存实例 |
| `lock_name` | str | — | 锁名称 |
| `ttl` | float | 30.0 | TTL（秒） |
| `renew_interval` | float | 10.0 | 心跳续期间隔（秒） |
| `instance_id` | str | 自动 | 实例 ID |

**方法：** `acquire(timeout, blocking)` | `release()` | `fencing_token`

**原理：** 使用 KV `create()` CAS 原子操作实现互斥。

### `MutexLockWithWait`

基础 `MutexLock` + NATS Pub/Sub 通知机制。释放时发送通知，等待者立即重试而非轮询。

### `ReadWriteLock`

```python
rwlock = ReadWriteLock(cache, "shared-data", ttl=30)
async with rwlock.reader_lock():  # 读共享
async with rwlock.writer_lock():  # 写互斥
```

### `SemaphoreLock`

```python
sem = SemaphoreLock(cache, "api-rate-limit", max_count=3, ttl=30)
async with sem(timeout=5.0):
    pass
```

### `ReentrantLock`

```python
rlock = ReentrantLock(cache, "db-connection", ttl=30)
async with rlock:
    async with rlock:  # 可重入
        pass
```

### `LeaseLock`

```python
lease = LeaseLock(cache, "temporary-resource", ttl=10)
async with lease(timeout=3.0):
    pass  # 10 秒后自动释放
```

### `FencingTokenLock`

```python
fence = FencingTokenLock(cache, "critical-resource", ttl=30)
async with fence(timeout=5.0) as token:
    await write_with_fencing(token, data)
```

---

## `LockFactory`

```python
from chongming_lock import LockFactory

factory = LockFactory(cache)
mutex = factory.mutex("resource-a")
rwlock = factory.rwlock("resource-b")
semaphore = factory.semaphore("api-limit", max_count=5)
```

---

## 异常类型

| 异常 | 说明 |
|------|------|
| `LockError` | 锁操作基础异常 |
| `LockNotAcquiredError` | 未能获取锁 |
| `LockNotOwnedError` | 尝试释放不属于自己的锁 |
| `LockReleaseError` | 释放锁失败 |
| `LockStateError` | 锁状态异常 |
