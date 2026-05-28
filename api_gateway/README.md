# Chongming Gateway — API 动态路由网关

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-teal.svg)](https://fastapi.tiangolo.com/)
[![NATS](https://img.shields.io/badge/NATS-2.10-green.svg)](https://nats.io/)

基于 FastAPI + NATS 的动态路由网关，作为 Chongming 微服务架构的流量入口。接收 HTTP 请求并通过 NATS Request/Reply 模式转发到对应的 Worker 服务，自动管理路由注册与心跳保活。

---

## 架构概述

```
HTTP 请求
     │
     ▼
┌───────────────┐
│  FastAPI App  │  ← 接收 HTTP 请求
│  (uvicorn)    │
└───────┬───────┘
        │
        ▼  NATS Request / Reply
┌──────────────────────────────────────────┐
│            NATS Cluster                  │
│         (3 节点高可用)                    │
└────┬─────┬─────┬──────┬──────────────────┘
     │     │     │      │
     ▼     ▼     ▼      ▼
  Worker Worker Worker Worker
  calc/  user/ order/  ...
```

---

## 核心特性

### 动态路由注册
- Worker 启动时通过 NATS 主题 `service.registry` 注册路由信息
- 路由信息包含：subject（NATS 主题）、method、path、参数定义、响应模型等
- 支持定时重新注册，Gateway 重启后路由自动恢复

### 心跳保活
- Worker 定期发送心跳消息到 Gateway
- Gateway 维护路由注册表，超时未收到心跳的路由自动清理
- 可配置心跳间隔和 TTL（生存时间）

### 响应模型
- 支持动态创建 Pydantic 响应模型
- 通过 `response_model` 配置定义字段类型和默认值
- 自动生成 OpenAPI 文档（Swagger UI）

### NATS 集群连接
- 支持多节点 NATS 集群
- 自动重连机制
- 分布式锁保护路由注册（基于 `chongming-lock`）

---

## 配置

`config.toml` 示例：

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

---

## API 端点

| 路径 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查，返回已注册路由列表 |
| `/debug/routes` | GET | 调试端点，列出所有已注册动态路由 |
| `/{prefix}/{path}` | 动态 | Worker 注册的动态路由 |

---

## 构建部署

```bash
# Nuitka 编译
uv run build

# Docker 镜像构建
chongming docker-build gateway

# 二进制镜像构建（推荐生产）
chongming binary-build gateway
```

### Docker 配置文件

| 文件 | 用途 |
|------|------|
| `gateway.Dockerfile` | Python 运行时模式 |
| `gateway-binary.Dockerfile` | PyInstaller 二进制模式（推荐） |

---

## 依赖

| 包 | 用途 |
|------|------|
| **FastAPI** | Web 框架 |
| **NATS-Py** | NATS 消息队列客户端 |
| **Gunicorn** | WSGI 服务器（生产） |
| **Uvicorn** | ASGI 服务器 |
| **tomli** | TOML 配置解析 |
| **chongming-lock** | 分布式锁 |
| **chongming-logging** | 日志配置 |
