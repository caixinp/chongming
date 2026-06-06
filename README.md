# Chongming — 基于 NATS 的微服务平台

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Rust](https://img.shields.io/badge/Rust-1.80+-orange.svg)](https://www.rust-lang.org/)
[![NATS](https://img.shields.io/badge/NATS-2.10-green.svg)](https://nats.io/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-teal.svg)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Chongming 是一个基于 **NATS 消息队列**的现代化微服务框架，提供**动态路由注册**、**服务发现**、**分布式锁**和**优雅关闭**等核心能力，支持 **Python** 和 **Rust** 两种 Worker 开发语言，帮助开发者快速构建可扩展的分布式系统。

---

## 核心特性

| 特性 | 说明 |
|------|------|
| **动态路由注册** | Worker 启动时自动向 Gateway 注册路由，无需手动配置 |
| **多语言 Worker** | 支持 Python 和 Rust 两种 Worker 开发语言 |
| **NATS 消息驱动** | 基于 NATS Request/Reply 模式实现服务间通信 |
| **Queue Group 负载均衡** | 同一 Worker 多实例自动分发请求 |
| **分布式锁（6 种）** | 互斥锁、读写锁、信号量、可重入锁、租约锁、栅栏令牌锁 |
| **OpenAPI 文档** | 动态路由自动生成 Swagger UI 文档 |
| **分布式追踪** | request_id 贯穿 Gateway → Worker 全链路 |
| **请求链路追踪** | `chongming trace` 实时追踪 NATS 请求-响应，关联 request_id 和耗时 |
| **二进制部署** | PyInstaller 编译为单文件二进制，镜像仅 ~20MB |
| **Docker 一键部署** | 开发/生产双模式 Docker Compose 编排 |

---

## Worker 详解（核心概念）

### 什么是 Worker？

Worker 是 Chongming 微服务架构中的**业务逻辑执行单元**。每个 Worker 是一个独立的服务进程，通过 NATS 消息队列与 API Gateway 和其他 Worker 通信。

```
客户端 HTTP 请求
      │
      ▼
┌──────────────┐     NATS Request/Reply      ┌──────────────────┐
│ API Gateway  │ ──────────────────────────→ │    Worker        │
│  (FastAPI)   │                             │  (业务处理单元)   │
│              │ ←────────────────────────── │                  │
└──────────────┘           JSON              └──────────────────┘
```

### Worker 的核心 — `config.toml`

**每个 Worker 的核心是 `config.toml` 文件**，它是 Worker 的**唯一配置来源**，定义了 Worker 的全部行为：

| 配置模块 | 作用 | 说明 |
|----------|------|------|
| `[worker]` | Worker 身份 | 名称、版本、描述 |
| `[nats]` | 连接信息 | NATS 集群地址列表 |
| `[registration]` | 路由注册 | 服务名、队列组、心跳间隔、**所有路由定义（items）** |
| `[logging.minio]` | 日志持久化 | MinIO 对象存储配置 |

Worker 的生命周期就是围绕 `config.toml` 展开的：

```
config.toml 加载 ──→ 连接 NATS ──→ 注册路由 ──→ 处理请求 ──→ 优雅关闭
     │                    │              │             │             │
     │                    ▼              ▼             ▼             ▼
  读取 Worker        读取 NATS      读取 items      按 params      触发
  身份信息           URL 列表       注册所有        解析参数        注销
                   (支持多节点)     handler         调用 handler    路由
```

---

## Worker 生命周期

```
启动
  │
  ▼
┌─────────────────────┐
│  ★ 加载 config.toml  │  ← Worker 名称、NATS 地址、路由配置（items）
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│  连接 NATS 集群       │  ← 支持多节点高可用
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│  注册服务到 Gateway   │  ← 读取 config.toml items 逐条注册
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│  订阅 handler subject│  ← 开始监听 NATS 消息
└─────────┬───────────┘
          ▼
┌─────────────────────┐     ┌──────────────────────┐
│  循环：发送心跳       │────→│ 每 heartbeat_interval │
│       等待消息        │     │ 秒发一次心跳           │
│       处理请求        │     └──────────────────────┘
└─────────┬───────────┘
          ▼  (收到 SIGTERM/SIGINT)
┌─────────────────────┐
│  优雅关闭             │
│  ├─ 停止心跳          │
│  ├─ 取消订阅          │
│  ├─ 注销服务          │
│  └─ 关闭 NATS 连接    │
└─────────────────────┘
```

---

## 快速创建自己的 Worker

### 方式一：使用 CLI 脚手架（推荐）

```bash
# 创建 Python Worker
chongming new my-worker

# 或创建 Rust Worker
chongming new my-worker --lang rust
```

这会自动生成完整的项目结构，包含 `config.toml`、`main.py`、handler 目录等。**生成后的第一件事就是编辑 `config.toml`**。

### 方式二：手动搭建

```bash
# 1. 创建项目目录
mkdir -p workers/my-worker/app/handlers
cd workers/my-worker

# 2. 创建 config.toml（Worker 的核心！）
cat > config.toml << 'TOML'
[worker]
name = "my-worker"
version = "0.1.0"
description = "my first worker"

[nats]
urls = ["nats://localhost:4222"]

[registration]
type = "register"
service = "my-worker"
queue_group = "my-workers"
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
            message = ["str", "__required__"]
        }
    }
]
TOML

# 3. 创建 main.py
cat > main.py << 'EOF'
from app.bootstrap import app
app.run()
EOF

# 4. 创建 bootstrap.py
mkdir -p app
cat > app/bootstrap.py << 'EOF'
from chongming_worker.worker_lifespan import WorkerLifespan
app = WorkerLifespan("config.toml")  # ← 加载 config.toml
EOF

# 5. 创建 handler
cat > app/handlers/hello.py << 'EOF'
from app.bootstrap import app

@app.handler("hello.world")  # ← 匹配 config.toml 中的 subject
async def hello(name: str) -> dict:
    return {"message": f"Hello, {name}!"}
EOF

cat > app/handlers/__init__.py << 'EOF'
from app.handlers import hello  # noqa: F401
EOF
```

---

## 项目架构

```
┌─────────────────────────────────────────────────────────────┐
│                       客户端 (Browser/curl)                  │
└─────────────────────┬───────────────────────────────────────┘
                      │  HTTP
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              Nginx 负载均衡（生产环境双实例）                  │
└─────────────────────┬───────────────────────────────────────┘
                      │
              ┌───────┴───────┐
              ▼               ▼
┌─────────────────────┐ ┌─────────────────────┐
│   API Gateway #1    │ │   API Gateway #2    │
│  (FastAPI+Uvicorn)  │ │  (FastAPI+Uvicorn)  │
└─────────┬───────────┘ └─────────┬───────────┘
          │                       │
          └───────────┬───────────┘
                      │  NATS Request/Reply
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                    NATS 集群（3 节点）                        │
│               JetStream + KV Store + Queue Group            │
└────┬──────────┬──────────┬──────────────────────────────────┘
     │          │          │
     ▼          ▼          ▼
┌────────┐┌────────┐┌─────────────────────────────────────────┐
│Worker  ││Worker  ││  基础设施                                │
│Python  ││ Rust   ││  ┌─────────┐ ┌──────────┐ ┌──────────┐ │
│(my-app)││(demo)  ││  │PostgreSQL│ │  MinIO   │ │  Redis   │ │
└────────┘└────────┘│  │主备自动切换│ │对象存储2节点│ │(可选)    │ │
                    │  └─────────┘ └──────────┘ └──────────┘ │
                    └─────────────────────────────────────────┘
```

### 目录结构

```
chongming/
├── api_gateway/            # ★ API Gateway — FastAPI 动态路由网关
│   └── src/chongming_gateway/
├── cli/                    # ★ CLI 工具 — 脚手架 & 构建 & 追踪
│   └── src/chongming_cli/
├── workers/                # ★ Worker 服务实例（你的业务代码放这里）
│   ├── example/            #   Python Worker 完整示例（建议从这开始）
│   │   ├── config.toml     #     ← Worker 的"心脏"，所有配置在此
│   │   └── ...
│   └── example_rs/         #   Rust Worker 示例
│       ├── config.toml     #     ← 也是 config.toml！
│       └── ...
├── templates/              # ★ Worker 脚手架模板
│   ├── python/             #   Python Worker 模板
│   └── rust/               #   Rust Worker 模板
├── utils/                  # ★ 公共工具包
│   ├── worker/             #   chongming-worker — Python Worker 框架（核心！）
│   ├── config/             #   chongming-config — TOML 配置加载
│   ├── cache/              #   chongming-cache — NATS JetStream KV 缓存
│   ├── lock/               #   chongming-lock — 6 种分布式锁
│   ├── logging/            #   chongming-logging — 统一日志 + 分布式追踪
│   ├── jwt/                #   chongming-jwt — JWT 认证
│   ├── database/           #   chongming-database — 数据库管理与迁移
│   └── permission/         #   chongming-permission — 权限缓存
├── docker-env/             # ★ Docker 基础设施编排
├── front/                  # ★ Vue 3 管理面板
└── docs/                   # ★ 技术文档
```

---

## 🚀 快速开始

### 前置条件

- Python 3.12+
- Docker & Docker Compose（可选，但推荐）
- Rust 工具链（仅 Rust Worker 需要）

### 第 1 步：启动基础设施

```bash
cd docker-env
docker compose up -d

# 确认所有服务运行中
docker compose ps
```

### 第 2 步：启动 API Gateway

```bash
cd api_gateway
uv sync
uv run serve

# 验证
curl http://localhost:8000/health
```

### 第 3 步：启动示例 Worker（Python）

```bash
cd workers/example
uv sync
python main.py
```

Worker 启动后会自动**读取 `config.toml`** → 连接 NATS → 向 Gateway 注册路由。**所有行为均由 `config.toml` 驱动**。

### 第 4 步：验证完整链路

```bash
# 健康检查
curl http://localhost:8000/health

# 计算器 API
curl "http://localhost:8000/api/v1/calc/add?a=10&b=20"       # → {"result": 30}
curl "http://localhost:8000/api/v1/calc/divide?a=100&b=3"    # → {"result": 33.33}

# Worker 间通讯（order.create 内部调用 user.query + publish 通知）
curl -X POST "http://localhost:8000/api/v1/order/create" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "u001", "amount": 30, "item": "book"}'

# 追踪请求-响应链路
chongming trace calc.add --follow

# Swagger UI
open http://localhost:8000/docs
```

---

## 📚 文档导航

| 文档 | 适合读者 | 内容 |
|------|----------|------|
| **[Worker 框架 (Python)](utils/python/worker/README.md)** | **所有开发者（从这里开始）** | Worker 生命周期、handler 开发、服务间通信、**config.toml 各字段详解** |
| **[Worker 示例](workers/example/README.md)** | **初学者** | **基于 config.toml 的完整功能演示**，覆盖全部特性 |
| **[CLI 工具](cli/README.md)** | 所有开发者 | 脚手架创建、模型生成、构建部署、**trace 链路追踪**、**config.toml 完整参考** |
| **[API Gateway](api_gateway/README.md)** | 后端开发者 | 网关配置、部署、API 参考 |
| **[Docker 部署](docker-env/README.md)** | DevOps | 基础设施部署、生产环境配置 |
| **[Worker 框架 (Rust)](utils/rust/worker/README.md)** | Rust 开发者 | Rust Worker 开发指南 |
| **[分布式锁](utils/lock/README.md)** | 高级开发者 | 6 种锁类型及使用示例 |
| **[缓存工具](utils/cache/README.md)** | 开发者 | NATS JetStream KV 缓存使用 |
| **[JWT 认证](utils/jwt/README.md)** | 后端开发者 | Token 创建与验证 |
| **[数据库工具](utils/database/README.md)** | 后端开发者 | 数据库连接管理 + Alembic 迁移 |
| **[权限管理](utils/permission/README.md)** | 开发者 | 基于 NATS KV 的分布式权限缓存 |
| **[前端面板](front/chongming_front/README.md)** | 前端开发者 | Vue 3 管理面板开发 |
| **[API 参考](docs/api/README.md)** | 框架开发者 | 完整内部 API 技术文档 |

### 按角色推荐阅读顺序

- **👤 新手入门** → `utils/python/worker/README.md` → `workers/example/README.md` → `cli/README.md`
- **🔧 开发 Worker** → 先看 `config.toml` → `utils/python/worker/README.md` → `workers/example/README.md`
- **🔍 调试追踪** → `cli/README.md#trace` → `chongming trace --help`
- **🚀 生产部署** → `cli/README.md` → `docker-env/README.md`

---

## 🏗️ 核心数据流

```
┌─────────┐      HTTP       ┌──────────────┐     NATS Request     ┌─────────────┐
│  Client  │ ───────────────→│ API Gateway  │ ──────────────────→ │   Worker    │
│          │                │  (FastAPI)    │                     │ (业务逻辑)    │
│          │ ←──────────────│              │ ←────────────────── │             │
└─────────┘     JSON        └──────┬───────┘     JSON Response   └─────────────┘
                                   │
                          NATS JetStream KV
                                   │
                          ┌────────▼────────┐
                          │   分布式锁/缓存   │
                          │  (6 种锁类型)     │
                          └─────────────────┘
```

**关键链路：config.toml → Gateway 路由注册 → 请求分发**

1. **Worker 启动** → 读取 `config.toml` → 通过 `service.registry` 向 Gateway 注册 routes
2. **客户端** → 发送 HTTP 请求到 **API Gateway**
3. **API Gateway** → 查找匹配的 Worker → 通过 NATS Request-Reply 转发
4. **Worker** → 接收消息 → 提取 request_id（分布式追踪）→ 解析参数 → 调用业务 handler
5. **Worker** → 返回结果 → Gateway 响应客户端
6. **Swagger UI** → `http://localhost:8000/docs` 自动展示所有动态路由

### 调试：实时追踪请求链路

```bash
# 追踪一次请求-响应
chongming trace user.register

# 持续追踪（按 Ctrl+C 停止）
chongming trace calc.add --follow --pretty

# 追踪 3 对后退出
chongming trace order.create --count 3 --no-response-payload
```

输出示例：

```
[2026-06-04 10:00:00] [request_id=abc-123] REQ user.register (duration: waiting...)
Payload: {"username": "admin123", "password": "***", "email": "admin@example.com"}

[2026-06-04 10:00:01] [request_id=abc-123] RSP (took 1.02s)
Payload: {"status": true, "user_id": 1001, "token": "***"}
```

---

## 🛠️ 技术栈

| 分类 | 技术 | 用途 |
|------|------|------|
| **消息队列** | NATS 2.10 | 服务间通信、JetStream KV、Queue Group |
| **API 网关** | FastAPI + Uvicorn/Gunicorn | HTTP 路由、OpenAPI 文档 |
| **Worker (Python)** | asyncio + NATS-Py | 业务逻辑处理 |
| **Worker (Rust)** | tokio + async-nats | 高性能业务处理 |
| **配置管理** | **TOML** | **`config.toml` 统一配置格式，Worker 的唯一配置来源** |
| **容器编排** | Docker Compose | 基础设施部署 |
| **前端** | Vue 3 + Vite + TypeScript | 管理面板 |
| **构建工具** | PyInstaller / Cargo | 二进制编译 |
| **数据库** | PostgreSQL (主备) | 持久化存储 |
| **对象存储** | MinIO (分布式) | 文件/日志存储 |

---

## 📦 分布式锁 — 6 种类型

| 锁类型 | 类名 | 适用场景 |
|--------|------|----------|
| 🥇 互斥锁 | `MutexLock` | 资源独占访问 |
| 📖 读写锁 | `ReadWriteLock` | 读多写少场景 |
| 🔢 信号量 | `SemaphoreLock` | 连接池、限流 |
| 🔁 可重入锁 | `ReentrantLock` | 递归调用 |
| ⏱️ 租约锁 | `LeaseLock` | Leader Election |
| 🛡️ 栅栏令牌锁 | `FencingTokenLock` | 防僵尸节点 |

所有锁基于 NATS JetStream KV 实现，天然支持多进程并发、崩溃自动恢复。

---

## 🐳 生产部署

```bash
# 1. 构建二进制镜像（推荐）
cd cli && uv sync
chongming binary-build gateway --tag registry.example.com/gateway:v1.0
chongming binary-build example --tag registry.example.com/example:v1.0

# 2. 启动生产环境
cd docker-env
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# 3. 验证
curl http://localhost:8080/health
```

**二进制部署优势：**
- 镜像仅 ~20-30MB（对比 Python 运行时 ~200-300MB）
- 启动毫秒级
- 不包含源码，保护知识产权

---

## 🤝 贡献指南

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'feat: add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request

### 开发约定

- Python 3.12+，使用 `uv` 管理依赖
- Rust 1.80+，使用 `cargo` 管理依赖
- 遵循 [Conventional Commits](https://www.conventionalcommits.org/)
- 提交前运行 `uv run ruff check` 和 `cargo clippy`

---

## 📄 许可

[MIT License](LICENSE) — 详见 LICENSE 文件