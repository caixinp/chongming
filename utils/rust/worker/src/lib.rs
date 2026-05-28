//! # Chongming Worker Lifespan Framework (Rust)
//!
//! 自动处理 Worker 生命周期管理，包括：
//! - NATS 连接与重连
//! - 服务注册与心跳
//! - 消息分发与参数解析
//! - 优雅关闭
//!
//! 开发者只需专注于业务逻辑函数的实现。
//!
//! ## 用法
//!
//! ```ignore
//! use chongming_worker::prelude::*;
//! use serde::{Deserialize, Serialize};
//!
//! #[derive(Deserialize)]
//! struct CalcInput { a: f64, b: f64 }
//!
//! #[derive(Serialize)]
//! struct CalcOutput { result: f64, operation: String, timestamp: f64 }
//!
//! #[tokio::main]
//! async fn main() -> Result<()> {
//!     let mut app = WorkerBuilder::from_config("config.toml")?;
//!
//!     app.handle("calc.add", |input: CalcInput| async move {
//!         Ok(CalcOutput {
//!             result: input.a + input.b,
//!             operation: "add".to_string(),
//!             timestamp: current_timestamp(),
//!         })
//!     });
//!
//!     app.run().await
//! }
//! ```

mod config;
mod protocol;
mod worker;

pub use config::*;
pub use protocol::*;
pub use worker::*;

/// 常用类型的便利重导出
pub mod prelude {
    pub use crate::config::{
        Config, NatsConfig, RegistrationConfig, RouteItem, WorkerConfig,
    };
    pub use crate::protocol::{
        DeregisterMessage, HeartbeatMessage, RegisterMessage,
    };
    pub use crate::worker::{current_timestamp, Worker, WorkerBuilder};
    pub use anyhow::Result;
}
