# CLI — Chongming CLI

**Package:** `chongming_cli`  
**Location:** `cli/src/chongming_cli/`  
**Entry Point:** `chongming_cli.__main__`

一站式项目管理命令行工具，使用 `typer` 构建，支持项目脚手架创建、Docker 镜像构建、生产级二进制打包、Gateway 启动等。

---

## 命令树

```
chongming
├── new            创建新项目模板
├── gateway        启动 API Gateway
├── worker         启动 Worker
├── docker-build   构建 Docker 镜像
├── binary-build   构建二进制 Docker 镜像（推荐生产）
├── docker         Docker Compose 环境管理
├── image-export   导出 Docker 镜像
└── log-export     从 MinIO 导出日志
```

---

## 命令详解

### `new`

```python
@app.command()
def new(
    name: str = typer.Argument(..., help="Worker name"),
    lang: str = Option("python", "--lang", help="Language (python/rust)"),
    no_venv: bool = Option(False, "--no-venv", help="Skip venv creation"),
):
```

**逻辑：**
1. 创建目标目录
2. 根据 `lang` 从 `templates/` 复制对应模板
3. 重命名文件中的占位符（`example` / `example_rs` → `name` 等）
4. Python 模式下自动创建虚拟环境（除非 `--no-venv`）

**模板来源：**
- Python: `templates/python/`（来自 `workers/example`，含全部 WorkerLifespan 特性）
- Rust: `templates/rust/`（来自 `workers/example_rs`）

**示例：**
```bash
# 创建 Python worker（默认，包含全部 WorkerLifespan 特性）
chongming new myworker

# 创建 Rust worker
chongming new myworker --lang rust
```

### `gateway`

```python
@app.command()
def gateway(
    host: str = Option("0.0.0.0", "--host"),
    port: int = Option(8000, "--port", "-p"),
    production: bool = Option(False, "--production"),
    reload: Optional[bool] = Option(None, "--reload/--no-reload"),
):
```

**逻辑：**
- 开发模式：`uv run uvicorn chongming_gateway.app:app --host ... --port ... --reload`
- 生产模式：`uv run gunicorn chongming_gateway.app:app -w 4 -k uvicorn.workers.UvicornWorker -b ...`

### `worker`

```python
@app.command()
def worker(
    name: Optional[str] = typer.Argument(None, help="Worker name"),
    all: bool = Option(False, "--all", "-a"),
    list_workers: bool = Option(False, "--list", "-l"),
):
```

**自动检测 Worker 类型：**
- 存在 `Cargo.toml` → Rust Worker → `cargo run`
- 否则 → Python Worker → `uv run python main.py`

### `docker-build`

```python
@app.command()
def docker_build(
    name: str = typer.Argument(...),
    tag: Optional[str] = Option(None, "--tag", "-t"),
    dockerfile: Optional[str] = Option(None, "--dockerfile", "-f"),
    push: bool = Option(False, "--push"),
    no_cache: bool = Option(False, "--no-cache"),
    build_arg: Optional[List[str]] = Option(None, "--build-arg"),
    rust_build_mode: str = Option("release", "--rust-build-mode"),
    help_deploy: bool = Option(False, "--help-deploy"),
):
```

**自动 Dockerfile 检测：**
- 包含 `Cargo.toml` → `worker-rust.Dockerfile`
- 否则 → `worker.Dockerfile`

### `binary-build`

```python
@app.command()
def binary_build(
    name: str = typer.Argument(...),
    tag: Optional[str] = Option(None, "--tag", "-t"),
    push: bool = Option(False, "--push"),
):
```

**实现原理：** 编译 → PyInstaller 打包 → busybox 运行时镜像

### `docker`

```python
@app.command()
def docker(
    up: bool = Option(False, "--up"),
    down: bool = Option(False, "--down"),
    ps: bool = Option(False, "--ps"),
    prod: bool = Option(False, "--prod"),
):
```

### `image-export`

```python
@app.command()
def image_export(
    output: str = Option("./", "--output", "-o"),
):
```

从 Docker Compose 配置中提取所有镜像并导出为 tar 文件。

### `log-export`

```python
@app.command()
def log_export(
    ...
):
```

从 MinIO 对象存储中按条件查询并导出 Worker 或 Gateway 的日志。

**支持特性：**
- 按服务类型筛选（gateway / worker）
- 按服务实例名称筛选
- 按时间范围筛选（`--since`、`--start`、`--end`）
- 按日志级别筛选（`--level`）
- 输出为 JSON 或文本格式（`--format`）
- 列举 MinIO 中可用服务实例（`--list-services`）
- 统计日志存储使用量（`--stats`）
- 自定义 MinIO 连接配置（`--minio-endpoint`、`--bucket` 等）
- 输出到文件（`--output`）

**实现流程：**
1. 连接 MinIO（支持环境变量和命令行参数配置）
2. 遍历 `logs/{type}/{name}/{YYYY}/{MM}/{DD}/{HH}/` 路径结构
3. 自动解压 Gzip 日志文件
4. JSON 解析日志行，按筛选条件过滤
5. 按指定格式输出到 stdout 或文件

---

## 架构

```
cli/
├── pyproject.toml
├── README.md
└── src/
    └── chongming_cli/
        ├── __init__.py
        ├── __main__.py          # 入口：typer 应用 + 子命令注册
        └── commands/
            ├── __init__.py
            ├── binary_build.py  # binary-build 命令
            ├── docker_build.py  # docker-build 命令
            ├── docker.py        # docker 命令
            ├── gateway.py       # gateway 命令
            ├── image_export.py  # image-export 命令
            ├── log_export.py    # 日志导出工具
            ├── new.py           # new 命令
            └── worker.py        # worker 命令
