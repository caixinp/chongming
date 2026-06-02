# Chongming CLI — 项目管理与构建工具

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Typer](https://img.shields.io/badge/typer-0.12-blue.svg)](https://typer.tiangolo.com/)

一站式项目管理命令行工具，覆盖微服务全生命周期：项目脚手架创建、模型代码生成、Docker 镜像构建、生产级二进制打包、本地开发服务器启动、日志导出和数据库迁移管理。

---

## 安装

```bash
# 推荐：本地开发安装（使用 uv）
cd cli
uv sync

# 全局安装
pip install chongming-cli
```

安装后即可使用 `chongming` 命令。

---

## 命令树

```
chongming
├── new             创建新项目模板（Python / Rust）
├── gen-models      从 config.toml 生成 Pydantic 模型
├── gateway         启动 API Gateway
├── worker          启动 Worker
├── docker-build    构建 Docker 镜像
├── binary-build    构建二进制 Docker 镜像（推荐生产）
├── docker          Docker Compose 环境管理
├── image-export    导出 Docker 镜像为 tar 包
├── log-export      从 MinIO 导出日志
└── db              数据库迁移管理
```

---

## chongming new — 创建新项目

从模板快速生成 Worker 或 Gateway 项目。

```bash
# 创建 Python Worker（默认）
chongming new my-service

# 创建 Rust Worker
chongming new my-service --lang rust

# 跳过虚拟环境创建
chongming new my-service --no-venv
```

| 参数 | 说明 |
|------|------|
| `name` | Worker 名称（目录名，必填） |
| `--lang` | 语言：`python`（默认）或 `rust` |
| `--no-venv` | 跳过虚拟环境创建（仅 Python） |

**模板来源：**
- Python → `templates/python/`（基于 `workers/example`，含完整的 WorkerLifespan 特性）
- Rust → `templates/rust/`（基于 `workers/example_rs`）

**自动处理：**
- 重命名 `config.toml` 中的 Worker 名称和占位符
- Python 模式自动创建虚拟环境（`uv sync`）
- 生成唯一 UUID 作为 Worker ID

---

## chongming gen-models — 生成 Pydantic 模型

从 Worker 的 `config.toml` 中读取路由注册信息，自动生成类型安全的 Pydantic 请求/响应模型代码。

```bash
# 为指定 Worker 生成模型（默认输出到 models/__init__.py）
chongming gen-models example

# 预览生成的模型（不写文件）
chongming gen-models example --dry-run

# 为所有 Worker 生成模型
chongming gen-models --all

# 生成共享模型到 public 目录（跨 Worker 复用）
chongming gen-models example --output workers/example/public/__init__.py --shared
```

| 参数 | 说明 |
|------|------|
| `name` | Worker 名称（对应 `workers/` 下的子目录），不传则使用当前目录 |
| `--all` | 为所有 Worker 生成模型 |
| `--dry-run` | 仅预览，不写文件 |
| `--output` | 指定输出路径，覆盖默认的 `models/__init__.py` |
| `--shared` | 仅生成标记为 `shared=true` 的 handler 模型 |

### 工作原理

1. 读取 `config.toml` → `registration.items` 的每个 handler 配置
2. 根据 `params` 生成 Pydantic 请求模型
3. 根据 `response_model` 生成 Pydantic 响应模型
4. 支持嵌套 `object` 类型，递归生成子模型
5. `__required__` → 必填字段，其他值 → 可选字段（带默认值）

### 跨 Worker 共享模型

```toml
items = [
    {
        subject = "user.query",
        shared = true,               # 标记为共享模型
        params = ["user_id: str"],
        response_model = {
            user_id = ["str", "__required__"],
            name = ["str", "__required__"],
            balance = ["float", 0.0]
        }
    }
]
```

```bash
# 生成共享模型
chongming gen-models example --output workers/example/public/__init__.py --shared

# 其他 Worker 导入使用
from workers.example.public import UserQueryOutput
```

---

## chongming gateway — 启动 API Gateway

```bash
# 开发模式（单进程，热重载）
chongming gateway

# 生产模式（Gunicorn + 多进程）
chongming gateway --production

# 自定义地址和端口
chongming gateway --host 127.0.0.1 --port 8080 --reload
```

| 参数 | 说明 |
|------|------|
| `--host` | 监听地址，默认 `0.0.0.0` |
| `--port`, `-p` | 端口，默认 `8000` |
| `--production` | Gunicorn 生产模式（4 workers） |
| `--reload` | 启用热重载 |
| `--no-reload` | 禁用热重载 |

---

## chongming worker — 启动 Worker

自动检测 Worker 类型并启动。

```bash
# 启动指定 Worker
chongming worker example

# 启动所有 Worker
chongming worker --all

# 列出可用 Worker
chongming worker --list
```

| 参数 | 说明 |
|------|------|
| `name` | Worker 名称（对应 `workers/` 下的子目录） |
| `--all`, `-a` | 启动所有 Worker |
| `--list`, `-l` | 列出所有可用 Worker |

**自动检测：**
- 存在 `Cargo.toml` → Rust Worker → `cargo run`
- 否则 → Python Worker → `uv run python main.py`

---

## chongming docker-build — 构建 Docker 镜像

```bash
# 构建 Python Worker
chongming docker-build example

# 构建 Rust Worker
chongming docker-build example_rs

# 指定标签并推送
chongming docker-build example --tag registry.example.com/example:v1.0 --push

# 不缓存构建
chongming docker-build example --no-cache
```

| 参数 | 说明 |
|------|------|
| `name` | 服务名称（必填） |
| `--tag`, `-t` | 镜像标签，默认 `chongming/<name>:latest` |
| `--push` | 推送至镜像仓库 |
| `--no-cache` | 不使用缓存 |
| `--dockerfile`, `-f` | 指定 Dockerfile，默认自动检测 |

**自动 Dockerfile 检测：**
- 包含 `Cargo.toml` → `worker-rust.Dockerfile`
- 否则 → `worker.Dockerfile`

---

## chongming binary-build — 构建二进制镜像

使用 **PyInstaller** 将 Python 代码编译为单文件二进制，再打包为极小 Docker 镜像。**推荐生产部署方式。**

```bash
chongming binary-build gateway --tag registry.example.com/gateway:v1.0
chongming binary-build example
```

### 构建模式对比

| 特性 | `docker-build` | `binary-build` ✅ |
|------|---------------|-------------------|
| 基础镜像 | `python:3.12-slim` (~120MB) | `busybox:glibc` (~5MB) |
| 最终镜像 | ~200-300MB | ~20-30MB |
| 构建时间 | ~15-20s | ~60s |
| 启动速度 | 秒级 | **毫秒级** |
| 源码保护 | ❌ 包含 .py | ✅ 编译为二进制 |
| 环境依赖 | 需 pip + Python | 无依赖 |
| 适用环境 | 开发 / CI | **生产部署** |

### 构建流程

```
Python 源码 → PyInstaller 编译 → 单文件二进制 → busybox Docker 镜像
```

---

## chongming docker — Docker Compose 环境管理

```bash
# 启动开发环境
chongming docker up

# 启动生产环境（含 Nginx 负载均衡）
chongming docker up --prod

# 查看服务状态
chongming docker ps

# 停止并清理
chongming docker down
```

---

## chongming image-export — 导出镜像

导出 Docker Compose 中使用的所有镜像为 tar 文件，便于离线环境部署。

```bash
chongming image-export --output ./images
```

---

## chongming log-export — 从 MinIO 导出日志

按条件查询并导出 Worker 或 Gateway 的日志。

```bash
# 列出可用服务实例
chongming log-export --list-services

# 导出指定 Worker 最近 1 小时日志
chongming log-export --type worker --name example --since 1h

# 导出 DEBUG 级别日志到文件
chongming log-export --type worker --name example --level DEBUG --output /tmp/logs.json

# 统计日志存储使用量
chongming log-export --stats
```

| 参数 | 说明 |
|------|------|
| `--type` | 服务类型：`gateway` 或 `worker` |
| `--name` | 服务实例名称 |
| `--since` | 时间范围（如 `1h`、`30m`） |
| `--start` / `--end` | 精确时间范围 |
| `--level` | 日志级别：`DEBUG`、`INFO`、`WARNING`、`ERROR` |
| `--format` | 输出格式：`json`（默认）或 `text` |
| `--output` | 输出文件路径 |
| `--list-services` | 列举可用服务实例 |
| `--stats` | 统计日志存储使用量 |

---

## chongming db — 数据库迁移管理

基于 **Alembic** 的数据库迁移管理，迁移文件位于 `utils/python/database/migrations/`。

```bash
# 查看当前数据库版本
chongming db current --db-url "postgresql://user:pass@localhost:5432/dbname"

# 查看迁移历史
chongming db history

# 创建增量迁移（模型变更后）
chongming db migrate -m "add user table" --db-url "..."

# 应用迁移
chongming db upgrade --db-url "..."

# 回滚一步
chongming db downgrade --db-url "..."

# 标记已有数据库的版本
chongming db stamp 0001 --db-url "..."

# 离线生成 SQL 脚本
chongming db upgrade head --sql
```

### 迁移文件结构

```
utils/python/database/migrations/
├── env.py                    # Alembic 环境配置
├── script.py.mako            # 迁移模板
└── versions/
    ├── 0001_initial_empty.py # 空基线（标记初始状态）
    └── 0002_user_id_bigint.py # Snowflake ID 迁移示例
```

---

## 配置参考

### Worker config.toml 格式

`config.toml` 是 Worker 的核心配置文件，所有 `chongming` 子命令（`gen-models`、`worker`、`docker-build` 等）都依赖此文件。

```toml
[worker]
name = "example"              # Worker 名称（唯一标识）
version = "0.1.0"
description = "示例 Worker"

[nats]
urls = [
    "nats://localhost:4222",
    "nats://localhost:4223",
    "nats://localhost:4224"
]

[registration]
type = "register"
service = "example"           # 服务名，Gateway 路由前缀
queue_group = "calc-workers"  # 同组 Worker 负载均衡
router_prefix = "/calc"
tags = ["calculator"]
heartbeat_interval = 15       # 心跳间隔（秒）

items = [
    # ── 每个 handler 一条路由 ──
    {
        subject = "calc.add",
        method = "GET",
        path = "/add",
        summary = "加法运算",
        params = ["a: float", "b: float"],
        ttl = 30,                       # TTL > heartbeat_interval
        timeout = 2.0,
        response_model = {
            result = ["float", "__required__"],
            operation = ["str", "add"],
            timestamp = ["float", 0.0]
        },
        shared = true,                  # 共享模型（gen-models --shared 选中）
        internal = false,               # 是否在 Swagger 隐藏
        auth_required = false,          # 是否需 JWT 认证
    },
]

[logging.minio]
enabled = true
endpoint = "localhost:9000"
bucket = "chongming-logs"
```

完整配置详解参考 [Worker 生命周期框架文档](../utils/python/worker/README.md#configtoml-配置参考)。

---

## 项目结构依赖

```
chongming/
├── cli/                          # ← CLI 工具本身
│   ├── pyproject.toml
│   └── src/
│       └── chongming_cli/
│           ├── __main__.py       # 入口：typer 应用
│           └── commands/
│               ├── new.py         # 创建项目
│               ├── gen_models.py  # 模型生成
│               ├── gateway.py     # Gateway 启动
│               ├── worker.py      # Worker 启动
│               ├── docker_build.py# Docker 构建
│               ├── binary_build.py# 二进制构建
│               ├── docker.py     # Docker 环境
│               ├── image_export.py# 镜像导出
│               ├── log_export.py # 日志导出
│               └── gen_migrate.py # 数据库迁移
├── workers/                      # ← Worker 实例（被操作对象）
├── templates/                    # ← 项目模板（被 new 命令读取）
├── utils/python/worker/          # ← Worker 框架（被 worker 命令启动）
└── utils/python/database/        # ← 数据库迁移（被 db 命令管理）
```

---

## 相关文档

| 文档 | 说明 |
|------|------|
| [API Gateway 文档](../api_gateway/README.md) | Gateway 架构和行为 |
| [Worker 框架文档](../utils/python/worker/README.md) | Worker 生命周期、handler 开发、config.toml 详解 |
| [Docker 部署文档](../docker-env/README.md) | 生产环境 Docker Compose 编排 |
| [数据库工具文档](../utils/python/database/README.md) | 数据库初始化和迁移 |
| [User Auth Worker](../workers/user_auth/README.md) | 实际 Worker 开发示例 |
