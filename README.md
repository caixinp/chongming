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
| **开源 API 文档** | 动态路由自动生成 OpenAPI/Swagger 文档 |
| **分布式追踪** | request_id 贯穿 Gateway → Worker 全链路 |
| **二进制部署** | PyInstaller 编译为单文件二进制，镜像仅 ~20MB |
| **Docker 一键部署** | 开发/生产双模式 Docker Compose 编排 |

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
│(calc)  ││(demo)  ││  │PostgreSQL│ │  MinIO   │ │  Redis   │ │
└────────┘└────────┘│  │主备自动切换│ │对象存储2节点│ │(可选)    │ │
                    │  └─────────┘ └──────────┘ └──────────┘ │
                    └─────────────────────────────────────────┘
```

### 目录结构

```
chongming/
├── api_gateway/            # ★ API Gateway — FastAPI 动态路由网关
│   └── src/chongming_gateway/
├── cli/                    # ★ CLI 工具 — 脚手架 & 构建
│   └── src/chongming_cli/
├── workers/                # ★ Worker 服务实例
│   ├── example/            #   Python Worker 示例（计算器 + Worker 间通讯）
│   ├── example_rs/         #   Rust Worker 示例
│   └── worker_comm/        #   Python Worker 间通讯专题示例
├── templates/              # ★ Worker 脚手架模板
│   ├── python/             #   Python Worker 模板（来自 example，含全部特性）
│   └── rust/               #   Rust Worker 模板（来自 example_rs）
├── utils/                  # ★ 公共工具包（发布为独立 PyPI 包）
│   ├── cache/              #   chongming-cache — NATS JetStream KV 缓存
│   ├── config/             #   chongming-config — TOML 配置加载
│   ├── lock/               #   chongming-lock — 6 种分布式锁
│   ├── logging/            #   chongming-logging — 统一日志
│   └── worker/             #   chongming-worker — Python Worker 框架
├── docker-env/             # ★ Docker 基础设施编排
├── front/                  # ★ Vue 3 管理面板
│   └── chongming_front/
├── docs/                   # ★ 技术文档
│   └── api/                #   API 参考文档
└── build/                  #   构建产物
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

### 第 3 步：启动示例 Worker

```bash
# Python Worker
cd workers/example
uv sync
python main.py

# 或 Rust Worker
cd workers/example_rs
cargo run
```

### 第 4 步：验证完整链路

```bash
# 健康检查
curl http://localhost:8000/health

# 计算器 API
curl "http://localhost:8000/api/v1/calc/add?a=10&b=20"    # → 30
curl "http://localhost:8000/api/v1/calc/subtract?a=30&b=10" # → 20
curl "http://localhost:8000/api/v1/calc/multiply?a=6&b=7"   # → 42
curl "http://localhost:8000/api/v1/calc/divide?a=100&b=3"   # → 33.33

# Swagger UI（浏览器打开）
open http://localhost:8000/docs
```

---

## 📚 文档导航

| 文档 | 适合读者 | 内容 |
|------|----------|------|
| **[API Gateway](api_gateway/README.md)** | 后端开发者 | 网关配置、部署、API 参考 |
| **[CLI 工具](cli/README.md)** | 所有开发者 | 脚手架、构建、部署命令 |
| **[Docker 部署](docker-env/README.md)** | DevOps | 基础设施部署、生产环境配置 |
| **[Worker 框架 (Python)](utils/worker/README.md)** | Python 开发者 | Worker 生命周期开发指南 |
| **[Worker 框架 (Rust)](utils/rust/worker/README.md)** | Rust 开发者 | Rust Worker 开发指南 |
| **[分布式锁](utils/lock/README.md)** | 高级开发者 | 6 种锁类型及使用示例 |
| **[缓存工具](utils/cache/README.md)** | 开发者 | NATS JetStream KV 缓存使用 |
| **[前端面板](front/chongming_front/README.md)** | 前端开发者 | Vue 3 管理面板开发 |
| **[API 参考](docs/api/README.md)** | 框架开发者 | 完整内部 API 技术文档 |

### 按角色推荐

- **新建微服务** → `cli/README.md` → `chongming new`
- **开发 Worker** → `utils/worker/README.md`
- **本地调试** → `docker-env/README.md` → 启动基础设施
- **生产部署** → `cli/README.md` → `chongming binary-build`
- **阅读源码** → `docs/api/README.md`

---

## 🏗️ 核心数据流

```
┌─────────┐      HTTP       ┌──────────────┐     NATS Request     ┌─────────────┐
│  Client  │ ───────────────→│ API Gateway  │ ──────────────────→ │   Worker    │
│          │                │  (FastAPI)    │                     │ (Python/Rust)│
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

1. **客户端** → 发送 HTTP 请求到 **API Gateway**
2. **API Gateway** → 通过 NATS Request-Reply 转发到 **Worker**
3. **Worker** → 处理业务逻辑，可选使用分布式锁/缓存
4. **Worker** → 返回结果，Gateway 响应客户端
5. **自动文档** → 动态路由自动出现在 `/docs` Swagger UI

---

## 🛠️ 技术栈

| 分类 | 技术 | 用途 |
|------|------|------|
| **消息队列** | NATS 2.10 | 服务间通信、JetStream KV、Queue Group |
| **API 网关** | FastAPI + Uvicorn/Gunicorn | HTTP 路由、OpenAPI 文档 |
| **Worker (Python)** | asyncio + NATS-Py | 业务逻辑处理 |
| **Worker (Rust)** | tokio + async-nats | 高性能业务处理 |
| **配置管理** | TOML | 统一配置格式 |
| **容器编排** | Docker Compose | 基础设施部署 |
| **前端** | Vue 3 + Vite + TypeScript | 管理面板 |
| **构建工具** | PyInstaller / Nuitka / Cargo | 二进制编译 |
| **数据库** | PostgreSQL (主备) | 持久化存储 |
| **对象存储** | MinIO (分布式) | 文件存储 |

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
