# Example Worker — Python Worker 完整功能示例（学习指南）

基于 `chongming-worker` 框架开发的 Python Worker 示例，覆盖框架 **全部核心特性**。如果你是第一次接触 Chongming，建议从本文档开始，逐步理解 Worker 的每个概念。

---

## 前置知识

在阅读本文前，建议先了解：
- [Worker 生命周期框架](../../utils/python/worker/README.md) — Worker 的基本概念和 API
- **Worker 的核心：`config.toml`** — 所有配置和路由定义都在此文件，本文将详细讲解

---

## 🎯 核心概念：一切从 `config.toml` 开始

每个 Worker 的行为完全由 **`config.toml`** 定义。Worker 启动后，框架做的第一件事就是**加载并解析 `config.toml`**，然后根据其中的配置依次完成连接 NATS、注册路由、启动心跳等操作。

```
config.toml
    │
    ├─ [worker]         → Worker 名称、版本
    ├─ [nats]           → NATS 集群地址
    ├─ [registration]   → 服务名、队列组、心跳间隔
    │   └─ items[]      → ★ 所有 handler 的路由定义！
    │        ├─ subject        NATS 主题名
    │        ├─ method/path    HTTP 方法 & 路径
    │        ├─ params         参数列表
    │        ├─ ttl/timeout    有效期 & 超时
    │        └─ response_model 响应结构
    └─ [logging.minio]  → 日志配置
```

**`config.toml` 的 `items` 数组定义了所有 handler 的路由**。每一条 `item` 对应一个 NATS subject + HTTP API 映射。当你编写一个 `@app.handler("calc.add")` 时，`"calc.add"` 必须匹配 `config.toml` 中某条 `item` 的 `subject` 字段。

---

## 覆盖的特性

这个示例 Worker 演示了 **5 大核心特性**，从简单到复杂逐步深入：

| # | 特性 | Handler | 学习要点 |
|---|------|---------|----------|
| 1 | **基本 Handler 注册** | `calc.add/subtract/multiply/divide` | 最基础的 handler，纯业务逻辑 |
| 2 | **被动服务** | `user.query` | 被其他 handler 通过 `_app.request()` 调用 |
| 3 | **主动调用 + 异步广播** | `order.create` | `_app.request()` 同步调用 + `_app.publish()` 异步广播 |
| 4 | **异步通知接收** | `notification.order_created` | 通过 publish 触发的独立 handler |
| 5 | **框架注入** | `system.info` / `user.health_check` | `_app` 和 `_nc` 参数由框架自动注入 |

---

## 快速开始

### 1. 启动基础设施

```bash
cd docker-env
docker compose up -d

# 确认 NATS 集群运行中
docker compose ps
# 输出应包含 nats-1, nats-2, nats-3
```

### 2. 启动 API Gateway

```bash
cd api_gateway
uv sync
uv run serve

# 输出示例:
# INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 3. 启动示例 Worker

```bash
cd workers/example
uv sync
python main.py

# 输出示例:
# INFO:     加载 config.toml 成功                ← 第一步：加载配置
# INFO:     连接 NATS 成功: nats://localhost:4222
# INFO:     注册 5 个路由 (来自 config.toml items) ← 第二步：注册路由
# INFO:     心跳已启动 (间隔: 15s)
```

### 4. 验证完整链路

```bash
# 健康检查
curl http://localhost:8000/health

# ── 特性 1：基本运算 ──────────────────────────────
curl "http://localhost:8000/api/v1/calc/add?a=10&b=20"
# → {"result": 30, "operation": "add", "timestamp": 1654321000.0}

curl "http://localhost:8000/api/v1/calc/divide?a=100&b=3"
# → {"result": 33.33, "operation": "divide", "timestamp": 1654321000.5}

# ── 特性 3：Worker 间通讯 ─────────────────────────
curl -X POST "http://localhost:8000/api/v1/order/create" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "u001", "amount": 30, "item": "book"}'
# 内部流程：
#   1. order.create 调用 user.query 查询用户余额
#   2. 检查余额充足后创建订单
#   3. publish 通知 notification.order_created
#   4. 返回订单信息
# → {"order_id": "ORD-1654321000", "user": {...}, "item": "book", ...}

# ── 特性 5：框架注入 ──────────────────────────────
curl "http://localhost:8000/api/v1/user/health"
# → {"status": "healthy", "nats_server": "nats://localhost:4222", "timestamp": ...}

curl "http://localhost:8000/api/v1/system/info"
# → {"status": "ok", "worker_name": "example", "registered_subjects": [...], ...}

