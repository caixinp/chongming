# Chongming CLI — 项目管理与构建工具

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

一站式项目管理命令行工具，覆盖微服务全生命周期：项目脚手架创建、模型代码生成、Docker 镜像构建、生产级二进制打包、本地开发服务器启动、日志导出、NATS 链路追踪、直接请求发送和数据库迁移管理。

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
├── trace           实时追踪 NATS 请求-响应链路（支持多 subject）
├── request         直接向 NATS subject 发送请求（绕过网关）
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

## chongming trace — NATS 请求链路追踪

实时或历史追踪 NATS 请求-响应链路，自动关联 `request_id` 并打印格式化的彩色输出。支持同时监听多个 subject。

```bash
# 追踪单个 subject
chongming trace user.register

# 同时追踪多个 subject
chongming trace user.login user.register calc.add --follow

# 持续追踪
chongming trace calc.add --follow

# 追踪 3 对后退出
chongming trace order.create --count 3

# 美化输出，隐藏 payload
chongming trace calc.add --pretty --no-request-payload --no-response-payload

# 回放最近 1 小时历史（需要 JetStream）
chongming trace user.register --since 1h --js

# 指定 NATS 连接参数
chongming trace user.register --host nats.example.com --port 4222 --creds ./nats.creds
```

| 参数 | 说明 |
|------|------|
| `subjects` | 要追踪的业务主题（支持多个），如 `user.register` |
| `--follow`, `-f` | 持续监听，直到手动停止（Ctrl+C） |
| `--count`, `-n` | 接收 N 对请求-响应后退出（默认 1，`--follow` 模式下无限） |
| `--since` | 使用 JetStream 回放最近一段时间的历史消息（如 `1h`、`30m`），自动启用 `--js` |
| `--js` | 启用 JetStream 模式 |
| `--pretty` | 美化输出 JSON（多行缩进） |
| `--no-request-payload` | 不打印请求 payload |
| `--no-response-payload` | 不打印响应 payload |

**NATS 连接参数：** `--host`、`--port`、`--user`、`--password`、`--token`、`--creds`、`--nkey`、`--tls`、`--tls-cert`、`--tls-key`、`--tls-ca`

**JetStream 参数：** `--stream`（指定 stream 名称）、`--js-domain`

### 工作原理

1. 订阅所有业务 subject（支持同时监听多个主题）
2. 捕获请求消息 → 提取 `request_id`（从 headers）和 `reply` 主题
3. 动态订阅 reply 主题（每个请求独立订阅，用完即取消）
4. 收到响应 → 计算耗时 → 格式化输出
5. 5 秒超时 → 打印超时提示

### 输出示例

```
[2026-06-04 10:00:00] [request_id=abc-123] REQ user.register (duration: waiting...)
  Payload: {"username": "admin123", "password": "***", "email": "admin@example.com"}

[2026-06-04 10:00:01] [request_id=abc-123] RSP (took 1.02s)
  Payload: {"status": true, "user_id": 1001, "token": "***"}
```

### 特性

- **彩色输出**：时间戳（暗色）、REQ（绿色）、RSP（蓝色）、超时（红色）、request_id（黄色）、耗时（品红色）
- **多 subject 支持**：可同时监听多个业务主题，消息按实际 subject 分组显示
- **request_id 关联**：从 NATS headers 提取 `request_id` 自动关联请求与响应
- **自动脱敏**：`password`、`token`、`secret` 等字段自动替换为 `***`
- **动态 reply 订阅**：每个请求独立订阅其 reply 主题，避免通配符订阅的开销
- **超时处理**：5 秒未收到响应打印超时提示并继续
- **并发安全**：多请求同时在途时独立管理各自状态
- **JetStream 历史回放**：通过 `--since 1h --js` 回放最近一小时的请求-响应

---

## chongming request — 直接发送 NATS 请求

直接向 NATS subject 发送请求（绕过 API Gateway），适用于本地调试和测试脚本。支持 CLI 命令和 Python 函数导入两种使用方式。

### CLI 使用

```bash
# 携带 JSON payload 发送请求
chongming request user.register --data '{"email": "test@example.com", "password": "123456"}'

# 从文件读取 payload
chongming request user.register --file payload.json

# 通过管道 stdin 传入
echo '{"email": "test@example.com"}' | chongming request user.register

# 美化输出
chongming request user.register --data '{"email": "test@example.com"}' --pretty

# 自定义超时
chongming request user.login --data '{"email": "test@example.com"}' --timeout 10

# 指定 NATS 连接参数
chongming request user.register --data '{"email": "test@example.com"}' --host nats.example.com --port 4222 --creds ./nats.creds
```

| 参数 | 说明 |
|------|------|
| `subject` | 要请求的业务主题，如 `user.register` |
| `--data`, `-d` | 请求 JSON payload（字符串） |
| `--file`, `-f` | 从文件读取请求 payload（JSON） |
| `--timeout`, `-t` | 请求超时秒数（默认 10 秒） |
| `--pretty` | 美化输出响应 JSON |

**NATS 连接参数：** `--host`、`--port`、`--user`、`--password`、`--token`、`--creds`、`--nkey`、`--tls`、`--tls-cert`、`--tls-key`、`--tls-ca`

### 测试脚本使用（Python）

```python
import asyncio
from chongming_cli.commands.request import send_request

async def test_register():
    result = await send_request(
        "user.register",
        {"email": "test@example.com", "password": "123456"},
        timeout=10,
    )
    assert result["status"] is True

async def test_with_auth():
    result = await send_request(
        "user.login",
        {"email": "test@example.com", "password": "123456"},
        host="nats.example.com",
        port=4222,
        user="admin",
        password="secret",
    )
    print(result["token"])

asyncio.run(test_register())
```

`send_request` 参数说明：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `subject` | `str` | 必填 | NATS 业务主题 |
| `payload` | `dict` | 必填 | 请求数据 |
| `host` | `str` | `"localhost"` | NATS 服务器地址 |
| `port` | `int` | `4222` | NATS 服务器端口 |
| `timeout` | `float` | `10.0` | 请求超时秒数 |
| `token` | `str` | `None` | NATS 认证令牌 |
| `user` | `str` | `None` | NATS 用户名 |
| `password` | `str` | `None` | NATS 密码 |
| `creds` | `str` | `None` | 用户凭证文件路径 |
| `nkey` | `str` | `None` | NKEY 种子文件路径 |
| `tls` | `bool` | `False` | 启用 TLS |
| `tls_ca` | `str` | `None` | TLS CA 证书路径 |
| `tls_cert` | `str` | `None` | TLS 客户端证书路径 |
| `tls_key` | `str` | `None` | TLS 客户端密钥路径 |

**返回值：** 解析后的响应 `dict`

**可能抛出的异常：**
- `asyncio.TimeoutError` — 请求超时
- `nats.errors.NoRespondersError` — 没有 Worker 订阅该 subject
- `nats.errors.BadSubjectError` — 无效的 subject

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
│           ├── __init__.py       # 入口 + 子命令注册
│           └── commands/
│               ├── new.py         # 创建项目
│               ├── gen_models.py  # 模型生成
│               ├── gateway.py     # Gateway 启动
│               ├── worker.py      # Worker 启动
│               ├── trace.py       # NATS 链路追踪（多 subject + 彩色输出）
│               ├── request.py     # NATS 直接请求（CLI + 测试脚本）
│               ├── docker_build.py# Docker 构建
│               ├── binary_build.py# 二进制构建
│               ├── docker.py     # Docker 环境
│               ├── image_export.py# 镜像导出
│               ├── log_export.py # 日志导出
│               └── migrate.py    # 数据库迁移
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