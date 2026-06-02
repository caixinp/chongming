# Rust Worker 模板

基于 Rust `chongming-worker` 框架的 Worker 脚手架模板。使用 CLI 命令 `chongming new my-worker --lang rust` 时，会从此模板复制并自动重命名。

---

## 🎯 核心概念：`config.toml` 驱动一切

**与 Python Worker 一样，Rust Worker 也完全由 `config.toml` 驱动。** 创建新 Worker 后的第一件事：**编辑 `config.toml`**，修改 Worker 名称、NATS 地址、添加你的路由定义。

`config.toml` 的格式与 Python 版**完全兼容**，区别仅在于代码层的注册方式：
- Rust 使用 **Builder 模式**（`.handle().build()`）
- Python 使用 **装饰器模式**（`@app.handler()`）

```
config.toml（Rust & Python 格式完全相同！）
    │
    ├─ [worker]         → Worker 名称、版本
    ├─ [nats]           → NATS 集群地址
    ├─ [registration]   → 服务名、队列组、心跳间隔
    │   └─ items[]      → ★ 所有 handler 的路由定义！
    └─ [logging.minio]  → 日志配置
```

---

## 业务功能

| 接口 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 加法 | GET | `/calc/add?a=10&b=20` | 两数相加 |
| 减法 | GET | `/calc/subtract?a=30&b=10` | 两数相减 |
| 乘法 | GET | `/calc/multiply?a=6&b=7` | 两数相乘 |
| 除法 | GET | `/calc/divide?a=100&b=3` | 两数相除（除数不能为 0） |

### 响应格式

```json
{
    "result": 30.0,
    "operation": "add",
    "timestamp": 1234567890.123
}
```

---

## 快速开始

### 前置条件

1. 启动 NATS 集群（参考 `docker-env/README.md`）
2. 启动 API Gateway（可选）
3. Rust 工具链 1.80+

### 启动 Worker

```bash
cd <your-worker-dir>
cargo run
```

启动后自动：
1. **读取 `config.toml` 配置**
2. 连接 NATS 集群
3. 向 Gateway 注册路由（通过 `service.registry` 主题）
4. 开始心跳保活（默认每 15 秒）

### 测试

```bash
# 加法
curl "http://localhost:8000/api/v1/calc/add?a=10&b=20"

# 减法
curl "http://localhost:8000/api/v1/calc/subtract?a=30&b=10"

# 乘法
curl "http://localhost:8000/api/v1/calc/multiply?a=6&b=7"

# 除法
curl "http://localhost:8000/api/v1/calc/divide?a=100&b=3"

# 除零错误
curl "http://localhost:8000/api/v1/calc/divide?a=1&b=0"
# → {"error": "除数不能为 0"}
```

---

## 代码结构

```
<your-worker>/
├── src/
│   └── main.rs            # ★ 业务逻辑 — 类型安全的 Rust 实现
├── config.toml            # ★★ 核心配置文件 — Worker 的"心脏"
│                           #    定义 NATS 连接、路由注册、心跳间隔、
│                           #    所有 handler 的 subject/method/path/params
├── Cargo.toml
└── README.md
```

### 核心代码 (src/main.rs)

```rust
use anyhow::Result;
use chongming_worker::prelude::*;
use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize)]
struct CalcInput {
    a: f64,
    b: f64,
}

#[derive(Debug, Serialize)]
struct CalcOutput {
    result: f64,
    operation: String,
    timestamp: f64,
}

async fn add(input: CalcInput) -> Result<CalcOutput> {
    Ok(CalcOutput {
        result: input.a + input.b,
        operation: "add".to_string(),
        timestamp: current_timestamp(),
    })
}

// ... subtract, multiply, divide 同理

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter("info")
        .init();

    let mut app = WorkerBuilder::from_config("config.toml")?  // ← 加载 config.toml
        .handle("calc.add", add)       // ← subject 必须与 config.toml items 一致
        .handle("calc.subtract", subtract)
        .handle("calc.multiply", multiply)
        .handle("calc.divide", divide)
        .build();

    app.run().await
}
```

**`WorkerBuilder::from_config("config.toml")`** 加载配置后，`.handle("calc.add", add)` 中的 `"calc.add"` 必须匹配 `config.toml` 中某条 `item` 的 `subject` 字段。

---

## config.toml（与 Python 版格式兼容）

```toml
[worker]
name = "example_rs"
version = "0.1.0"
description = "Rust calculator worker"

[nats]
urls = [
    "nats://localhost:4222",
    "nats://localhost:4223",
    "nats://localhost:4224"
]

[registration]
type = "register"
service = "example_rs"
queue_group = "calc-workers"
router_prefix = "/calc"
tags = ["calculator", "rust"]
heartbeat_interval = 15

items = [
    {
        subject = "calc.add",
        method = "GET",
        path = "/add",
        params = ["a: float", "b: float"],
        ttl = 30,
        timeout = 2.0,
        response_model = {
            result = ["float", "__required__"],
            operation = ["str", "add"],
            timestamp = ["float", 0.0]
        }
    },
    # ... subtract, multiply, divide 同理
]
```

### 参数速查表

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `subject` | string | ✅ | NATS 主题名，Rust 中通过 `.handle("calc.add", add)` 匹配 |
| `method` | string | ✅ | HTTP 方法：GET、POST、PUT、DELETE |
| `path` | string | ✅ | URL 路径，Gateway 组装为 `/api/v1/{service}{path}` |
| `params` | array | ❌ | 参数列表 `["name: type"]` |
| `ttl` | int | ❌ | 路由注册 TTL（秒），需 > `heartbeat_interval` |
| `timeout` | float | ❌ | NATS request 超时（秒），默认 2.0 |
| `response_model` | dict | ❌ | 响应结构定义 |

---

## 与 Python 版对比

| 特性 | Python Worker | Rust Worker |
|------|--------------|-------------|
| 框架 | `chongming_worker` (Python) | `chongming_worker` (Rust) |
| 构造方式 | 装饰器 `@app.handler()` | Builder 模式 `.handle().build()` |
| 配置驱动 | 加载 `config.toml` | **同样加载 `config.toml`** |
| 路由定义 | **`config.toml` items** | **同左 — 格式完全兼容** |
| 类型安全 | 运行时类型转换 | 编译期类型检查 |
| 日志 | Python logging | tracing crate |
| 异步运行时 | asyncio | tokio |
| 构建命令 | `python main.py` | `cargo run` / `cargo build` |

---

## 构建部署

```bash
# Docker 镜像
chongming docker-build <your-worker>

# 或手动构建
docker build -f docker-env/worker-rust.Dockerfile -t chongming/<your-worker>:latest .
