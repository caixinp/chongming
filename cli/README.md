# Chongming CLI — 项目管理与构建工具

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

一站式项目管理命令行工具，支持项目脚手架创建、Docker 镜像构建、生产级二进制打包、本地开发服务器启动等功能。

---

## 安装

```bash
# 本地开发安装
cd cli
uv sync

# 或通过 pip 安装
pip install chongming-cli
```

安装后即可使用 `chongming` 命令。

---

## 可用命令

| 命令 | 功能 | 适用场景 |
|------|------|----------|
| `new` | 新建 Worker / Gateway 项目模板 | 项目脚手架 |
| `gateway` | 启动 API Gateway 开发服务器 | 本地开发 |
| `worker` | 启动 Worker 服务 | 本地开发 |
| `docker-build` | 构建 Docker 镜像（Python 运行时） | 开发 / CI 调试 |
| `binary-build` | 构建二进制 Docker 镜像（PyInstaller） | **生产部署** |
| `docker` | Docker Compose 环境管理 | 基础设施管理 |
| `image-export` | 导出 Docker 镜像为离线 tar 包 | 离线部署 |

---

## 命令详解

### `chongming new` — 创建新项目

快速生成 Worker 或 Gateway 的项目模板。

```bash
# 创建新 Worker 项目
chongming new worker my-service

# 创建新 Gateway 项目
chongming new gateway my-gateway
```

### `chongming gateway` — 启动 Gateway

启动 API Gateway 开发服务器（等同 `uv run serve`）。

```bash
chongming gateway --port 8000 --reload
```

### `chongming worker` — 启动 Worker

启动 Worker 服务，自动处理 NATS 连接、服务注册和心跳。

```bash
chongming worker --config workers/my-service/config.toml
```

### `chongming docker-build` — 构建 Python 运行时镜像

使用 `python:3.12-slim` 基础镜像，适合开发环境。

```bash
# 构建所有服务
chongming docker-build gateway
chongming docker-build example

# 指定标签
chongming docker-build gateway --tag registry.example.com/gateway:latest
```

### `chongming binary-build` — 构建二进制镜像（推荐生产）

使用 PyInstaller 将 Python 代码编译为单文件二进制，再打包为 `busybox:glibc` 基础镜像。

| 特性 | docker-build | binary-build ✅ |
|------|-------------|-----------------|
| 基础镜像 | python:3.12-slim (~120MB) | busybox:glibc (~5MB) |
| 最终镜像 | ~200-300MB | ~20-30MB |
| 启动速度 | 秒级 | 毫秒级 |
| 源码安全 | ❌ 包含 .py 源码 | ✅ 无源码 |
| 环境依赖 | 需 pip + Python | 无依赖 |

```bash
# 构建二进制镜像
chongming binary-build gateway
chongming binary-build example

# 推送到镜像仓库
chongming binary-build gateway --tag registry.example.com/gateway:v1.0 --push
```

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

### `chongming image-export` — 离线镜像导出

将 Docker Compose 中使用的所有镜像导出为 tar 文件，便于离线环境部署。

```bash
# 导出所有镜像
chongming image-export

# 指定输出目录
chongming image-export --output ./images
```

---

## 构建模式对比

| 维度 | `docker-build` | `binary-build` |
|------|---------------|----------------|
| 构建工具 | Docker + pip | PyInstaller + Docker |
| 基础镜像 | `python:3.12-slim` | `busybox:glibc` |
| 镜像大小 | ~200–300MB | ~20–30MB |
| 构建时间 | ~15–20s | ~60s |
| 启动速度 | 秒级 | 毫秒级 |
| 源码保护 | ❌ | ✅ |
| 适用环境 | 开发 / CI | **生产** |
| 命令 | `chongming docker-build <name>` | `chongming binary-build <name>` |

---

## 依赖

- Python 3.12+
- Hatcling（构建后端）
- 子命令可能依赖 Docker、PyInstaller、Nuitka 等外部工具
