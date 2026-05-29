# chongming-worker — Worker 生命周期框架（Python）

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![NATS](https://img.shields.io/badge/NATS-2.10-green.svg)](https://nats.io/)

Chongming 微服务体系的 **Python Worker 生命周期管理框架**。自动处理 NATS 连接与重连、服务注册、心跳保活、消息分发和优雅关闭，开发者只需关注纯业务逻辑函数。

---

## 核心能力

| 能力 | 说明 |
|------|------|
| ✅ NATS 连接与重连 | 自动连接 NATS 集群，断线自动重连并重新注册 |
| ✅ 服务注册 | 启动时自动向 Gateway 注册路由（`service.registry`） |
| ✅ 心跳保活 | 定期发送心跳（批量 + 单个），防止路由被清理 |
| ✅ 消息分发与参数解析 | 自动解析 NATS 消息参数并调用处理函数 |
| ✅ 优雅关闭 | SIGINT/SIGTERM 时自动注销并关闭连接 |
| ✅ 负载均衡 | 通过 NATS Queue Group 分发请求 |

---

## 安装

```bash
uv add chongming-worker
```

---

## 快速开始

```python
from chongming_worker.worker_lifespan import WorkerLifespan
import time

# 1. 创建应用实例（自动加载 config.toml）
app = WorkerLifespan("config.toml")

# 2. 注册消息处理函数
@app.handler("calc.add")
async def add(a: float, b: float) -> dict:
    """加法运算"""
    return {
        "result": a + b,
        "operation": "add",
        "timestamp": time.time(),
    }

# 3. 启动
if __name__ == "__main__":
    app.run()
```

---

## API 参考

### `WorkerLifespan`

```python
app = WorkerLifespan(config_path: str = "config.toml")
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `config_path` | `str` | `"config.toml"` | 配置文件路径 |

从配置读取心跳间隔（默认 15 秒），自动校验 TTL 配置。

#### `handler(subject: str)`

装饰器：将 async 函数注册为指定 NATS subject 的消息处理器。

```python
@app.handler("calc.add")
async def handler(a: float, b: float) -> dict:
    ...
```

| 参数 | 说明 |
|------|------|
| `subject` | NATS subject。未指定时从配置推断，再回退为函数名 |

**处理器函数要求：**
- 参数名与配置中 `registration.items[].params` 一一对应
- 函数参数的类型注解用于自动类型转换（如 `a: float`）
- 返回 `dict`，按 `response_model` 结构返回数据

#### `run()`

同步入口：启动事件循环并运行 Worker。自动注册 SIGINT/SIGTERM 信号处理。

```python
if __name__ == "__main__":
    app.run()
```

#### `start()`

异步启动 Worker：连接 NATS → 注册服务 → 订阅主题 → 开始心跳。

```python
await app.start()
```

#### `shutdown()`

异步关闭 Worker：取消心跳 → 取消订阅 → 注销服务 → 关闭 NATS 连接。

```python
await app.shutdown()
```

---

## 消息分发流程

```
NATS Queue Group
    │
    ├── _dispatch_message(msg)
    │       │
    │       ├── 提取 request_id → set_request_id()   ← 分布式追踪
    │       │
    │       ├── JSON 解析参数
    │       │   ├── dict → 按参数名映射，按类型注解自动转换
    │       │   └── 非 dict → 作为唯一参数传入
    │       │
    │       ├── 调用业务 handler
    │       │
    │       └── JSON 序列化结果 → msg.respond()（回传 request_id）
    │
    └── _dispatch_auto_from_config(msg)  # 兜底：无 handler 时返回错误
```

---

## 心跳机制

```python
# 批量心跳（每 3 次心跳周期，携带完整注册信息）
{
    "type": "heartbeat",
    "service": "example",
    "subjects": ["calc.add", "calc.subtract", ...],
    "items": [/* 完整路由信息 */],
    "router_prefix": "/calc",
    "tags": ["calc"]
}

# 单个心跳（其他周期）
{
    "type": "heartbeat",
    "service": "example",
    "subject": "calc.add"
}
```

> **重要：** 批量心跳携带完整注册信息 items，Gateway 重启后可通过 items 自动恢复路由，替代了原先定期 `type=register` 触发路由删除重建的不稳定方式。

---

## 配置示例

```toml
[worker]
name = "example"
version = "0.1.0"
description = "chongming worker example"

[nats]
urls = [
    "nats://localhost:4222",
    "nats://localhost:4223",
    "nats://localhost:4224",
]

[registration]
type = "register"
service = "calc"
queue_group = "calc-workers"
router_prefix = "/calc"
tags = ["calculator"]
heartbeat_interval = 15
items = [
    {
        subject = "calc.add",
        method = "GET",
        path = "/add",
        params = ["a: float", "b: float"],
        ttl = 60,
        timeout = 2.0,
        [items.response_model]
        result = "float"
        operation = "str"
        timestamp = "float"
    }
]
```

---

## 配置校验

框架在初始化时自动校验配置合理性：
- **TTL 必须大于心跳间隔**，否则路由会在心跳到来前被清理
- TTL 不足时发出警告，建议 TTL ≥ 心跳间隔 × 3

---

## NATS 连接回调

| 回调 | 说明 |
|------|------|
| `_on_error(e)` | NATS 错误回调 |
| `_on_disconnected()` | NATS 断开回调 |
| `_on_reconnected()` | NATS 重连回调 — 自动重新发送注册消息 |
| `_on_closed()` | NATS 连接关闭回调 |

---

## 完整示例

```python
import logging
import time
from chongming_worker.worker_lifespan import WorkerLifespan

app = WorkerLifespan("config.toml")

@app.handler("calc.add")
async def add(a: float, b: float) -> dict:
    return {"result": a + b, "operation": "add", "timestamp": time.time()}

@app.handler("calc.subtract")
async def subtract(a: float, b: float) -> dict:
    return {"result": a - b, "operation": "subtract", "timestamp": time.time()}

@app.handler("calc.multiply")
async def multiply(a: float, b: float) -> dict:
    return {"result": a * b, "operation": "multiply", "timestamp": time.time()}

@app.handler("calc.divide")
async def divide(a: float, b: float) -> dict:
    if b == 0:
        raise ValueError("除数不能为 0")
    return {"result": a / b, "operation": "divide", "timestamp": time.time()}

if __name__ == "__main__":
    app.run()
```

---

## 依赖

| 包 | 用途 |
|------|------|
| **chongming-config** | TOML 配置加载 |
| **chongming-logging** | 统一日志配置 |
| **nats-py** | NATS 消息队列客户端 |
