//! NATS message protocol types for service registration, heartbeat, and
//! deregistration.  Compatible with the Python version's message format.

use serde::{Deserialize, Serialize};

/// Registration message sent on startup and reconnection.
/// Published to `service.registry` subject.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RegisterMessage {
    #[serde(rename = "type")]
    pub msg_type: String,
    pub service: String,
    pub router_prefix: String,
    pub tags: Vec<String>,
    pub items: Vec<crate::config::RouteItem>,
}

/// Heartbeat message sent periodically to keep routes alive.
///
/// Two modes:
/// - Single heartbeat: `subject` is set, `subjects`/`items` are `None`
/// - Batch heartbeat: `subjects` and/or `items` are set for bulk renewal
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HeartbeatMessage {
    #[serde(rename = "type")]
    pub msg_type: String,
    pub service: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub subject: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub subjects: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub items: Option<Vec<crate::config::RouteItem>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub router_prefix: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tags: Option<Vec<String>>,
}

/// Deregistration message sent on graceful shutdown.
/// Published to `service.registry` subject.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeregisterMessage {
    #[serde(rename = "type")]
    pub msg_type: String,
    pub service: String,
    pub router_prefix: String,
}