# Swagger UI（浏览器打开）
open http://localhost:8000/docs
```

---

## 代码结构

```
workers/example/
├── main.py                 # ★ 入口文件（最简单的：导入 app → 启动）
├── config.toml             # ★★ 核心配置文件——Worker 的"心脏"
│                           #    定义所有路由、参数、NATS 连接、心跳间隔
├── pyproject.toml          #   Python 项目配置
├── app/
│   ├── __init__.py
│   ├── bootstrap.py        # ★ WorkerLifespan 实例（加载 config.toml）
│   └── handlers/
│       ├── __init__.py     # ★ 导入并注册所有 handler 模块
│       ├── calc.py         #   特性 1：纯业务 handler
│       ├── user.py         #   特性 2：被动服务 handler
│       ├── order.py        #   特性 3+4：主动调用 + publish 接收
│       └── system.py       #   特性 5：_nc / _app 注入演示
└── models/
    └── __init__.py         #   自动生成的 Pydantic 模型文件
```

---

## 特性详解

### 特性 1：基本 Handler 注册

**知识点：** 每个 handler 是一个 async 函数，通过 `@app.handler()` 装饰器注册。**装饰器的 subject 必须与 `config.toml` 中的 `subject` 一致**。

**文件：** `app/handlers/calc.py`

```python
from app.bootstrap import app
import time

@app.handler("calc.add")
async def add(a: float, b: float) -> dict:
    """加法运算"""
    return {
        "result": a + b,
        "operation": "add",
        "timestamp": time.time(),
    }
```

**对应的 `config.toml` 路由定义：**
```toml
{
    subject = "calc.add",          # ← 必须与 @app.handler("calc.add") 一致
    method = "GET",
    path = "/add",
    params = ["a: float", "b: float"],   # ← 参数名必须与函数参数一致
    ttl = 30,
    timeout = 2.0,
    response_model = {
        result = ["float", "__required__"],
        operation = ["str", "add"],
        timestamp = ["float", 0.0]
    }
}
```

✅ `handler 函数` 和 `config.toml` 通过 `subject` 绑定。**这是最核心的对应关系。**

---

### 特性 2：被动服务

**知识点：** Handler 可以被其他 handler 通过 `_app.request()` 同步调用。

**文件：** `app/handlers/user.py`

```python
@app.handler("user.query")
async def user_query(user_id: str, _app: WorkerLifespan) -> dict:
    """查询用户信息（被其他 handler 通过 _app.request() 调用）"""
    return {
        "user_id": user_id,
        "name": "Alice",
        "balance": 100.0,
        "level": "normal",
        "queried_at": time.time(),
    }
```

**`config.toml` 中对应的路由：** `subject = "user.query"` 定义了 NATS 主题名，其他 handler 通过 `_app.request("user.query", {...})` 调用。

---

### 特性 3：主动调用 + 异步广播

**知识点：** 一个 handler 可以通过 `_app.request()` 同步调用其他 handler，并通过 `_app.publish()` 发送异步广播。

**文件：** `app/handlers/order.py`

```python
@app.handler("order.create")
async def create_order(
    user_id: str,
    amount: float,
    item: str,
    _app: WorkerLifespan,  # ← 框架自动注入
) -> dict:
    # 1. 同步调用：查询用户信息
    user = await _app.request("user.query", {"user_id": user_id})

    # 2. 业务校验：检查余额
    if user["balance"] < amount:
        raise ValueError("余额不足")

    # 3. 创建订单
    order_id = f"ORD-{int(time.time())}"

    # 4. 异步广播：通知其他服务（不等待响应）
    await _app.publish("notification.order_created", {
        "order_id": order_id,
        "user_id": user_id,
        "user_name": user["name"],
        "item": item,
        "amount": amount,
        "timestamp": time.time(),
    })

    return {
        "order_id": order_id,
        "user": user,           # 嵌套对象
        "item": item,
        "amount": amount,
        "status": "created",
        "timestamp": time.time(),
    }
```

**`config.toml` 中 `order.create` 的超时设为 10.0 秒**（因为内部有两次 NATS 通讯），这是配置驱动 Worker 行为的典型示例。

---

### 特性 4：异步通知接收

**知识点：** 通过 `_app.publish()` 发送的消息，可以被另一个 handler 接收处理。

**文件：** `app/handlers/order.py`（同一文件）

```python
@app.handler("notification.order_created")
async def on_order_created(order_id: str, user_id: str, item: str, amount: float, timestamp: float) -> dict:
    """处理订单创建通知（通过 publish 触发）"""
    print(f"收到通知：订单 {order_id} 已创建")
    return {"status": "notified", "message": f"Order {order_id} processed", ...}
```

**`config.toml` 中此路由标记为 `internal = true`**，表示不在 Swagger 文档中公开。**所有行为都由 config.toml 控制**。

---

### 特性 5：框架注入

**知识点：** 框架会自动注入两个特殊参数——`_app`（框架实例）和 `_nc`（NATS 连接）。**这两个参数不需要在 config.toml 的 `params` 中声明**。

**文件：** `app/handlers/system.py`

```python
# _nc 注入：直接操作 NATS 连接
@app.handler("user.health_check")
async def health_check(_nc: Nats) -> dict:
    """获取 NATS 连接状态"""
    server_info = _nc._nats_connected_server
    return {
        "status": "healthy",
        "nats_server": str(server_info),
        "timestamp": time.time(),
    }

