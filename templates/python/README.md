# Example Worker — Python Worker 完整功能示例

基于 `chongming-worker` 框架开发的 Python Worker 示例，覆盖框架 **全部核心特性**，既是功能演示也是开发模板。

---

## 覆盖的特性

| # | 特性 | handler | 演示要点 |
|---|------|---------|----------|
| 1 | **基本 Handler 注册** | `calc.add/subtract/multiply/divide` | `@app.handler()` 装饰器，纯业务逻辑 |
| 2 | **被动服务（request 被调用方）** | `user.query` | 被其他 handler 通过 `_app.request()` 调用 |
| 3 | **主动调用方（request + publish）** | `order.create` | `_app.request()` 同步调用 + `_app.publish()` 异步广播 |
| 4 | **异步通知接收（publish 接收方）** | `notification.order_created` | 通过 publish 触发的独立 handler |
| 5 | **NATS 连接注入（_nc）** | `user.health_check` | `_nc` 参数由框架自动注入 |
| 6 | **框架实例注入（_app）** | `system.info` | `_app.nats_connection` 访问底层连接 |

---

## 快速开始

```bash
# 1. 启动 NATS 集群
cd docker-env && docker compose up -d

# 2. 启动 API Gateway
cd api_gateway && uv sync && uv run serve

# 3. 启动 Worker
cd workers/example && uv sync && python main.py
```

### 测试所有特性

```bash
# ── 特性 1：基本运算 ──────────────────────────────
curl "http://localhost:8000/api/v1/calc/add?a=10&b=20"       # → {"result": 30}
curl "http://localhost:8000/api/v1/calc/divide?a=100&b=3"    # → {"result": 33.33}

# ── 特性 3：Worker 间通讯（request + publish） ────
curl -X POST "http://localhost:8000/api/v1/order/create" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "u001", "amount": 30, "item": "book"}'
# → 内部调用 user.query → 检查余额 → publish 通知 → 返回订单

# ── 特性 5：健康检查（_nc 注入） ───────────────────
curl "http://localhost:8000/api/v1/user/health"
# → {"status": "healthy", "nats_server": "nats://..."}

# ── 特性 6：系统信息（_app 注入） ─────────────────
curl "http://localhost:8000/api/v1/system/info"
# → {"registered_subjects": ["calc.add", "user.query", ...]}
```

---

## 代码结构

```
workers/example/
├── main.py                   # ★ 入口：导入 app → 启动
├── config.toml               # ★ 核心配置：NATS、路由注册、心跳
├── pyproject.toml
├── README.md
└── app/
    ├── __init__.py
    ├── bootstrap.py           # ★ WorkerLifespan 实例 + MinIO 日志初始化
    └── handlers/
        ├── __init__.py        # 导入并注册所有 handler 模块
        ├── calc.py            # 特性 1：纯业务 handler
        ├── user.py            # 特性 2：被动服务 handler
        ├── order.py           # 特性 3+4：主动调用 + publish 接收
        └── system.py          # 特性 5+6：_nc / _app 注入演示
```

---

## 配置参考（config.toml 参数详解）

