# Chongming CLI — 项目管理与构建工具

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

一站式项目管理命令行工具，支持项目脚手架创建、Docker 镜像构建、生产级二进制打包、本地开发服务器启动等功能，覆盖微服务全生命周期。

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
- **Python**：从 `workers/example` 复制模板，自动重命名配置文件和 `main.py` 中的占位内容
- **Rust**：从 `workers/example_rs` 复制模板，自动重命名 `Cargo.toml` 和 `main.rs` 中的占位内容

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

# 指定标签并推送
chongming docker-build example --tag registry.example.com/example:v1.0 --push

# 查看部署指南
chongming docker-build example --help-deploy
```

**参数：**

| 参数 | 说明 |
|------|------|
| `name` | 服务名称（必填） |
| `--tag`, `-t` | 镜像标签，默认 `chongming/<name>:latest` |
| `--dockerfile`, `-f` | Dockerfile 路径（自动检测） |
| `--push` | 构建完成后推送到镜像仓库 |
| `--no-cache` | 构建时不使用缓存 |
| `--build-arg` | 构建参数，可多次使用（如 `--build-arg KEY=VALUE`） |
| `--rust-build-mode` | Rust 编译模式：`release`（默认）或 `debug` |
| `--help-deploy` | 打印生产环境部署指南 |

**自动 Dockerfile 检测：**
- 包含 `Cargo.toml` → `worker-rust.Dockerfile`
- 否则 → `worker.Dockerfile`

---

### `chongming binary-build` — 构建二进制镜像

使用 PyInstaller 将 Python 代码编译为单文件二进制，再打包为极小 Docker 镜像。**推荐生产部署方式。**

```bash
# 构建二进制镜像
chongming binary-build gateway
chongming binary-build example

# 推送到镜像仓库
chongming binary-build gateway --tag registry.example.com/gateway:v1.0 --push
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

管理 Docker Compose 基础设施。

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
# 导出所有镜像
chongming image-export

# 指定输出目录
chongming image-export --output ./images
```

---

### `chongming log-export` — 导出日志

从 MinIO 对象存储中按条件查询并导出 Worker 或 Gateway 的日志，支持按服务类型、名称、时间范围和日志级别筛选。

```bash
# 列出 MinIO 中所有可用的服务实例
chongming log-export --list-services

# 导出所有 Gateway 日志
chongming log-export --type gateway

# 导出指定 Worker 最近 1 小时的日志
chongming log-export --type worker --name example --since 1h

# 导出指定时间范围内的日志
chongming log-export --type gateway --name api-gateway-1 \
    --start "2026-05-28T00:00:00Z" --end "2026-05-29T00:00:00Z"

# 导出 DEBUG 级别日志，JSON 格式
chongming log-export --type worker --name example --level DEBUG --format json

# 保存到文件
chongming log-export --type worker --name example --since 2h \
    --output /tmp/example-logs.json

# 查看日志存储统计
chongming log-export --stats
```

**参数：**

| 参数 | 说明 |
|------|------|
| `--type` | 服务类型：`gateway` 或 `worker` |
| `--name` | 服务实例名称（如 `api-gateway-1`、`example-worker`） |
| `--level` | 日志级别过滤（DEBUG/INFO/WARNING/ERROR/CRITICAL） |
| `--since` | 相对时间范围（如 `1h`、`30m`、`7d`） |
| `--start` | 起始时间（ISO 格式，如 `2026-05-28T00:00:00Z`） |
| `--end` | 结束时间（ISO 格式） |
| `--format` | 输出格式：`text`（默认）或 `json` |
| `--show-meta` | 显示元数据字段（logger、module、line 等） |
| `--output`, `-o` | 输出到文件（默认输出到 stdout） |
| `--list-services` | 列出 MinIO 中所有可用的服务实例 |
| `--stats` | 显示 MinIO 日志存储统计信息 |
| `--minio-endpoint` | MinIO 地址（默认 `localhost:9000`） |
| `--minio-access-key` | MinIO 访问密钥（默认 `minioadmin`） |
| `--minio-secret-key` | MinIO 密钥 |
| `--bucket` | 存储桶名称（默认 `chongming-logs`） |

**MinIO 日志路径结构：**

```
logs/{service_type}/{service_name}/{YYYY}/{MM}/{DD}/{HH}/{uuid}.log[.gz]
例如: logs/worker/example-worker/2026/05/28/14/abc123.log.gz
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
