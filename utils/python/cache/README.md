# chongming-cache — NATS JetStream KV 缓存客户端

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![NATS JetStream](https://img.shields.io/badge/NATS-JetStream-green.svg)](https://nats.io/)

基于 **NATS JetStream Key-Value Store** 的分布式缓存抽象层，为 Chongming 微服务体系提供 KV 存储能力。被 `chongming-lock` 等上层包依赖，支持多进程并发安全、跨进程实时通知和 CAS 乐观锁。

---

## 安装

```bash
uv add chongming-cache
```

或添加到 `pyproject.toml`：

```toml
[project]
dependencies = ["chongming-cache"]
```

---

## 快速开始

```python
import asyncio
import logging
from chongming_cache import ChongmingCache

logger = logging.getLogger(__name__)

async def main():
    async with ChongmingCache(logger, bucket="my_bucket") as cache:
        # 写入
        await cache.put("key1", b"value1")

        # 读取
        value = await cache.get("key1")
        print(f"value = {value.decode()}")  # → value1

        # 删除
        await cache.delete("key1")

asyncio.run(main())
```

---

## API 参考

### 构造

```python
# 推荐：上下文管理器（自动连接和关闭）
async with ChongmingCache(logger, bucket="my_cache") as cache:
    ...

# 手动管理生命周期
cache = ChongmingCache(logger, bucket="my_cache")
await cache.connect()
# ...
await cache.close()
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `logger` | `Logger` | — | 日志记录器 |
| `bucket` | `str` | `"app_config"` | KV 桶名称 |
| `nats_url` | `str` | 自动 | NATS 服务器地址（可选，优先于配置文件） |

### 核心 KV 操作

| 方法 | 说明 |
|------|------|
| `put(key, value)` | 写入键值对（upsert），返回 revision 版本号 |
| `create(key, value)` | 原子创建（仅键不存在时成功），并发安全的「创建锁」 |
| `get(key)` | 读取键值，不存在返回 `None` |
| `update(key, value, revision)` | **CAS 乐观锁更新**，基于版本号。冲突时抛 `KeyWrongLastSequenceError` |
| `cas_update(key, new_value, max_retries=5)` | 自动 CAS 重试：get → update → 重试 |
| `delete(key)` | 删除键 |
| `purge(key)` | 彻底清除键的所有历史记录 |
| `exists(key)` | 检查键是否存在 |

### 批量操作

| 方法 | 说明 |
|------|------|
| `put_batch(items: dict)` | 批量写入多个键值对 |
| `keys()` | 列出桶中所有键 |

### 监听与历史

| 方法 | 说明 |
|------|------|
| `watch(key=">")` | 监听键变化，返回异步迭代器 |
| `subscribe(key, callback, include_current=False)` | 订阅键变化，异步回调通知 |
| `history(key)` | 获取键的历史版本列表 |

**subscribe 示例：**

```python
async def on_change(entry):
    print(f"{entry.key} = {entry.value.decode()}")

task = await cache.subscribe("mykey", on_change)
# ... later ...
task.cancel()  # 停止监听
```

### 桶管理

| 方法 | 说明 |
|------|------|
| `recreate_bucket(history=5, ttl=3600, max_value_size=1024)` | 删除并重建 KV 桶（⚠️ 清空数据） |

---

## CAS 重试装饰器

```python
from chongming_cache import cas_retry

@cas_retry(max_retries=5)
async def update_value(cache, key, new_value):
    entry = await cache.get(key)
    if entry is None:
        await cache.put(key, new_value)
    else:
        await cache.update(key, new_value, entry.revision)
```

自动处理 `KeyWrongLastSequenceError`，支持指数退避重试。

---

## 架构位置

```
┌─────────────────────┐
│  Your Application   │
├─────────────────────┤
│  chongming-lock     │  6 种分布式锁
├─────────────────────┤
│  chongming-cache    │  NATS JetStream KV 封装
├─────────────────────┤
│  NATS JetStream KV  │  分布式 KV 存储
└─────────────────────┘
```

### 多进程并发安全

- **读写并发** — 每个进程独立 NATS 连接
- **CAS 乐观锁** — `update(key, value, revision)` 原子更新
- **Watch 跨进程通知** — 进程 A 修改后，进程 B 的 watcher 立即收到通知
- **连接隔离** — 每个进程独立连接，互不干扰

---

## 依赖

- Python 3.12+
- `nats-py>=2.14.0`
