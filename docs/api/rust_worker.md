# Utils Worker (Rust) — chongming-worker

**Package:** `chongming_worker` (Rust)  
**Location:** `utils/rust/worker/`  
**Entry Point:** `chongming_worker::prelude`

Rust 版的 Worker 生命周期管理框架，与 Python 版 API 对齐。自动处理 NATS 连接与重连、服务注册与心跳、消息分发与参数解析、优雅关闭。

---

## `WorkerBuilder`

Ergonomic builder 模式构造 Worker 实例。

```rust
use chongming_worker::prelude::*;

let mut app = WorkerBuilder::from_config("config.toml")?;
```

### 方法

| 方法 | 说明 |
|------|------|
| `from_config(path)` | 从 TOML 配置文件创建 builder |
| `new(config)` | 从已解析的 `Config` 结构体创建 builder |
| `handle(subject, handler)` | 注册类型化 handler（自动 JSON 序列化/反序列化） |
| `handle_raw(subject, handler)` | 注册原始 handler（直接操作 `serde_json::Value`） |
| `with_nats_urls(urls)` | 覆盖配置文件中的 NATS URLs |
| `build()` | 消费 builder 返回 `Worker` 实例 |

### 类型化 Handler

```rust
use serde::{Deserialize, Serialize};

#[derive(Deserialize)]
struct CalcInput { a: f64, b: f64 }

#[derive(Serialize)]
struct CalcOutput { result: f64, operation: String, timestamp: f64 }

async fn add(input: CalcInput) -> Result<CalcOutput> {
    Ok(CalcOutput {
        result: input.a + input.b,
        operation: "add".to_string(),
        timestamp: current_timestamp(),
    })
}

let mut app = WorkerBuilder::from_config("config.toml")?
    .handle("calc.add", add)
    .build();
```

### 原始 Handler

```rust
app.handle_raw("custom.subject", |json_val| async move {
    Ok(serde_json::json!({"status": "ok"}))
});
```

---

## `Worker`

### 构造

```rust
use chongming_worker::Worker;
use std::collections::HashMap;

let worker = Worker::new(config, handler_map);
```

### 生命周期方法

| 方法 | 说明 |
|------|------|
| `start()` | 启动：连接 NATS、注册、订阅、开始心跳 |
| `run()` | 主入口：启动后等待 SIGINT/SIGTERM，自动优雅关闭 |
| `shutdown()` | 优雅关闭：取消心跳、取消订阅、注销、关闭 NATS |

---

## 核心数据结构

### `Config`

```rust
pub struct Config {
    pub worker: WorkerConfig,
    pub nats: NatsConfig,
    pub registration: RegistrationConfig,
}

pub struct WorkerConfig { pub name: String, pub version: String, pub description: String }
pub struct NatsConfig { pub urls: Vec<String> }
pub struct RegistrationConfig {
    pub msg_type: String,
    pub service: String,
    pub router_prefix: String,
    pub tags: Vec<String>,
    pub items: Vec<RouteItem>,
    pub heartbeat_interval: u64,
    pub queue_group: Option<String>,
}
pub struct RouteItem {
    pub subject: String,
    pub method: String,
    pub path: String,
    pub summary: String,
    pub docstring: String,
    pub params: Vec<String>,
    pub ttl: u64,
    pub timeout: f64,
    pub response_model: Option<Value>,
}
```

### 消息协议

```rust
pub struct RegisterMessage { pub msg_type, pub service, pub router_prefix, pub tags, pub items }
pub struct HeartbeatMessage { pub msg_type, pub service, pub subject, pub subjects, pub items, pub router_prefix, pub tags }
pub struct DeregisterMessage { pub msg_type, pub service, pub router_prefix }
```

---

## 与 Python 版差异

| 特性 | Python | Rust |
|------|--------|------|
| 构造方式 | `WorkerLifespan("config.toml")` | `WorkerBuilder::from_config("config.toml")?.build()` |
| Handler 注册 | 装饰器 `@app.handler()` | 方法链 `.handle(subject, fn)` |
| 类型安全 | 运行时类型转换 | 编译期类型检查 + 运行时 |
| 日志 | Python logging + contextvars | tracing crate |
| 异步运行时 | asyncio | tokio |
