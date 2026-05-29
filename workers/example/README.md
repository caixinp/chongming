# Example Worker — Python Worker 完整功能示例（学习指南）

基于 `chongming-worker` 框架开发的 Python Worker 示例，覆盖框架 **全部核心特性**。如果你是第一次接触 Chongming，建议从本文档开始，逐步理解 Worker 的每个概念。

---

## 前置知识

在阅读本文前，建议先了解：
- [Worker 生命周期框架](../../utils/worker/README.md) — Worker 的基本概念和 API
- [CLI 工具 — config.toml 详解](../../cli/README.md#worker-configtoml-配置详解) — 配置文件完整说明

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
# INFO:     连接 NATS 成功: nats://localhost:4222
# INFO:     注册服务成功: example
# INFO:     已订阅 5 个 subject
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
├── config.toml             # ★ 核心配置文件（定义所有路由和参数）
├── pyproject.toml          #   Python 项目配置
├── app/
│   ├── __init__.py
│   ├── bootstrap.py        # ★ WorkerLifespan 实例（含 MinIO 日志初始化）
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

**知识点：** 每个 handler 是一个 async 函数，通过 `@app.handler()` 装饰器注册。

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

**对应配置：**
```toml
{
    subject = "calc.add",
    method = "GET",
    path = "/add",
    params = ["a: float", "b: float"],   # 参数名必须与函数参数一致
    response_model = {
        result = ["float", "__required__"],
        operation = ["str", "add"],
        timestamp = ["float", 0.0]
    }
}
```

✅ 这就是最基础的 handler，纯业务逻辑，没有额外依赖。

---

### 特性 2：被动服务

**知识点：** Handler 可以被其他 handler 通过 `_app.request()` 同步调用。

**文件：** `app/handlers/user.py`

```python
@app.handler("user.query")
async def user_query(user_id: str, _app: WorkerLifespan) -> dict:
    """查询用户信息（被其他 handler 通过 _app.request() 调用）"""
    # 这里实际应该查数据库，示例返回固定值
    return {
        "user_id": user_id,
        "name": "Alice",
        "balance": 100.0,
        "level": "normal",
        "queried_at": time.time(),
    }
```

**使用场景：**
- 用户服务提供 `user.query` handler
- 订单服务通过 `_app.request("user.query", {...})` 调用

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

**数据流图解：**

```
HTTP POST /api/v1/order/create
      │
      ▼
┌─────────────────────────────────────┐
│  order.create handler                │
│                                     │
│  1. _app.request("user.query")      │──→ user.query handler ──→ 返回用户信息
│                                     │    ←────────────────────
│  2. 校验余额是否充足                  │
│                                     │
│  3. 创建订单                         │
│                                     │
│  4. _app.publish("notification")    │──→ notification.order_created handler
│                                     │     （异步执行，不等待）
│  5. 返回订单结果                      │
└─────────────────────────────────────┘
```

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

**注意：**
- publish 是 **异步广播**，调用方不等待响应
- 同一个 Worker 或不同 Worker 都可以订阅相同的 subject
- 适用于**事件驱动**架构（如发邮件、写日志、更新缓存等）

---

### 特性 5：框架注入

**知识点：** 框架会自动注入两个特殊参数——`_app`（框架实例）和 `_nc`（NATS 连接）。

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

**注入规则：**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| `_app` | `WorkerLifespan` | 框架实例，可用于 `_app.request()` / `_app.publish()` 或读取配置 |
| `_nc` | `Nats` | 原始 NATS 连接对象，用于直接操作 NATS |

这两个参数由框架自动注入，**不占用 config.toml 中的 params 位置**。即使 `params = []`，也可以使用这两个参数。

---

## 配置参考（config.toml）

完整的配置说明已迁移到 [CLI 文档 — Worker config.toml 配置详解](../../cli/README.md#worker-configtoml-配置详解)，这里仅列出本示例中使用的参数：

| 字段 | 本示例值 | 说明 |
|------|----------|------|
| `heartbeat_interval` | `15` | 心跳间隔 15 秒 |
| `ttl` | `30` | 路由 TTL 30 秒（≥ 心跳 × 2） |
| `timeout` | `2.0` / `10.0` | 普通 handler 2 秒，`order.create` 10 秒（因内部有两次通讯） |
| `internal` | `true` | `notification.order_created` 等内部 handler 不在 Swagger 显示 |

### 关键配置示例

```toml
# 每个 handler 必填的 4 个字段
{
    subject = "order.create",       # NATS subject
    method = "POST",                # HTTP 方法
    path = "/order/create",         # URL 路径
    params = ["user_id: str", ...], # 参数列表
}

# 可选但推荐的字段
{
    summary = "创建订单",             # OpenAPI 摘要
    ttl = 30,                        # TTL
    timeout = 10.0,                  # 超时
    response_model = { ... },        # 响应模型
}
```

---

## 如何动手练习

### 练习 1：添加新 Handler

```bash
# 1. 创建新文件
cat > workers/example/app/handlers/hello.py << 'EOF'
from app.bootstrap import app

@app.handler("hello.world")
async def hello_world(name: str) -> dict:
    return {"message": f"Hello, {name}!"}
EOF

# 2. 注册到 __init__.py
echo "from app.handlers import hello  # noqa: F401" >> workers/example/app/handlers/__init__.py

# 3. 在 config.toml 的 items 中添加：
# {
#     subject = "hello.world",
#     method = "GET",
#     path = "/hello",
#     summary = "Say hello",
#     params = ["name: str"],
#     response_model = {
#         message = ["str", "__required__"]
#     }
# }

# 4. 重启 Worker（Ctrl+C 重新运行 python main.py）

# 5. 测试
# curl "http://localhost:8000/api/v1/hello?name=chongming"
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
# 生成 Pydantic 模型（自动从 config.toml 生成）
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
| 参数类型错误 | config.toml 的 params 类型注解与 handler 不一致 | 确保类型匹配 |

---

## 下一步

- 阅读 [CLI 工具文档](../../cli/README.md) 了解如何构建和部署
- 阅读 [Docker 部署文档](../../docker-env/README.md) 了解生产环境配置
- 尝试创建自己的 Worker：`chongming new my-worker`
