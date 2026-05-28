# Chongming — 基于 NATS 的微服务平台

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![NATS](https://img.shields.io/badge/NATS-2.10-green.svg)](https://nats.io/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-teal.svg)](https://fastapi.tiangolo.com/)

Chongming 是一个基于 NATS 消息队列的 Python 微服务框架，提供动态路由注册、服务发现、负载均衡和优雅关闭等功能，帮助开发者快速构建可扩展的分布式系统。

---

## 项目架构

```
chongming/
├── api_gateway/             # FastAPI 网关 — HTTP 请求转发层
│   └── src/chongming_gateway/
│
├── cli/                     # CLI 工具 — 项目脚手架与构建工具
│   └── src/chongming_cli/
│
├── utils/                   # 公共工具包
│   ├── cache/               # 缓存工具（NATS JetStream KV）
│   ├── config/              # 配置加载工具（TOML）
│   ├── lock/                # 分布式锁库（6 种锁类型）
│   ├── logging/             # 统一日志配置
│   └── worker/              # Worker 生命周期框架
│
├── workers/                 # 业务 Worker 服务
│   └── example/             # 示例计算器 Worker
│
├── docker-env/              # Docker 基础设施配置
├── front/                   # 前端应用
│   └── chongming_front/     # Vue 3 + Vite 管理面板
└── build/                   # 构建产物
```

---

## 核心组件

### API Gateway
基于 FastAPI + NATS 的动态路由网关，作为微服务流量入口。接收 HTTP 请求，通过 NATS Request/Reply 模式转发到对应的 Worker 服务，自动管理路由注册与心跳保活。

### Worker 框架
自动处理 NATS 连接、服务注册、心跳保活、消息分发和优雅关闭，开发者只需关注纯业务逻辑。支持 Queue Group 负载均衡。

### 分布式锁
基于 NATS JetStream KV 的完整分布式锁库，提供互斥锁、读写锁、信号量、可重入锁、租约锁、栅栏令牌锁共 6 种锁类型。

### CLI 工具
一站式脚手架工具，支持快速创建新 Worker、构建 Docker 镜像、编译二进制文件（PyInstaller/Nuitka）。

### 基础设施
| 组件 | 用途 | 高可用 |
|------|------|--------|
| NATS | 消息队列 / 微服务间通信 | 3 节点集群 |
| PostgreSQL | 关系型数据库 | 主备自动故障转移 |
| MinIO | 对象存储 | 2 节点分布式 |

---

## 快速开始

### 1. 启动基础设施

```bash
cd docker-env
docker compose up -d
```

### 2. 启动 API Gateway

```bash
cd api_gateway
uv sync
uv run serve
```

### 3. 启动示例 Worker

```bash
cd workers/example
uv sync
python main.py
```

### 4. 验证

```bash
# 健康检查
curl http://localhost:8000/health

# 计算器 API
curl "http://localhost:8000/api/v1/calc/add?a=10&b=20"
curl "http://localhost:8000/api/v1/calc/multiply?a=6&b=7"
```

---

## 相关文档

| 文档 | 用途 |
|------|------|
| [API Gateway 文档](api_gateway/README.md) | 网关配置、部署、API 参考 |
| [CLI 工具文档](cli/README.md) | 脚手架命令、构建打包 |
| [Docker 部署文档](docker-env/README.md) | 基础设施部署、生产环境配置 |
| [Worker 框架文档](utils/worker/README.md) | Worker 生命周期开发指南 |
| [分布式锁文档](utils/lock/README.md) | 6 种锁类型及使用示例 |
| [前端文档](front/chongming_front/README.md) | Vue 管理面板开发 |
| [示例 Worker](workers/example/README.md) | 计算器微服务示例 |

---

## 许可

MIT
