# chongming-worker — Worker 生命周期框架（Python）

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![NATS](https://img.shields.io/badge/NATS-2.10-green.svg)](https://nats.io/)

Chongming 微服务体系的 **Python Worker 生命周期管理框架**。自动处理 NATS 连接与重连、服务注册、心跳保活、消息分发和优雅关闭，开发者只需关注纯业务逻辑函数。

---

## 快速开始（3 分钟）

### 1. 安装

```bash
uv add chongming-worker
```

### 2. 创建 Handler

```python
# app/handlers/hello.py
from chongming_worker.worker_lifespan import WorkerLifespan

app = WorkerLifespan("config.toml")

@app.handler("hello.world")
async def hello(name: str) -> dict:
    """说你好"""
    return {"message": f"Hello, {name}!", "timestamp": time.time()}
```

### 3. 启动

```python
# main.py
from app.bootstrap import app
app.run()
```

### 4. 配置

```toml
# config.toml — Worker 唯一配置文件
[worker]
name = "my-worker"

[nats]
urls = ["nats://localhost:4222"]

[registration]
service = "my-worker"
heartbeat_interval = 15
items = [
    {
        subject = "hello.world",
        method = "GET",
        path = "/hello",
        params = ["name: str"],
        response_model = {
            message = ["str", "__required__"],
            timestamp = ["float", 0.0]
        }
    }
]
```

就是这样！启动后 Worker 会自动连接 NATS、注册路由到 Gateway，开始处理请求。

---

## Worker 生命周期详解

### 启动流程

```
config.toml 加载
      │
      ▼
  ┌─────────────────┐
  │  WorkerLifespan  │  ← 解析配置、校验 TTL > heartbeat_interval
  │  构造函数         │
  └─────────┬───────┘
            │  app = WorkerLifespan("config.toml")
            ▼
  ┌─────────────────┐
  │  @app.handler()  │  ← 装饰器注册 handler（可以有多个）
  │  注册 handler    │
  └─────────┬───────┘
            │  @app.handler("calc.add")
            ▼
  ┌─────────────────┐
  │  app.run()      │  ← 进入事件循环
  └─────────┬───────┘
            │
            ▼
  ┌─────────────────────┐
  │  app.start()         │
  │  ├─ 连接 NATS 集群    │
  │  ├─ 注册当前服务      │  ← 发注册消息到 service.registry
  │  ├─ 订阅所有 subject  │  ← 开始监听消息
  │  └─ 启动心跳定时器    │  ← 每 heartbeat_interval 秒发一次心跳
  └─────────┬───────────┘
            │
            ▼
  ┌─────────────────────┐
  │  循环处理消息         │
  │  ├─ 收到 NATS 请求    │
  │  ├─ 解析参数          │
  │  ├─ 调用 handler      │  ← 你的业务代码在这里执行
  │  └─ 返回响应          │
  └─────────────────────┘
```

### 关闭流程

```
收到 SIGTERM / SIGINT
      │
      ▼
  ┌─────────────────────┐
  │  app.shutdown()      │
  │  ├─ 停止心跳          │  ← 停止定时器
  │  ├─ 取消所有订阅      │  ← 取消 NATS 订阅
  │  ├─ 注销当前服务      │  ← 通知 Gateway 移除路由
  │  └─ 关闭 NATS 连接    │  ← 断开与 NATS 集群的连接
  └─────────────────────┘
```

### 连接重连

NATS 断开后，框架会自动重连，重连后自动重新注册服务和订阅：

```
NATS 断开
      │
      ▼
  ┌──────────────────┐
  │  _on_disconnected │  ← 日志警告
  └────────┬─────────┘
           ▼
  ┌──────────────────┐
  │  NATS 自动重连     │  ← NATS 客户端内部机制
  └────────┬─────────┘
           ▼
  ┌──────────────────┐
  │  _on_reconnected  │  ← 重新注册服务 + 重新订阅
  └──────────────────┘
```

---

## Handler 开发指南

### 基本 Handler

```python
@app.handler("calc.add")
async def add(a: float, b: float) -> dict:
    """加法运算：参数名与 config.toml 的 params 一一对应"""
    return {"result": a + b, "operation": "add", "timestamp": time.time()}
```

**规则：**
- 函数名不限，但建议与 subject 对应
- **参数名必须**与 config.toml 中 `params` 定义一致
- **类型注解**用于自动类型转换
- 返回 `dict`，按 config.toml 的 `response_model` 结构返回
- 函数中可使用 `_app` 和 `_nc` 参数（见下文）

### 服务间通信（`_app` 注入）

框架会自动注入 `_app` 参数，通过它可以调用其他 Worker 的 handler 或发送广播通知：

```python
@app.handler("order.create")
async def create_order(
    user_id: str,
    amount: float,
    item: str,
    _app: WorkerLifespan,  # ← 框架自动注入
) -> dict:
    # 同步请求：调用另一个 Worker 的 handler
    user = await _app.request("user.query", {"user_id": user_id})
    
    # 异步广播：通知其他服务
    await _app.publish("notification.order_created", {
        "order_id": order_id,
        "user_id": user_id,
        "item": item,
        "amount": amount,
    })
    
    return {"order_id": order_id, "user": user, ...}
```

### 原始 NATS 连接（`_nc` 注入）

需要直接操作 NATS 连接时，使用 `_nc` 参数：

```python
@app.handler("user.health_check")
async def health_check(_nc: Nats) -> dict:
    """获取当前连接的 NATS 服务器信息"""
    server_info = _nc._nats_connected_server
    return {
        "status": "healthy",
        "nats_server": str(server_info),
        "timestamp": time.time(),
    }
```

### 参数自动解析规则

当 NATS 消息到达时，框架按以下规则解析参数：

1. **消息体是 dict** → 按参数名从 dict 中提取，按类型注解自动转换
2. **消息体不是 dict** → 作为唯一参数传入（如果 handler 只有一个参数）
3. **参数注入** → `_app` 和 `_nc` 由框架自动注入，不占用参数位置

---

## 心跳机制

Worker 启动后，会定期向 Gateway 发送心跳，告知自己仍然存活。

### 心跳类型

| 心跳类型 | 发送频率 | 内容 |
|----------|----------|------|
| **批量心跳** | 每 3 次心跳周期 | 携带完整的注册信息（所有 items），Gateway 重启后可自动恢复路由 |
| **普通心跳** | 其他周期 | 仅携带服务名和 subject |

### 关键配置

```toml
[registration]
heartbeat_interval = 15   # 心跳间隔（秒）
```

> **⚠️ TTL 必须大于心跳间隔**，否则路由会在下次心跳到来前被 Gateway 清理。
> 建议 TTL ≥ 心跳间隔 × 3（如心跳 15s，TTL 设为 60s）。

---

## API 参考

### `WorkerLifespan(config_path)`

创建 Worker 实例。

```python
app = WorkerLifespan(config_path: str = "config.toml")
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `config_path` | `str` | `"config.toml"` | 配置文件路径 |

#### 配置校验

构造函数中自动校验：
- TTL 是否大于 `heartbeat_interval`
- 若 TTL 不足，发出警告并建议最小值

---

### `@app.handler(subject)`

装饰器：注册消息处理器。

```python
@app.handler(subject: str)
async def handler(...):
    ...
```

| 参数 | 说明 |
|------|------|
| `subject` | NATS subject（必填）。未指定时从配置推断，再回退为函数名 |

**参数注入：**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| `_app` | `WorkerLifespan` | 框架实例，用于 `_app.request()` 和 `_app.publish()` |
| `_nc` | `Nats` | 原始 NATS 连接 |

---

### `app.run()`

同步入口：启动事件循环并运行 Worker。

```python
if __name__ == "__main__":
    app.run()
```

自动注册 SIGINT/SIGTERM 信号处理。

---

### `app.start()`

异步启动 Worker。

```python
await app.start()
```

执行顺序：
1. 连接 NATS
2. 注册服务到 Gateway
3. 订阅所有 handler 的 subject
4. 启动心跳

---

### `app.shutdown()`

异步关闭 Worker。

```python
await app.shutdown()
```

执行顺序：
1. 停止心跳
2. 取消所有订阅
3. 注销服务
4. 关闭 NATS 连接

---

### `app.request(subject, data)`

同步调用其他 Worker 的 handler（NATS Request-Reply）。

```python
result = await app.request("user.query", {"user_id": "u001"})
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `subject` | `str` | 目标 handler 的 subject |
| `data` | `dict` | 请求参数 |

---

### `app.publish(subject, data)`

异步广播消息（NATS Publish），不等待响应。

```python
await app.publish("notification.order_created", {"order_id": "xxx"})
```

---

## 配置参考

完整配置说明见 [CLI README — Worker config.toml 配置详解](../../cli/README.md#worker-configtoml-配置详解)。

---

## 完整示例

```python
import time
from chongming_worker.worker_lifespan import WorkerLifespan

app = WorkerLifespan("config.toml")

@app.handler("calc.add")
async def add(a: float, b: float) -> dict:
    return {"result": a + b, "operation": "add", "timestamp": time.time()}

@app.handler("calc.subtract")
async def subtract(a: float, b: float) -> dict:
    return {"result": a - b, "operation": "subtract", "timestamp": time.time()}

@app.handler("user.query")
async def user_query(user_id: str, _app: WorkerLifespan) -> dict:
    """查询用户信息（被其他 handler 通过 _app.request() 调用）"""
    return {"user_id": user_id, "name": "Alice", "balance": 100.0}

@app.handler("order.create")
async def create_order(user_id: str, amount: float, item: str, _app: WorkerLifespan) -> dict:
    """创建订单（演示 _app.request + _app.publish）"""
    # 1. 调用 user.query 获取用户信息
    user = await _app.request("user.query", {"user_id": user_id})
    
    order_id = f"ORD-{int(time.time())}"
    
    # 2. 广播通知
    await _app.publish("notification.order_created", {
        "order_id": order_id, "user_id": user_id, "item": item, "amount": amount,
    })
    
    return {"order_id": order_id, "user": user, "item": item, "amount": amount, "status": "created"}

@app.handler("notification.order_created")
async def on_order_created(order_id: str, user_id: str, item: str, amount: float, timestamp: float) -> dict:
    """处理订单创建通知（通过 publish 触发）"""
    print(f"收到通知：订单 {order_id} 已创建")
    return {"status": "notified", "message": f"Order {order_id} processed"}

@app.handler("system.info")
async def system_info(_app: WorkerLifespan) -> dict:
    """查看系统信息（演示 _app 注入）"""
    return {
        "status": "ok",
        "worker_name": _app.config["worker"]["name"],
        "registered_subjects": list(_app._handlers.keys()),
        "heartbeat_interval": _app.config["registration"]["heartbeat_interval"],
        "timestamp": time.time(),
    }

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
