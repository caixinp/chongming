# Utils Worker — chongming-worker (Python)

**Package:** `chongming_worker`  
**Location:** `utils/worker/src/chongming_worker/`  
**Entry Point:** `chongming_worker.worker_lifespan.WorkerLifespan`

自动处理 Worker 生命周期管理的 Python 框架，包括 NATS 连接与重连、服务注册与心跳、消息分发与参数解析、优雅关闭。

---

## `class WorkerLifespan`

### 构造

```python
from chongming_worker.worker_lifespan import WorkerLifespan

app = WorkerLifespan("config.toml")
```

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `config_path` | str | `"config.toml"` | 配置文件路径 |

### `@app.handler(subject="")` 装饰器

将 async 函数注册为指定 subject 的消息处理器。

```python
@app.handler("calc.add")
async def add(a: float, b: float) -> dict:
    result = a + b
    return {"result": result, "operation": "add", "timestamp": time.time()}
```

**参数：**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `subject` | str | `""` | NATS subject。未指定时从配置推断，再回退为函数名 |

### 生命周期方法

| 方法 | 说明 |
|------|------|
| `start()` | 启动 worker：连接 NATS、注册、订阅、开始心跳 |
| `shutdown()` | 优雅关闭：取消心跳、取消订阅、注销、关闭 NATS |
| `run()` | 同步入口：启动事件循环并运行 worker，等待 SIGINT/SIGTERM |

---

### 主动通讯 API

| 方法 | 说明 |
|------|------|
| `publish(subject, data)` | 向 subject 发布消息（发布-订阅模式，异步通知其他 worker） |
| `request(subject, data, timeout=5.0)` | 向 subject 发送请求并等待响应（请求-回复模式，同步调用其他 worker） |
| `nats_connection` (属性) | 获取原始 NATS 连接对象，用于自定义 NATS 操作 |

**`publish(subject, data)`** — 异步广播

```python
# 在 handler 中通过 _app 参数注入的 WorkerLifespan 实例调用
await _app.publish("notification.order_created", {
    "order_id": "ord_123",
    "user_id": "u001",
    "user_name": "Alice",
    "item": "laptop",
    "amount": 999.99,
    "timestamp": time.time(),
})
```

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `subject` | str | — | NATS subject |
| `data` | dict/list/str/int/float/bool/None | — | 要发布的数据（JSON 序列化） |

**`request(subject, data, timeout=5.0)`** — 同步调用

```python
# 调用其他 worker 的服务并等待响应
try:
    user_info = await _app.request("user.query", {"user_id": "u001"}, timeout=3.0)
    logger.info("User info: %s", user_info)
except asyncio.TimeoutError:
    logger.warning("Request timed out, using defaults")
    user_info = {"name": "Unknown", "balance": 0.0}
except ValueError as e:
    logger.error("Business error: %s", e)
```

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `subject` | str | — | 目标 handler 的 subject |
| `data` | dict/list/str/int/float/bool/None | — | 请求数据（JSON 序列化） |
| `timeout` | float | 5.0 | 超时时间（秒） |

**异常：**
- `ValueError` — 目标 worker 返回的业务错误
- `asyncio.TimeoutError` — 超时未收到响应
- `RuntimeError` — NATS 未连接

---

## 参数自动注入

框架支持通过保留参数名自动注入以下对象：

| 参数名 | 注入对象 | 用途 |
|--------|----------|------|
| `_app` | `WorkerLifespan` 实例 | 调用 `_app.publish()` / `_app.request()` / `_app.nats_connection` |
| `_nc` | NATS 连接对象 | 直接执行底层 NATS 操作 |

这些参数**不需要客户端传入**，框架在调用 handler 时自动填充。

**示例：**

```python
@app.handler("order.create")
async def create_order(user_id: str, amount: float, _app: WorkerLifespan) -> dict:
    """_app 参数由框架自动注入"""
    user_info = await _app.request("user.query", {"user_id": user_id})
    await _app.publish("notification.order_created", {"order_id": "..."})
    return {"order_id": "ord_123", "user": user_info}

@app.handler("user.health_check")
async def health_check(_nc) -> dict:
    """_nc 参数由框架自动注入"""
    is_connected = _nc.is_connected if hasattr(_nc, 'is_connected') else False
    return {"status": "healthy" if is_connected else "unhealthy"}
```

---

## 消息分发流程

```
NATS Queue Group
    │
    ├── _dispatch_message(msg)
    │       │
    │       ├── 提取 request_id → set_request_id() （分布式追踪）
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
# 批量心跳（每 3 次心跳周期）
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

**批量心跳携带完整注册信息 items，Gateway 重启后可通过 items 自动恢复路由。**

---

## NATS 连接回调

| 回调 | 说明 |
|------|------|
| `_on_error(e)` | NATS 错误回调 |
| `_on_disconnected()` | NATS 断开回调 |
| `_on_reconnected()` | NATS 重连回调 — 自动重新发送注册消息 |
| `_on_closed()` | NATS 连接关闭回调 |

---

## 模块结构

```
chongming_worker/
├── __init__.py
├── worker_lifespan.py    # WorkerLifespan 核心实现
└── config_model.py       # 配置模型定义
