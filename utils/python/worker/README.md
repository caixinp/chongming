# chongming-worker — Worker 生命周期框架（Python）

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![NATS](https://img.shields.io/badge/NATS-2.10-green.svg)](https://nats.io/)

Chongming 微服务体系的 **Python Worker 生命周期管理框架**。自动处理 NATS 连接与重连、服务注册、心跳保活、消息分发和优雅关闭，开发者只需关注纯业务逻辑函数。

---

## 👑 核心设计：配置即声明（Config-Driven）

**Worker 的所有行为由 `config.toml` 驱动。** 框架遵循"配置即声明"原则——你在 `config.toml` 中声明的路由、参数、连接信息，框架自动将其转化为可运行的微服务。

```
┌──────────────────────────────────────────────────────┐
│                    config.toml                       │
│  ┌──────────┐ ┌──────┐ ┌──────────────┐ ┌─────────┐ │
│  │ [worker]  │ │[nats]│ │[registration]│ │logging. │ │
│  │ name      │ │ urls │ │ service      │ │ minio   │ │
│  │ version   │ │      │ │ heartbeat    │ │         │ │
│  └──────────┘ └──────┘ │   ┌─ items[]  │ └─────────┘ │
│                         │   │ subject   │             │
│                         │   │ method    │             │
│                         │   │ path      │             │
│                         │   │ params    │             │
│                         │   │ ttl/timeout            │
│                         │   │ response_model          │
│                         └───┴───────────┘             │
└─────────────────────────┬────────────────────────────┘
                          │ 加载
                          ▼
                ┌─────────────────────┐
                │  WorkerLifespan     │
                │  (自动: NATS 连接、   │
                │   路由注册、心跳、    │
                │   消息分发优雅关闭)    │
                └─────────────────────┘
```

---

## 快速开始（3 分钟）

### 第 0 步：编写 `config.toml`（Worker 的核心）

```toml
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
        ttl = 30,
        timeout = 2.0,
        response_model = {
            message = ["str", "__required__"],
            timestamp = ["float", 0.0]
        }
    }
]
```

### 第 1 步：创建 Handler

```python
# app/handlers/hello.py
from chongming_worker.worker_lifespan import WorkerLifespan

app = WorkerLifespan("config.toml")  # ← 加载 config.toml

@app.handler("hello.world")          # ← 匹配 config.toml 中的 subject
async def hello(name: str) -> dict:
    """说你好"""
    return {"message": f"Hello, {name}!", "timestamp": time.time()}
```

### 第 2 步：启动

```python
# main.py
from app.bootstrap import app
app.run()
```

**启动后框架自动：**
1. 加载 `config.toml` → 读取 `[worker]`、`[nats]`、`[registration]` 配置
2. 连接 NATS → 使用 `[nats].urls`
3. 注册路由 → 遍历 `items[]` 逐条注册
4. 启动心跳 → 每 `heartbeat_interval` 秒一次

---

## Worker 生命周期详解

### 启动流程

```
config.toml 加载 ──────────────────── ← Worker 名称、NATS 地址、路由配置（items）
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
  │  注册 handler    │      subject 必须与 config.toml items 匹配
  └─────────┬───────┘
            ▼
  ┌─────────────────┐
  │  app.run()      │  ← 进入事件循环
  └─────────┬───────┘
            │
            ▼
  ┌─────────────────────────────┐
  │  app.start()                 │
  │  ├─ 连接 NATS 集群            │ ← 使用 config.toml [nats] urls
  │  ├─ 注册当前服务              │ ← 遍历 items[] 注册每个 subject
  │  ├─ 订阅所有 subject          │ ← 开始监听消息
  │  └─ 启动心跳定时器            │ ← 每 heartbeat_interval 秒
  └─────────┬───────────────────┘
            │
            ▼
  ┌─────────────────────────────┐
  │  循环处理消息                  │
  │  ├─ 收到 NATS 请求            │
  │  ├─ 按 config.toml params     │ ← 解析参数
  │  ├─ 调用 handler              │ ← 你的业务代码在这里执行
  │  └─ 返回响应                  │
  └─────────────────────────────┘
```

### 关闭流程

```
收到 SIGTERM / SIGINT
      │
      ▼
  ┌─────────────────────┐
  │  app.shutdown()      │
  │  ├─ 停止心跳          │
  │  ├─ 取消所有订阅      │
  │  ├─ 注销服务          │  ← 通知 Gateway 移除路由
  │  └─ 关闭 NATS 连接    │
  └─────────────────────┘
```

### 生命周期钩子（启动/关闭回调）

Handler 模块可以通过 `on_start` / `on_stop` 注册回调，让 `WorkerLifespan` 在恰当的时机自动调用它们。

#### 动机

有些初始化工作需要在 NATS 就绪后才能执行，例如：
- 连接数据库、Redis 等外部服务
- 监听 NATS KV 桶的配置变更
- 加载缓存或模型文件

同样地，关闭时需要优雅释放这些资源。

#### 基本用法（装饰器风格）

```python
from app.bootstrap import app

@app.on_start
async def setup_db_pool():
    """NATS 连接就绪后，初始化数据库连接池"""
    global db_pool
    db_pool = await create_database_pool(
        host="localhost",
        port=5432,
    )
    logger.info("Database pool initialized")

@app.on_stop
async def close_db_pool():
    """关闭前释放数据库连接池"""
    global db_pool
    if db_pool:
        await db_pool.close()
        logger.info("Database pool closed")
```

#### 基本用法（方法调用风格）

```python
from app.bootstrap import app

async def setup_db_pool():
    global db_pool
    db_pool = await create_database_pool(...)

async def close_db_pool():
    global db_pool
    if db_pool:
        await db_pool.close()

# 注册启动/关闭钩子（方法调用风格）
app.on_start(setup_db_pool)
app.on_stop(close_db_pool)
```

#### 实际案例：监听网关配置变更

这是一个真实场景：监听 `_gw_config_` KV 桶中的 `gateway_config` 键变更，当网关更新 JWT 密钥时，实时同步更新。

```python
# app/handlers/auth.py
import asyncio
import json
import logging
from typing import Any, Dict, Optional

from app.bootstrap import app
from chongming_cache import ChongmingCache
from chongming_jwt import JWTAuth

logger = logging.getLogger("chongming.worker.user_auth")

jwt_auth = None
_listener_cache: Optional[ChongmingCache] = None
_listener_task: Optional[asyncio.Task] = None


async def listen_gateway_config_changes():
    """启动监听：订阅 _gw_config_ 桶中 gateway_config 键的变更"""
    global _listener_task, _listener_cache, jwt_auth

    _listener_cache = ChongmingCache(logger, bucket="_gw_config_")
    await _listener_cache.connect()

    # 1. 读取当前配置，初始化 jwt_auth
    entry = await _listener_cache.get("gateway_config")
    if entry is not None:
        gateway_config = json.loads(entry.value.decode())
        jwt_auth = JWTAuth(gateway_config.get("jwt", {}))

    # 2. 订阅后续变更
    _listener_task = await _listener_cache.subscribe(
        "gateway_config",
        _on_gateway_config_change,
    )
    logger.info("Listening for gateway config changes...")


async def _on_gateway_config_change(entry):
    """配置变更回调：更新 jwt_auth"""
    global jwt_auth
    gateway_config = json.loads(entry.value.decode())
    jwt_auth = JWTAuth(gateway_config.get("jwt", {}))
    logger.info("Updated JWTAuth from config change (rev=%d)", entry.revision)


async def stop_listener():
    """停止监听：取消任务、关闭连接"""
    global _listener_task, _listener_cache
    if _listener_task:
        _listener_task.cancel()
        try:
            await _listener_task
        except asyncio.CancelledError:
            pass
    if _listener_cache:
        await _listener_cache.close()


# 注册生命周期钩子
app.on_start(listen_gateway_config_changes)
app.on_stop(stop_listener)


@app.handler("user.auth")
async def auth_user(data: Any) -> Dict:
    return {
        "status": "success",
        "token": "fake-jwt-token",
        "timestamp": time.time(),
    }
```

#### 执行时序

```
app.start()
  ├─ NATS connect
  ├─ run on_start hooks ──→ listen_gateway_config_changes()
  │                           ├─ 连接 _gw_config_ 桶
  │                           ├─ 读取当前配置 → 初始化 jwt_auth
  │                           └─ subscribe gateway_config
  ├─ 注册到网关
  ├─ 订阅 NATS subject
  └─ 开始心跳

... 运行中 ...
  网关更新配置 → KV 变更 → 回调触发 → jwt_auth 自动更新

SIGINT/SIGTERM → app.shutdown()
  ├─ 取消心跳
  ├─ 取消 NATS 订阅
  ├─ 注销服务
  ├─ 关闭 NATS 连接
  └─ run on_stop hooks (相反顺序) ──→ stop_listener()
                                        ├─ cancel() 监听任务
                                        └─ close() KV 连接
```

#### 钩子数量与执行顺序

- 多个 `on_start` 钩子按注册顺序依次执行
- 多个 `on_stop` 钩子按**相反顺序**执行（后注册的先执行），确保释放顺序与创建顺序相反
- 某个钩子失败时**仅记录日志**，不会阻止后续钩子或 Worker 的启动/关闭

### 连接重连

NATS 断开后，框架会自动重连，重连后自动重新注册服务和订阅：

```
NATS 断开 → NATS 自动重连 → 重新读取 config.toml 注册信息 → 重新注册服务 + 重新订阅
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

**⚠️ 关键规则：Handler 的 subject 必须与 `config.toml` 中的 `subject` 匹配**

| 元素 | 定义位置 | 一致性要求 |
|------|----------|-----------|
| subject | `config.toml` items 的 `subject` 字段 | **必须**匹配 `@app.handler("calc.add")` |
| 参数名 | `config.toml` items 的 `params` 字段 | **必须**与 handler 函数参数名一致 |
| 参数类型 | `config.toml` items 的 `params` 类型注解 | 用于自动类型转换 |

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

> **注意：** `_app` 和 `_nc` 是框架自动注入的，**不需要在 config.toml 的 `params` 中声明**。

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
| `config_path` | `str` | `"config.toml"` | **配置文件路径**（Worker 所有配置来源） |

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
| `subject` | NATS subject（必填）。**必须匹配 config.toml items 中的 subject** |

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

---

### `app.shutdown()`

异步关闭 Worker。

```python
await app.shutdown()
```

---

### `app.request(subject, data)`

同步调用其他 Worker 的 handler（NATS Request-Reply）。

```python
result = await app.request("user.query", {"user_id": "u001"})
```

### `app.publish(subject, data)`

异步广播消息（NATS Publish），不等待响应。

```python
await app.publish("notification.order_created", {"order_id": "xxx"})
```

---

## config.toml 配置参考

### 完整结构

```toml
# ── Worker 元信息 ──────────────────────────────────
[worker]
name = "my-worker"
version = "0.1.0"
description = "..."

# ── NATS 连接信息 ──────────────────────────────────
[nats]
urls = [
    "nats://localhost:4222",
    "nats://localhost:4223",
    "nats://localhost:4224"
]

# ── 路由注册配置 ────────────────────────────────────
[registration]
type = "register"
service = "my-worker"
queue_group = "my-workers"    # 同组 worker 实现负载均衡
tags = ["my-tag"]
heartbeat_interval = 15       # 心跳间隔（秒）

# ── ★ 核心：所有路由定义 ────────────────────────────
items = [
    {
        subject = "calc.add",               # NATS 主题名（必填）
        method = "GET",                     # HTTP 方法（必填）
        path = "/add",                      # URL 路径（必填）
        params = ["a: float", "b: float"],  # 参数列表
        summary = "Add two numbers",        # OpenAPI 摘要
        docstring = "详细说明",               # OpenAPI 描述
        ttl = 30,                           # 路由 TTL（秒）
        timeout = 2.0,                      # 超时时间（秒）
        response_model = {                  # 响应模型
            result = ["float", "__required__"],
            operation = ["str", "add"],
            timestamp = ["float", 0.0]
        },
        shared = false,      # 是否共享模型
        internal = false,    # 是否内部 handler（不在 Swagger 展示）
        auth_required = true,# 是否需要 JWT 认证
    },
]

# ── MinIO 日志（可选） ─────────────────────────────
[logging.minio]
enabled = true
endpoint = "localhost:9000"
bucket = "chongming-logs"
retention_days = 30
```

### 字段速查表

| 字段 | 类型 | 必填 | 默认值 | 说明 | 定义位置 |
|------|------|------|--------|------|----------|
| `[worker].name` | string | ✅ | — | Worker 唯一标识 | config.toml |
| `[nats].urls` | array | ✅ | — | NATS 集群地址列表 | config.toml |
| `[registration].service` | string | ✅ | — | 服务名，Gateway URL 前缀 | config.toml |
| `[registration].heartbeat_interval` | int | ❌ | 15 | 心跳间隔（秒） | config.toml |
| `items[].subject` | string | ✅ | — | NATS 主题名 | config.toml |
| `items[].method` | string | ✅ | — | HTTP 方法 | config.toml |
| `items[].path` | string | ✅ | — | URL 路径 | config.toml |
| `items[].params` | array | ❌ | `[]` | 参数列表 `["name: type"]` | **必须与 handler 一致** |
| `items[].ttl` | int | ❌ | 30 | 路由 TTL（秒），**需 > heartbeat** | config.toml |
| `items[].timeout` | float | ❌ | 2.0 | NATS request 超时 | config.toml |
| `items[].response_model` | dict | ❌ | `{}` | 响应结构定义 | config.toml |
| `items[].internal` | bool | ❌ | `false` | 不在 Swagger 公开 | config.toml |

---

## 完整示例

```python
import time
from chongming_worker.worker_lifespan import WorkerLifespan

app = WorkerLifespan("config.toml")  # ← 一切从 config.toml 开始

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
    user = await _app.request("user.query", {"user_id": user_id})
    order_id = f"ORD-{int(time.time())}"
    await _app.publish("notification.order_created", {
        "order_id": order_id, "user_id": user_id, "item": item, "amount": amount,
    })
    return {"order_id": order_id, "user": user, "item": item, "amount": amount, "status": "created"}

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
