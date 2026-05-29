//! Example_rs Rust Worker using the `chongming-worker` lifespan framework.
//!
//! This demonstrates how to use the [`chongming_worker::WorkerBuilder`] to
//! quickly create a NATS-based worker with:
//! - Configuration-driven setup (config.toml)
//! - Automatic service registration, heartbeat, and deregistration
//! - Queue-group based load-balanced subscriptions
//! - Graceful shutdown on SIGINT / SIGTERM
//!
//! Compare with the Python version in `workers/example/main.py`.

use anyhow::Result;
use chongming_worker::prelude::*;
use serde::{Deserialize, Serialize};

// ---------------------------------------------------------------------------
// Business logic types
// ---------------------------------------------------------------------------

/// Input for all calc operations.
#[derive(Debug, Deserialize)]
struct CalcInput {
    a: f64,
    b: f64,
}

/// Output for all calc operations.
#[derive(Debug, Serialize)]
struct CalcOutput {
    result: f64,
    operation: String,
    timestamp: f64,
}

// ---------------------------------------------------------------------------
// Handler functions
// ---------------------------------------------------------------------------

async fn add(input: CalcInput) -> Result<CalcOutput> {
    Ok(CalcOutput {
        result: input.a + input.b,
        operation: "add".to_string(),
        timestamp: current_timestamp(),
    })
}

async fn subtract(input: CalcInput) -> Result<CalcOutput> {
    Ok(CalcOutput {
        result: input.a - input.b,
        operation: "subtract".to_string(),
        timestamp: current_timestamp(),
    })
}

async fn multiply(input: CalcInput) -> Result<CalcOutput> {
    Ok(CalcOutput {
        result: input.a * input.b,
        operation: "multiply".to_string(),
        timestamp: current_timestamp(),
    })
}

async fn divide(input: CalcInput) -> Result<CalcOutput> {
    if input.b == 0.0 {
        anyhow::bail!("division by zero");
    }
    Ok(CalcOutput {
        result: input.a / input.b,
        operation: "divide".to_string(),
        timestamp: current_timestamp(),
    })
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter("info")
        .init();

    let config_path = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "config.toml".to_string());

    let mut app = WorkerBuilder::from_config(&config_path)?
        .handle("calc.add", add)
        .handle("calc.subtract", subtract)
        .handle("calc.multiply", multiply)
        .handle("calc.divide", divide)
        .build();

    app.run().await
}
