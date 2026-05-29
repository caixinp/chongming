# Chongming Gateway — API 动态路由网关

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-teal.svg)](https://fastapi.tiangolo.com/)
[![NATS](https://img.shields.io/badge/NATS-2.10-green.svg)](https://nats.io/)

基于 **FastAPI + NATS** 的动态路由网关，作为 Chongming 微服务架构的统一流量入口。接收 HTTP 请求并通过 NATS Request/Reply 模式转发到对应的 Worker 服务，自动管理路由注册与心跳保活。

---

## 架构概述

```
HTTP 请求 (Client)
     │
     ▼
┌─────────────────────────────┐
│      FastAPI Application     │  ← 接收 HTTP 请求，解析参数
│        (Uvicorn/Gunicorn)    │  ← 自动生成 OpenAPI / Swagger 文档
└──────────┬──────────────────┘
           │
           ▼   NATS Request / Reply
┌────────────────────────────────────────────┐
│              NATS Cluster                  │
│           (3 节点高可用)                    │
│  JetStream KV Store + Queue Group          │
└────┬──────┬──────┬──────┬──────────────────┘
     │      │      │      │
     ▼      ▼      ▼      ▼
  Worker  Worker Worker Worker
  calc/   user/  order/  ...
```

### 核心流程

1. **Worker 启动** → 通过 NATS 主题 `service.registry` 发送注册消息（路由、参数、响应模型）
2. **Gateway 监听** → 接收注册消息，动态添加路由到 FastAPI router
3. **心跳保活** → Worker 定期发送心跳，Gateway 清理超时路由
4. **请求转发** → 客户端请求到达 Gateway → NATS Request-Reply → Worker 处理并返回
5. **自动文档** → 动态路由自动出现在 `/docs` 和 `/redoc`

---

## 核心特性

### 🔄 动态路由注册
- Worker 启动时通过 `service.registry` 主题注册路由信息
- 包含：subject（NATS 主题）、method、path、参数定义、响应模型等
- 支持定时批量心跳携带完整路由信息，Gateway 重启后自动恢复
- 分布式锁保护路由注册表并发安全

### 💓 心跳保活
- Worker 定期发送心跳（默认每 15 秒）
- 批量心跳（每 3 个周期）携带完整 items 信息
- Gateway 维护路由注册表，超时未收到心跳的路由自动清理
- 可配置心跳间隔和 TTL

### 📋 自动 OpenAPI 文档
- 动态创建 Pydantic 响应模型
- 通过 `response_model` 配置定义字段类型和默认值
- 所有动态路由自动出现在 Swagger UI (`/docs`) 和 ReDoc (`/redoc`)

### 🔗 NATS 集群高可用
- 支持多节点 NATS 集群连接
- 自动重连机制
- 分布式锁保护路由注册（基于 `chongming-lock`）

---

## 配置

### config.toml

```toml
[default]
app.debug = false
app.name = "chongming-gateway"
app.version = "v0.1.0"
prefix = "/api/v1"
env = "development"

[nats]
urls = [
    "nats://localhost:4222",
    "nats://localhost:4223",
    "nats://localhost:4224"
]

[cleanup]
interval = 10  # 过期路由清理间隔（秒）
```

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `app.debug` | 调试模式 | `false` |
| `app.name` | 网关名称 | `chongming-gateway` |
| `app.version` | 版本号 | `v0.1.0` |
| `prefix` | 全局路由前缀 | `/api/v1` |
| `nats.urls` | NATS 集群地址列表 | 默认 3 节点 |
| `cleanup.interval` | 路由清理检查间隔（秒） | `10` |

---

## 快速开始

```bash
# 安装依赖
cd api_gateway
uv sync

# 开发模式（单进程 + 热重载）
uv run serve

# 生产模式（Gunicorn + 4 Uvicorn Workers）
uv run gunicorn
```

### 通过 CLI 启动

```bash
chongming gateway
chongming gateway --host 127.0.0.1 --port 8080 --reload
chongming gateway --production
```

---

## API 端点

| 路径 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查，返回状态和已注册路由列表 |
| `/debug/routes` | GET | 调试端点，列出所有已注册动态路由详情 |
| `/{prefix}/{path}` | 动态 | Worker 注册的动态路由 |

### `/health` 响应示例

```json
{
    "status": "ok",
    "registered_services": ["calc.add", "calc.subtract", "calc.multiply", "calc.divide"]
}
```

### `/debug/routes` 响应示例

```json
{
    "routes": [
        {
            "prefix": "/calc",
            "path": "/calc/add",
            "methods": ["GET"],
            "name": "calc.add"
        }
    ],
    "router_prefixes": ["/calc"],
    "registry_lock_type": "chongming_lock.MutexLock (distributed)",
    "total_registered": 4
}
```

---

## NATS 消息协议

### 服务注册 (`service.registry`)

Gateway 订阅 `service.registry` 主题，处理以下消息类型：

#### `type = "register"` — 服务注册

Worker 首次启动或 NATS 重连后发送。

```json
{
    "type": "register",
    "service": "example",
    "router_prefix": "/calc",
    "tags": ["calc"],
    "items": [
        {
            "subject": "calc.add",
            "method": "GET",
            "path": "/calc/add",
            "summary": "加法运算",
            "docstring": "两数相加",
            "params": ["a: float", "b: float"],
            "ttl": 60,
            "timeout": 2.0,
            "response_model": {
                "result": "float",
                "operation": "str",
                "timestamp": "float"
            }
        }
    ]
}
```

#### `type = "heartbeat"` — 心跳保活

**单个路由心跳（常规周期）：**
```json
{
    "type": "heartbeat",
    "service": "example",
    "subject": "calc.add"
}
```

**批量路由心跳（每 3 次心跳周期，携带完整路由信息）：**
```json
{
    "type": "heartbeat",
    "service": "example",
    "subjects": ["calc.add", "calc.subtract", "calc.multiply", "calc.divide"],
    "items": [/* 完整路由信息 */],
    "router_prefix": "/calc",
    "tags": ["calc"]
}
```

> **说明：** 批量心跳携带完整的 items 信息。即使 Gateway 重启后 `routes_registry` 清空，也能通过 items 自动恢复路由，替代了原先定期 `type=register` 触发路由删除重建的不稳定方式。

#### `type = "deregister"` — 服务注销

Worker 优雅关闭时发送。

```json
{
    "type": "deregister",
    "service": "example",
    "router_prefix": "/calc"
}
```

---

## 请求参数规范

支持两种格式的参数声明：

| 格式 | 示例 | 说明 |
|------|------|------|
| 纯参数名 | `["a", "b"]` | 类型默认为 `str` |
| 带类型声明 | `["a: float", "b: float"]` | Gateway 层做严格类型校验 |

**支持的参数类型：** `str`、`int`、`float`、`bool`

**类型校验失败时返回 HTTP 400 Bad Request。**

---

## 构建部署

```bash
# Nuitka 编译
uv run build

# Docker 镜像构建（Python 运行时）
chongming docker-build gateway

# 二进制镜像构建（推荐生产）
chongming binary-build gateway
```

### Docker 镜像方案

| 方案 | Dockerfile | 基础镜像 | 最终大小 | 适用场景 |
|------|-----------|----------|---------|----------|
| Python 运行时 | `gateway.Dockerfile` | `python:3.12-slim` | ~200-300MB | 开发 / CI |
| 二进制模式 ✅ | `gateway-binary.Dockerfile` | `busybox:glibc` | ~20-30MB | **生产部署** |

---

## 依赖

| 包 | 用途 |
|------|------|
| **FastAPI** | Web 框架 |
| **NATS-Py** | NATS 消息队列客户端 |
| **Gunicorn** | WSGI 服务器（生产模式） |
| **Uvicorn** | ASGI 服务器 |
| **tomli** | TOML 配置解析 |
| **chongming-lock** | 分布式锁（保护路由注册表） |
| **chongming-logging** | 统一日志配置 |
