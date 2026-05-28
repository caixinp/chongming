//! Configuration structures for Chongming Worker.
//!
//! Corresponds to `config.toml` file structure, compatible with the Python
//! version's configuration format.

use serde::{Deserialize, Serialize};

/// Top-level configuration.
#[derive(Debug, Clone, Deserialize)]
pub struct Config {
    pub worker: WorkerConfig,
    pub nats: NatsConfig,
    pub registration: RegistrationConfig,
}

/// Worker metadata.
#[derive(Debug, Clone, Deserialize)]
pub struct WorkerConfig {
    pub name: String,
    pub version: String,
    pub description: String,
}

/// NATS cluster connection settings.
#[derive(Debug, Clone, Deserialize)]
pub struct NatsConfig {
    pub urls: Vec<String>,
}

/// Service registration and routing configuration.
#[derive(Debug, Clone, Deserialize)]
pub struct RegistrationConfig {
    #[serde(rename = "type")]
    pub reg_type: String,
    pub service: String,
    pub queue_group: Option<String>,
    pub router_prefix: String,
    pub tags: Vec<String>,
    pub heartbeat_interval: u64,
    pub items: Vec<RouteItem>,
}

/// A single route/subject registration item.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RouteItem {
    pub subject: String,
    pub method: String,
    pub path: String,
    pub summary: String,
    pub docstring: String,
    pub params: Vec<String>,
    pub ttl: u64,
    pub timeout: f64,
    pub response_model: Option<serde_json::Value>,
}
