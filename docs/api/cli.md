# CLI — Chongming CLI

**Package:** `chongming_cli`
**Location:** `cli/src/chongming_cli/`
**Entry Point:** `chongming_cli:main`

一站式项目管理命令行工具，使用 `argparse` 构建，支持项目脚手架创建、Docker 镜像构建、生产级二进制打包、Gateway 启动、NATS 链路追踪等。

---

## 命令树

```
chongming
├── new             创建新项目模板（Python / Rust）
├── gen-models      从 config.toml 生成 Pydantic 模型
├── gateway         启动 API Gateway
├── worker          启动 Worker
├── trace           实时追踪 NATS 请求-响应链路
├── docker-build    构建 Docker 镜像
├── binary-build    构建二进制 Docker 镜像（推荐生产）
├── docker          Docker Compose 环境管理
├── image-export    导出 Docker 镜像
├── log-export      从 MinIO 导出日志
└── db              数据库迁移管理
```

---

## 命令详解

### `new`

```python
def add_new_parser(subparsers):
    parser = subparsers.add_parser("new", ...)
    parser.add_argument("name", type=str, help="Worker 名称")
    parser.add_argument("--lang", choices=["python", "rust"], default="python")
    parser.add_argument("--no-venv", action="store_true")
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

### `gen-models`

```python
def add_gen_models_parser(subparsers):
    parser = subparsers.add_parser("gen-models", ...)
    parser.add_argument("name", type=str, nargs="?", help="Worker 名称")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=str)
    parser.add_argument("--shared", action="store_true")
```

**逻辑：**
1. 读取 `config.toml` → `registration.items` 的每个 handler 配置
2. 根据 `params` 生成 Pydantic 请求模型
3. 根据 `response_model` 生成 Pydantic 响应模型
4. 支持嵌套 `object` 类型，递归生成子模型
5. `--shared` 仅生成标记为 `shared=true` 的模型

### `gateway`

```python
def add_gateway_parser(subparsers):
    parser = subparsers.add_parser("gateway", ...)
    parser.add_argument("--host", type=str, default=None)
    parser.add_argument("--port", "-p", type=int, default=None)
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--no-reload", action="store_true")
```

**逻辑：**
- 开发模式：`uv run uvicorn chongming_gateway.app:app --host ... --port ... --reload`
- 生产模式：`uv run gunicorn chongming_gateway.app:app -w 4 -k uvicorn.workers.UvicornWorker -b ...`

### `worker`

```python
def add_worker_parser(subparsers):
    parser = subparsers.add_parser("worker", ...)
    parser.add_argument("name", type=str, nargs="?")
    parser.add_argument("--all", "-a", action="store_true")
    parser.add_argument("--list", "-l", action="store_true")
