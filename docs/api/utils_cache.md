# Utils Cache — chongming-cache

**Package:** `chongming_cache`  
**Location:** `utils/cache/src/chongming_cache/`  
**Entry Point:** `chongming_cache.ChongmingCache`

基于 NATS JetStream Key-Value Store 的分布式缓存抽象层，提供异步 KV 操作、CAS 乐观锁、跨进程 Watch 通知等能力。

---

## Core API

### `class ChongmingCache`

```python
class ChongmingCache:
    def __init__(self, logger, bucket: str = "app_config", nats_url: str = None):
        ...
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `logger` | Logger | — | 日志记录器 |
| `bucket` | str | `"app_config"` | KV 桶名称 |
| `nats_url` | str | 自动 | NATS 服务器地址 |

### KV 操作

| 方法 | 签名 | 说明 |
|------|------|------|
| `put` | `(key, value) → int` | 写入/覆盖键值对，返回 revision 版本号 |
| `create` | `(key, value) → int` | 原子创建（仅键不存在时成功），并发安全 |
| `get` | `(key) → Entry \| None` | 读取键值，不存在返回 `None` |
| `update` | `(key, value, revision) → int` | **CAS 乐观锁更新**，冲突抛异常 |
| `cas_update` | `(key, new_value, max_retries=5) → int` | 自动 CAS 重试 |
| `delete` | `(key)` | 删除键值 |
| `purge` | `(key)` | 彻底清除键的历史记录 |
| `exists` | `(key) → bool` | 检查键是否存在 |

### 批量与监听

| 方法 | 说明 |
|------|------|
| `put_batch(items: dict)` | 批量写入多个键值对 |
| `keys()` | 列出桶中所有键 |
| `watch(key=">")` | 监听键变化，返回异步迭代器 |
| `subscribe(key, callback, include_current=False)` | 订阅键变化，异步回调通知 |
| `history(key)` | 获取键的历史版本列表 |

### 桶管理

| 方法 | 说明 |
|------|------|
| `recreate_bucket(history=5, ttl=3600, max_value_size=1024)` | 删除并重建 KV 桶 |

---

## 模块结构

```
chongming_cache/
├── __init__.py         # 导出 ChongmingCache
├── cache.py            # ChungmingCache 核心实现
├── decorators.py       # @cas_retry 装饰器
├── exceptions.py       # 异常定义
└── entry.py            # Entry 数据结构
