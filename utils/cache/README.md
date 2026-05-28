# chongming-cache — NATS JetStream KV 缓存客户端

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![NATS](https://img.shields.io/badge/NATS-JetStream-green.svg)](https://nats.io/)

基于 NATS JetStream KV Store 的缓存抽象层，为 Chongming 微服务体系提供分布式缓存能力。底层被 `chongming-lock` 等上层包依赖。

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

## 使用示例

```python
import asyncio
import logging
from chongming_cache import ChongmingCache

async def main():
    async with ChongmingCache(logger, bucket="my_bucket") as cache:
        # 写入
        await cache.put("key1", b"value1")

        # 读取
        value = await cache.get("key1")

        # 删除
        await cache.delete("key1")

asyncio.run(main())
```

---

## API 参考

### `ChongmingCache`

| 方法 | 说明 |
|------|------|
| `get(key)` | 读取键值 |
| `put(key, value)` | 写入键值 |
| `create(key, value)` | 原子创建（键不存在时成功） |
| `update(key, value, revision)` | CAS 更新（指定修订版本号） |
| `delete(key)` | 删除键值 |
| `keys()` | 列出所有键 |

---

## 架构位置

```
Your Application
       │
       ▼
chongming-lock (分布式锁)
       │
       ▼
chongming-cache (NATS JetStream KV)
       │
       ▼
NATS JetStream KV Store
```

---

## 依赖

- Python 3.12+
- `nats-py>=2.14.0`