```

**自动检测 Worker 类型：**
- 存在 `Cargo.toml` → Rust Worker → `cargo run`
- 否则 → Python Worker → `uv run python main.py`

### `trace`

```python
def add_trace_parser(subparsers):
    parser = subparsers.add_parser("trace", ...)
    parser.add_argument("subject", type=str, help="要追踪的业务主题")
    parser.add_argument("--follow", "-f", action="store_true")
    parser.add_argument("--count", "-n", type=int, default=None)
    parser.add_argument("--since", type=str, default=None)
    parser.add_argument("--js", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--no-request-payload", action="store_true")
    parser.add_argument("--no-response-payload", action="store_true")
    # NATS 连接参数：--host, --port, --user, --password, --token,
    #   --creds, --nkey, --tls, --tls-cert, --tls-key, --tls-ca
    # JetStream 参数：--stream, --js-domain
```

**功能：** 实时或历史追踪 NATS 请求-响应链路，自动关联 `request_id` 和耗时。

**工作流程：**
1. 连接 NATS（支持 TLS、凭证、NKEY 等认证方式）
2. 订阅业务 subject（如 `user.register`）
3. 捕获请求消息 → 提取 `request_id`（从 headers）和 `reply` 主题
4. 动态订阅 reply 主题（每个请求独立订阅，用完即取消）
5. 收到响应 → 计算耗时 → 格式化输出
6. 5 秒超时 → 打印超时提示

**Core NATS 模式（实时）：**
```python
async def _core_trace(nc, args, max_count, shutdown_event, counter):
    """实时监听业务 subject，动态订阅 reply"""
    pending = {}  # reply_subject -> {"request_id", "timer_task"}

    async def on_request(msg):
        # 提取 request_id 和 reply subject
        # 打印请求信息
        # 订阅 reply subject，设置超时任务
        # 收到响应 → 打印响应信息
        # 超时 → 打印超时提示
        ...

    await nc.subscribe(args.subject, cb=on_request)
    await shutdown_event.wait()
```

**JetStream 模式（历史回放）：**
```python
async def _js_trace(nc, args, since_delta, max_count, shutdown_event, counter):
    """JetStream pull subscribe 回放历史消息"""
    psub = await js.pull_subscribe(
        args.subject,
        stream=stream,
        config=ConsumerConfig(
            deliver_policy=DeliverPolicy.BY_START_TIME,
            opt_start_time=start_time,
        ),
    )
    # 拉取历史消息 → 打印 → 可选切换到实时监听
```

**特性：**
- **request_id 关联**：从 NATS headers 提取，自动关联请求与响应
- **自动脱敏**：`password`、`token`、`secret` 等字段自动替换为 `***`
- **动态 reply 订阅**：每个请求独立订阅其 reply 主题，避免通配符订阅 `_INBOX.>` 的开销
- **超时处理**：5 秒未收到响应打印超时提示
- **并发安全**：通过 dict 追踪在途请求，每个请求独立管理状态
- **资源清理**：Ctrl+C 或达到 count 时关闭所有订阅和 NATS 连接

### `docker-build`

```python
def add_docker_build_parser(subparsers):
    parser = subparsers.add_parser("docker-build", ...)
    parser.add_argument("name", type=str)
    parser.add_argument("--tag", "-t", type=str, default=None)
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--dockerfile", "-f", type=str, default=None)
```

**自动 Dockerfile 检测：**
- 包含 `Cargo.toml` → `worker-rust.Dockerfile`
- 否则 → `worker.Dockerfile`

### `binary-build`

```python
def add_binary_build_parser(subparsers):
    parser = subparsers.add_parser("binary-build", ...)
    parser.add_argument("name", type=str)
    parser.add_argument("--tag", "-t", type=str, default=None)
    parser.add_argument("--push", action="store_true")
```

**实现原理：** 编译 → PyInstaller 打包 → busybox 运行时镜像

### `docker`

```python
def add_docker_parser(subparsers):
    parser = subparsers.add_parser("docker", ...)
    parser.add_argument("--up", action="store_true")
    parser.add_argument("--down", action="store_true")
    parser.add_argument("--ps", action="store_true")
    parser.add_argument("--prod", action="store_true")
```

### `image-export`

```python
def add_image_export_parser(subparsers):
    parser = subparsers.add_parser("image-export", ...)
    parser.add_argument("--output", "-o", type=str, default="./")
```

从 Docker Compose 配置中提取所有镜像并导出为 tar 文件。

### `log-export`

```python
def add_log_export_parser(subparsers):
    parser = subparsers.add_parser("log-export", ...)
    # 筛选条件：--type (gateway/worker), --name, --level
    # 时间范围：--since, --start, --end
    # 输出选项：--format (json/text), --show-meta, --output
    # MinIO 连接：--minio-endpoint, --minio-access-key,
    #   --minio-secret-key, --minio-secure, --bucket
    # 特殊模式：--list-services, --stats
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

### `db`

```python
def add_db_parser(subparsers):
    parser = subparsers.add_parser("db", ...)
    sub = parser.add_subparsers(dest="db_command")
    # current, history, migrate, upgrade, downgrade, stamp 子命令
```

基于 Alembic 的数据库迁移管理。

---

## 架构

```
cli/
├── pyproject.toml
├── README.md
└── src/
    └── chongming_cli/
        ├── __init__.py          # 入口：argparse 应用 + 子命令注册
        └── commands/
            ├── __init__.py
            ├── new.py            # new 命令
            ├── gen_models.py     # gen-models 命令
            ├── gateway.py        # gateway 命令
            ├── worker.py         # worker 命令
            ├── trace.py          # ★ trace 命令（NATS 链路追踪）
            ├── docker_build.py   # docker-build 命令
            ├── binary_build.py   # binary-build 命令
            ├── docker.py         # docker 命令
            ├── image_export.py   # image-export 命令
            ├── log_export.py     # log-export 命令
            └── migrate.py        # db 命令
```

### 命令注册模式

每个命令模块提供两个函数：

```python
def add_<command>_parser(subparsers):
    """注册子命令的参数解析器"""
    parser = subparsers.add_parser("<command>", ...)
    # 添加参数 ...

def handle_<command>(args):
    """处理命令逻辑"""
    ...
```

在 `__init__.py` 中统一注册和路由：

```python
# 注册解析器
add_trace_parser(subparsers)

# 路由命令
if args.command == "trace":
    handle_trace(args)