# _app 注入：访问框架配置
@app.handler("system.info")
async def system_info(_app: WorkerLifespan) -> dict:
    """查看 Worker 系统信息"""
    return {
        "status": "ok",
        "worker_name": _app.config["worker"]["name"],
        "registered_subjects": list(_app._handlers.keys()),
        "heartbeat_interval": _app.config["registration"]["heartbeat_interval"],
        "timestamp": time.time(),
    }
```

虽然 `config.toml` 中这两个路由的 `params = []`，但 handler 仍然可以声明 `_app` 和 `_nc` 参数，框架会自动注入。

---

## config.toml 配置详解

### 基础结构

```toml
[worker]
name = "example"
version = "0.1.0"
description = "chongming worker example — covers all WorkerLifespan features"

[nats]
urls = [
    "nats://localhost:4222",
    "nats://localhost:4223",
    "nats://localhost:4224"
]

[registration]
type = "register"
service = "example"
queue_group = "calc-workers"   # 同 group 的 worker 实现负载均衡
router_prefix = "/calc"
tags = ["example"]
heartbeat_interval = 15        # 心跳间隔（秒）

items = [
    # ── 每条 item 定义一条路由 ──────────────────
    {
        subject = "calc.add",
        method = "GET",
        path = "/add",
        params = ["a: float", "b: float"],
        ttl = 30,
        timeout = 2.0,
        response_model = {
            result = ["float", "__required__"],
            operation = ["str", "add"],
            timestamp = ["float", 0.0]
        }
    },
    # ... 更多 items
]

[logging.minio]
enabled = true
endpoint = "localhost:9000"
bucket = "chongming-logs"
retention_days = 30
```

### 字段速查表

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `subject` | string | ✅ | — | NATS 主题名，handler 用 `@app.handler("calc.add")` 匹配 |
| `method` | string | ✅ | — | HTTP 方法：GET/POST/PUT/DELETE |
| `path` | string | ✅ | — | URL 路径，最终 URL: `/api/v1/{service}{path}` |
| `params` | array | ❌ | `[]` | 参数列表 `["name: type"]`，必须与 handler 函数参数一致 |
| `ttl` | int | ❌ | 30 | 路由 TTL（秒），**必须大于 `heartbeat_interval`** |
| `timeout` | float | ❌ | 2.0 | NATS request 超时时间 |
| `response_model` | dict | ❌ | `{}` | 响应结构，决定 OpenAPI 文档的响应模型 |
| `shared` | bool | ❌ | `false` | 设为 `true` 会被 `--shared` 选中 |
| `internal` | bool | ❌ | `false` | 设为 `true` 不在 Swagger 文档公开 |
| `auth_required` | bool | ❌ | `true` | 是否需要 JWT 认证 |

---

## 如何动手练习

### 练习 1：添加新 Handler（三步走）

**第 1 步：在 `config.toml` 中添加路由定义**
```toml
# 追加到 items 数组中
{
    subject = "hello.world",
    method = "GET",
    path = "/hello",
    summary = "Say hello",
    params = ["name: str"],
    ttl = 30,
    timeout = 2.0,
    response_model = {
        message = ["str", "__required__"]
    }
}
```

**第 2 步：创建 handler 文件**
```python
# app/handlers/hello.py
from app.bootstrap import app

@app.handler("hello.world")  # ← 必须与 config.toml 中的 subject 一致
async def hello_world(name: str) -> dict:
    return {"message": f"Hello, {name}!"}
```

**第 3 步：注册 handler**
```bash
echo "from app.handlers import hello  # noqa: F401" >> workers/example/app/handlers/__init__.py
```

**第 4 步：重启 Worker 并测试**
```bash
# Ctrl+C 停止 Worker，重新运行
python main.py

# 测试
curl "http://localhost:8000/api/v1/hello?name=chongming"
```

### 练习 2：体验 _app.request

```bash
# order.create 内部调用了 user.query
# 运行后观察 Worker 日志
curl -X POST "http://localhost:8000/api/v1/order/create" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "u001", "amount": 30, "item": "book"}'
```

### 练习 3：生成模型

```bash
# 从 config.toml 生成 Pydantic 模型
chongming gen-models example

# 查看生成的模型
cat workers/example/models/__init__.py
```

---

## 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| Worker 启动时 `连接 NATS 失败` | NATS 未启动 | 先启动 `docker compose up -d` |
| Gateway 返回 502 | Worker 未启动或路由未注册 | 确认 Worker 日志显示 `注册成功` |
| `_app.request()` 超时 | 目标 handler 未注册或 NATS 连接异常 | 检查目标 Worker 是否运行 |
| Handler 未调用 | `@app.handler(subject)` 与 `config.toml` 的 `subject` 不匹配 | 确保两者一致 |
| 参数类型错误 | config.toml 的 params 类型注解与 handler 不一致 | 确保类型匹配 |

---

## 下一步

- 阅读 [CLI 工具文档](../../cli/README.md) 了解如何构建和部署
- 阅读 [Docker 部署文档](../../docker-env/README.md) 了解生产环境配置
- 尝试创建自己的 Worker：`chongming new my-worker`