```toml
# ── Worker 元信息 ──────────────────────────────────────────────────
[worker]
name = "example"           # Worker 唯一标识，用于服务注册和日志
version = "0.1.0"
description = "..."        # 简要描述

# ── NATS 连接 ──────────────────────────────────────────────────────
[nats]
urls = [
    "nats://localhost:4222",   # NATS 集群节点（支持多节点高可用）
    "nats://localhost:4223",
    "nats://localhost:4224"
]

# ── 服务注册 ───────────────────────────────────────────────────────
[registration]
type = "register"              # 注册方式（固定为 "register"）
service = "example"            # 服务名，Gateway 用于 URL 路由前缀
queue_group = "calc-workers"   # 队列组名，同组 worker 实现请求负载均衡
router_prefix = "/calc"        # Gateway 路由前缀（已弃用，保留兼容）
tags = ["calculator", "worker-comm-demo"]  # 标签，用于服务分类和过滤
heartbeat_interval = 15        # 心跳间隔（秒），建议 10~30

# ── 路由定义 ───────────────────────────────────────────────────────
items = [
    # 每条路由 = 一个 NATS subject 映射为一个 HTTP API

    {
        # NATS subject 名，handler 通过 @app.handler("calc.add") 匹配
        subject = "calc.add",
        # HTTP 方法
        method = "GET",
        # HTTP 路径，Gateway 生成 URL: /api/v1/calc/add
        path = "/add",
        # OpenAPI 摘要
        summary = "Add two numbers",
        # OpenAPI 详细说明（自动出现在 Swagger UI）
        docstring = "Add two numbers and return result with metadata",
        # 参数列表（格式: "参数名: 类型"）
        params = ["a: float", "b: float"],
        # TTL（秒），服务注册的有效期，Gateway 缓存时间
        ttl = 30,
        # 超时（秒），NATS request 等待响应的最长时间
        timeout = 2.0,
        # 响应模型（类型 + 默认值），用于 API 文档和参数校验
        response_model = {
            result     = ["float", "__required__"],  # 必填字段
            operation  = ["str", "add"],             # 可选字段，默认值 "add"
            timestamp  = ["float", 0.0]
        }
    },

    # ── 被动服务：被 _app.request() 调用的内部服务 ─────────────────
    {
        subject = "user.query",
        method = "GET",
        path = "/user/query",
        summary = "Query user info",
        params = ["user_id: str"],
        ttl = 30,
        timeout = 2.0,
        response_model = {
            user_id   = ["str", "__required__"],
            name      = ["str", "__required__"],
            balance   = ["float", 0.0],
            level     = ["str", "normal"],
            queried_at = ["float", 0.0]
        }
    },

    # ── 主动调用方：request + publish 演示 ─────────────────────────
    {
        subject = "order.create",
        method = "POST",
        path = "/order/create",
        summary = "Create order (demonstrates _app.request & _app.publish)",
        params = ["user_id: str", "amount: float", "item: str"],
        ttl = 30,
        timeout = 10.0,   # 超时设长，因内部有两次通讯
        response_model = {
            order_id = ["str", "__required__"],
            user     = ["object", "__required__"],  # 嵌套对象
            item     = ["str", "__required__"],
            amount   = ["float", "__required__"],
            status   = ["str", "created"],
            timestamp = ["float", 0.0]
        }
    },

    # ── 异步通知接收方 ─────────────────────────────────────────────
    {
        subject = "notification.order_created",
        method = "POST",
        path = "/notification/order_created",
        params = ["order_id: str", "user_id: str", "user_name: str",
                  "item: str", "amount: float", "timestamp: float"],
        ttl = 30,
        timeout = 2.0,
        response_model = {
            status     = ["str", "notified"],
            message    = ["str", "__required__"],
            order_id   = ["str", "__required__"],
            notified_at = ["float", 0.0]
        },
        internal = true  # 内部服务，不在 Swagger 文档公开
    },

    # ── 系统管理（带 _nc 注入） ────────────────────────────────────
    {
        subject = "user.health_check",
        method = "GET",
        path = "/user/health",
        params = [],
        ttl = 30,
        timeout = 2.0,
        response_model = {
            status      = ["str", "__required__"],
            nats_server = ["str", "__required__"],
            timestamp   = ["float", 0.0]
        },
        internal = true
    },
]

# ── MinIO 日志持久化 ────────────────────────────────────────────────
[logging.minio]
enabled = true          # 启用 MinIO 日志
endpoint = "localhost:9000"  # MinIO 服务地址
bucket = "chongming-logs"      # 日志存储桶
retention_days = 30     # 日志保留天数
```

### 参数速查表

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `subject` | string | ✅ | NATS 主题名，handler 通过同名 `@app.handler()` 匹配 |
| `method` | string | ✅ | HTTP 方法：GET、POST、PUT、DELETE |
| `path` | string | ✅ | URL 路径，Gateway 组装为 `/api/v1/{service}{path}` |
| `params` | array | ❌ | 参数列表 `["name: type"]`，用于文档生成 |
| `ttl` | int | ❌ | 路由注册 TTL（秒），默认 30，需 < `registration.ttl` |
| `timeout` | float | ❌ | NATS request 超时（秒），默认 2.0 |
| `response_model` | dict | ❌ | 响应结构定义，用 `["type", 默认值]` 或 `["type", "__required__"]` |
| `internal` | bool | ❌ | 设为 `true` 不在 Swagger 文档公开 |
| `tags` | array | ❌ | 路由标签，用于 OpenAPI 分组 |

---

## 如何动手

### 添加新 Handler

```python
# app/handlers/hello.py
from app.bootstrap import app

@app.handler("hello.world")
async def hello_world(name: str) -> dict:
    return {"message": f"Hello, {name}!"}

# app/handlers/__init__.py 中追加：
from app.handlers import hello   # noqa: F401
```

### 添加新路由

```toml
# config.toml [registration] items 中追加：
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

---

## 构建部署

```bash
# Docker 镜像
chongming docker-build example

# 二进制镜像（推荐生产）
chongming binary-build example --tag registry.example.com/example:v1.0
