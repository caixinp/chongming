# Chongming CLI — 项目管理与构建工具

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

一站式项目管理命令行工具，支持项目脚手架创建、Pydantic 模型生成、Docker 镜像构建、生产级二进制打包、本地开发服务器启动等功能，覆盖微服务全生命周期。

---

## 安装

```bash
# 推荐：本地开发安装（使用 uv）
cd cli
uv sync

# 或通过 pip 安装
pip install chongming-cli
```

安装后即可使用 `chongming` 命令。

---

## 命令速览

| 命令 | 功能 | 文档 |
|------|------|------|
| `new` | 新建 Worker / Gateway 项目模板 | [👇 详解](#chongming-new--创建新项目) |
| `gen-models` | 从 config.toml 生成 Pydantic 模型 | [👇 详解](#chongming-gen-models--生成-pydantic-模型) |
| `gateway` | 启动 API Gateway 开发/生产服务器 | [👇 详解](#chongming-gateway--启动-gateway) |
| `worker` | 启动 Worker 服务 | [👇 详解](#chongming-worker--启动-worker) |
| `docker-build` | 构建 Docker 镜像（Python 运行时） | [👇 详解](#chongming-docker-build--构建-docker-镜像) |
| `binary-build` | 构建二进制 Docker 镜像（**推荐生产**） | [👇 详解](#chongming-binary-build--构建二进制镜像) |
| `docker` | Docker Compose 环境管理 | [👇 详解](#chongming-docker--管理-docker-环境) |
| `image-export` | 导出 Docker 镜像为离线 tar 包 | [👇 详解](#chongming-image-export--导出镜像) |
| `log-export` | 从 MinIO 导出日志 | [👇 详解](#chongming-log-export--导出日志) |

---

## 命令详解

### `chongming new` — 创建新项目

从模板快速生成 Worker 或 Gateway 项目，支持 Python 和 Rust。

```bash
# 创建 Python Worker（默认）
chongming new my-service

# 创建 Rust Worker
chongming new my-service --lang rust

# 不创建虚拟环境（仅 Python）
chongming new my-service --no-venv
```

**参数：**

| 参数 | 说明 |
|------|------|
| `name` | Worker 名称（目录名，必填） |
| `--lang` | 语言类型：`python`（默认）或 `rust` |
| `--no-venv` | 不创建虚拟环境（仅 Python） |

**模板行为：**
- **Python**：从 `workers/example` 复制模板，自动重命名配置文件和占位内容
- **Rust**：从 `workers/example_rs` 复制模板，自动重命名 `Cargo.toml` 和 `main.rs`

---

### `chongming gen-models` — 生成 Pydantic 模型

从 Worker 的 `config.toml` 配置中读取 handler 注册信息，自动生成类型安全的 Pydantic 请求/响应模型代码，减少手动编写模型代码的工作量。

```bash
# 为指定 worker 生成模型（默认输出到 models/__init__.py）
chongming gen-models example

# 预览生成的模型（不写文件）
chongming gen-models example --dry-run

# 为所有 worker 生成模型
chongming gen-models --all

# 生成共享模型到 public 目录（跨 Worker 复用）
chongming gen-models example --output public/__init__.py --shared
```

**参数：**

| 参数 | 说明 |
|------|------|
| `name` | Worker 名称（对应 `workers/` 下的子目录名），不传则使用当前目录 |
| `--all` | 为所有 Worker 生成模型（遍历 `workers/` 下所有含 `config.toml` 的目录） |
| `--dry-run` | 只预览生成的 Pydantic 模型代码，不写入文件 |
| `--output` | 指定输出文件路径（如 `public/__init__.py`），覆盖默认的 `models/__init__.py` |
| `--shared` | 只生成标记为 `shared = true` 的 handler 模型（用于跨 Worker 共享模型） |

**工作原理：**

1. 读取 `config.toml` 中 `registration.items` 注册的每个 handler 配置
2. 根据 handler 的参数签名和响应模型定义自动生成对应的 Pydantic 模型
3. 默认输出到 `models/__init__.py`，通过 `--output` 可指定自定义路径
4. 支持的类型：`str`, `int`, `float`, `bool`, `list`, `dict`, `Any`
5. 自动处理必填字段（`__required__`）和可选字段（默认值）
6. 支持嵌套对象模型（`object` 类型 + 内联字段定义）

---

#### Worker config.toml 配置详解

`gen-models` 的数据来源是 Worker 的 `config.toml`。以下详细解释其完整配置结构。

##### 基础结构

```toml
[worker]
name = "example"          # Worker 名称，Gateway 用于服务发现
version = "0.1.0"

[nats]
urls = [
    "nats://localhost:4222",
    "nats://localhost:4223",
    "nats://localhost:4224"
]

[registration]
type = "register"               # 固定为 "register"
service = "example"             # 服务名，Gateway 用于 URL 路由前缀
queue_group = "calc-workers"    # 队列组，同组多实例实现负载均衡
router_prefix = "/calc"         # 路由前缀（已弃用，保留兼容）
tags = ["calculator"]           # 标签，用于服务分类
heartbeat_interval = 15         # 心跳间隔（秒），建议 10~30

items = [
    # ── 每个 handler 一条路由 ──────────────────────────
    {
        subject = "calc.add",               # NATS subject（必填）
        method = "GET",                     # HTTP 方法
        path = "/add",                      # URL 路径（Gateway 拼接后为 /api/v1/calc/add）
        summary = "Add two numbers",        # OpenAPI 摘要
        docstring = "详细说明",               # OpenAPI 描述
        params = ["a: float", "b: float"],  # 请求参数（参数名: 类型）
        ttl = 30,                           # 路由 TTL（秒），需 > heartbeat_interval
        timeout = 2.0,                      # NATS 请求超时（秒）
        response_model = {                  # 响应模型定义
            result = ["float", "__required__"],  # 必填字段（无默认值）
            operation = ["str", "add"],          # 可选字段（有默认值）
            timestamp = ["float", 0.0]
        },
        shared = false,     # ❌ 不共享（默认），--shared 不会选中
        internal = false,   # ❌ 对外公开（默认），显示在 Swagger 文档
    },
]
```

##### 字段说明

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `subject` | string | ✅ | — | NATS 主题名，handler 用 `@app.handler("calc.add")` 匹配 |
| `method` | string | ✅ | — | HTTP 方法：`GET`/`POST`/`PUT`/`DELETE` |
| `path` | string | ✅ | — | URL 路径，最终 URL: `/api/v1/{service}{path}` |
| `params` | array | ❌ | `[]` | 参数列表 `["name: type"]`，决定 Input 模型字段 |
| `ttl` | int | ❌ | 30 | 路由 TTL（秒），**必须大于 `heartbeat_interval`** |
| `timeout` | float | ❌ | 2.0 | NATS request 超时时间 |
| `response_model` | dict | ❌ | `{}` | 响应结构，决定 Output 模型 |
| `shared` | bool | ❌ | `false` | 设为 `true` 会被 `--shared` 选中 |
| `internal` | bool | ❌ | `false` | 设为 `true` 不在 Swagger 文档公开 |

##### 响应模型字段定义

`response_model` 中的每个字段使用数组格式定义：

| 格式 | 说明 |
|------|------|
| `field = ["type", "__required__"]` | **必填字段**，无默认值，生成 `field: type` |
| `field = ["type", "default_value"]` | **可选字段**，有默认值，生成 `field: type = default` |
| `field = ["object", "__required__", { ... }]` | **嵌套对象**，内部继续定义子字段 |

**支持的类型映射：**

| config.toml 类型 | Python/Pydantic 类型 | 示例 |
|-------------------|----------------------|------|
| `str` | `str` | `"hello"` |
| `int` | `int` | `42` |
| `float` | `float` | `3.14` |
| `bool` | `bool` | `true` |
| `list` | `list` | `[1, 2, 3]` |
| `object` | `dict` / 嵌套模型 | `{ "nested": ... }` |
| `any` | `Any` | 任意类型 |

##### 嵌套对象示例

```toml
response_model = {
    order_id = ["str", "__required__"],
    user = ["object", "__required__", {        # 嵌套对象
        user_id = ["str", "__required__"],
        name = ["str", "__required__"],
        balance = ["float", 0.0],
        level = ["str", "normal"]
    }],
    items = ["list", []],
    timestamp = ["float", 0.0]
}
```

这会生成：

```python
class User(BaseModel):
    """User"""
    user_id: str
    name: str
    balance: float = 0.0
    level: str = "normal"

class CalcAddOutput(BaseModel):
    """calc.add 响应结果模型"""
    order_id: str
    user: User
    items: list = []
    timestamp: float = 0.0
```

---

#### 跨 Worker 共享模型（`--shared` + `--output`）

当不同 Worker 之间需要共享数据结构时（如 `order.create` 引用 `user.query` 的响应），可以将共享模型生成到 `public/` 目录，便于其他 Worker 导入。

**步骤 1：在 config.toml 中标记共享 handler**

```toml
items = [
    {
        subject = "user.query",
        shared = true,            # 标记为共享模型
        params = ["user_id: str"],
        response_model = {
            user_id = ["str", "__required__"],
            name = ["str", "__required__"],
            balance = ["float", 0.0],
            level = ["str", "normal"]
        }
    },
    {
        subject = "notification.order_created",
        internal = true,           # 内部 handler，不对外公开
        # shared = false（默认），不会被 --shared 选中
        params = ["order_id: str"],
        response_model = {
            status = ["str", "notified"]
        }
    }
]
```

**步骤 2：生成共享模型到 public/ 目录**

```bash
chongming gen-models example --output workers/example/public/__init__.py --shared
```

**步骤 3：其他 Worker 导入使用**

```python
# 在另一个 Worker 中导入共享模型
from workers.example.public import UserQueryOutput
```

> **注意：** `shared` 默认值为 `false`，只有显式设为 `true` 的 handler 才会被 `--shared` 选中。这确保了内部 handler 的模型不会被意外暴露。

**覆盖所有文件的场景：**

生成模型后，建议检查生成的代码，确保满足业务需求。如果后续修改了 `config.toml` 或 handler 签名，需要重新生成。

---

### `chongming gateway` — 启动 Gateway

启动 API Gateway 开发或生产服务器。

```bash
# 开发模式（单进程 + 热重载）
chongming gateway

# 生产模式（Gunicorn + 多进程）
chongming gateway --production

# 自定义监听地址和端口
chongming gateway --host 127.0.0.1 --port 8080 --reload
```

**参数：**

| 参数 | 说明 |
|------|------|
| `--host` | 监听地址，默认 `0.0.0.0` |
| `--port`, `-p` | 监听端口，默认 `8000` |
| `--production` | 使用 Gunicorn 生产模式（多进程，无热重载） |
| `--reload` | 启用热重载（仅开发模式） |
| `--no-reload` | 禁用热重载 |

---

### `chongming worker` — 启动 Worker

启动一个或多个 Worker 服务，自动处理 NATS 连接、服务注册和心跳。

```bash
# 启动指定 Worker
chongming worker example

# 启动所有 Worker
chongming worker --all

# 查看可用的 Worker 列表
chongming worker --list
```

**参数：**

| 参数 | 说明 |
|------|------|
| `name` | Worker 名称（对应 `workers/` 下的子目录名） |
| `--all`, `-a` | 启动所有 Worker |
| `--list`, `-l` | 列出所有可用的 Worker |

**自动检测 Worker 类型：**
- **Python Worker** — 使用 `uv run --directory workers/<name> python main.py` 启动
- **Rust Worker** — 使用 `cargo run --manifest-path workers/<name>/Cargo.toml` 启动（自动检测 `Cargo.toml`）

---

### `chongming docker-build` — 构建 Docker 镜像

将 Worker 或 Gateway 打包为 Docker 镜像（自动检测 Python/Rust）。

```bash
# 构建 Python Worker
chongming docker-build example

# 构建 Rust Worker
chongming docker-build example_rs
```

**参数：**

| 参数 | 说明 |
|------|------|
| `name` | 服务名称（必填） |
| `--tag`, `-t` | 镜像标签，默认 `chongming/<name>:latest` |
| `--push` | 构建完成后推送到镜像仓库 |
| `--no-cache` | 构建时不使用缓存 |

---

### `chongming binary-build` — 构建二进制镜像

使用 PyInstaller 将 Python 代码编译为单文件二进制，再打包为极小 Docker 镜像。**推荐生产部署方式。**

```bash
chongming binary-build gateway --tag registry.example.com/gateway:v1.0
chongming binary-build example
```

#### 构建模式对比

| 特性 | `docker-build` | `binary-build` ✅ |
|------|---------------|-------------------|
| 基础镜像 | `python:3.12-slim` (~120MB) | `busybox:glibc` (~5MB) |
| 最终镜像 | ~200-300MB | ~20-30MB |
| 构建时间 | ~15-20s | ~60s |
| 启动速度 | 秒级 | **毫秒级** |
| 源码保护 | ❌ 包含 .py 源码 | ✅ 编译为二进制，无源码 |
| 环境依赖 | 需 pip + Python 运行时 | 无依赖 |
| 适用环境 | 开发 / CI | **生产部署** |

---

### `chongming docker` — 管理 Docker 环境

```bash
# 启动所有服务
chongming docker up

# 启动生产模式（含 Nginx 负载均衡）
chongming docker up --prod

# 查看服务状态
chongming docker ps

# 停止服务
chongming docker down
```

---

### `chongming image-export` — 导出镜像

将 Docker Compose 中使用的所有镜像导出为 tar 文件，便于离线环境部署。

```bash
chongming image-export --output ./images
```

---

### `chongming log-export` — 导出日志

从 MinIO 对象存储中按条件查询并导出 Worker 或 Gateway 的日志。

```bash
# 列出可用的服务实例
chongming log-export --list-services

# 导出指定 Worker 最近 1 小时的日志
chongming log-export --type worker --name example --since 1h

# 导出 DEBUG 级别日志到文件
chongming log-export --type worker --name example --level DEBUG --output /tmp/logs.json
```

---

## 依赖

- **Python 3.12+**
- **uv**（包管理器）
- 子命令可能依赖：
  - **Docker** — `docker-build`、`binary-build`、`docker`、`image-export`
  - **PyInstaller** — `binary-build`
  - **Cargo** — Rust Worker 相关操作
  - **MinIO** — `log-export`
