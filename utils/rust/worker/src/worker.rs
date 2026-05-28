//! Core Worker lifecycle manager.
//!
//! Provides [`WorkerBuilder`] for ergonomic construction and [`Worker`] for
//! runtime lifecycle management.  Modeled after the Python
//! `worker_lifespan.py` API.

use std::collections::HashMap;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use anyhow::Result;
use async_nats::{Client, Message, Subscriber};
use futures::StreamExt;
use tokio::sync::{RwLock, watch};
use tokio::time;
use tracing::{debug, error, info, warn};

use crate::config::Config;
use crate::protocol::{DeregisterMessage, HeartbeatMessage, RegisterMessage};

// ---------------------------------------------------------------------------
// Type aliases
// ---------------------------------------------------------------------------

/// A boxed, pinned, Send future.
pub type BoxFuture<T> = Pin<Box<dyn Future<Output = T> + Send>>;

/// A handler function that receives a deserialized JSON value and returns a
/// JSON-serializable value.
///
/// Wrapped in `Arc` so that the handler map can be cheaply cloned for
/// sharing across dispatch tasks.
/// The inner `BoxFuture` must be `Send` so it can be spawned on Tokio.
pub type RawHandler =
    Arc<dyn Fn(serde_json::Value) -> BoxFuture<Result<serde_json::Value>> + Send + Sync>;

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/// How many heartbeat cycles before we send a batch heartbeat that includes
/// full route metadata (equivalent to `reregister_cycles = 3` in Python).
const REREGISTER_CYCLES: u64 = 3;

// ---------------------------------------------------------------------------
// WorkerBuilder
// ---------------------------------------------------------------------------

/// Ergonomic builder for constructing and configuring a [`Worker`].
///
/// # Example
///
/// ```ignore
/// use chongming_worker::prelude::*;
/// use serde::{Serialize, Deserialize};
///
/// #[derive(Deserialize)]
/// struct AddInput { a: f64, b: f64 }
///
/// #[derive(Serialize)]
/// struct CalcOut { result: f64, operation: String, timestamp: f64 }
///
/// #[tokio::main]
/// async fn main() -> Result<()> {
///     let mut app = WorkerBuilder::from_config("config.toml")?
///         .handle("calc.add", |input: AddInput| async move {
///             Ok(CalcOut {
///                 result: input.a + input.b,
///                 operation: "add".into(),
///                 timestamp: current_timestamp(),
///             })
///         })
///         .build();
///
///     app.run().await
/// }
/// ```
pub struct WorkerBuilder {
    config: Config,
    handlers: Vec<(String, RawHandler)>,
}

impl WorkerBuilder {
    /// Load configuration from a TOML file.
    pub fn from_config(path: &str) -> Result<Self> {
        let content = std::fs::read_to_string(path)?;
        let config: Config = toml::from_str(&content)?;
        Ok(Self {
            config,
            handlers: Vec::new(),
        })
    }

    /// Create a builder from an already-parsed [`Config`].
    pub fn new(config: Config) -> Self {
        Self {
            config,
            handlers: Vec::new(),
        }
    }

    /// Set NATS URLs (overrides config file values).
    pub fn with_nats_urls(mut self, urls: Vec<String>) -> Self {
        self.config.nats.urls = urls;
        self
    }

    /// Register a typed handler function.
    ///
    /// The handler receives a deserialized `T` and returns a `R`.
    /// Both types must implement the appropriate serde traits.
    ///
    /// Internally this wraps the user's handler in a closure that performs
    /// JSON deserialization / serialization.
    pub fn handle<T, R, F, Fut>(mut self, subject: &str, handler: F) -> Self
    where
        T: serde::de::DeserializeOwned + Send + 'static,
        R: serde::Serialize + Send + 'static,
        F: Fn(T) -> Fut + Send + Sync + 'static,
        Fut: Future<Output = Result<R>> + Send + 'static,
    {
        let subject = subject.to_string();
        let wrapped: RawHandler = Arc::new(move |json_val| {
            let input: T = match serde_json::from_value(json_val) {
                Ok(v) => v,
                Err(e) => {
                    return Box::pin(async move {
                        Err(anyhow::anyhow!("Failed to deserialize handler input: {}", e))
                    });
                }
            };
            let fut = handler(input);
            Box::pin(async move {
                let output = fut.await?;
                let json_out = serde_json::to_value(&output)
                    .map_err(|e| anyhow::anyhow!("Failed to serialize handler output: {}", e))?;
                Ok(json_out)
            })
        });
        self.handlers.push((subject, wrapped));
        self
    }

    /// Register a raw handler that works directly with `serde_json::Value`.
    /// Useful when you need full control over (de)serialization.
    pub fn handle_raw<F, Fut>(mut self, subject: &str, handler: F) -> Self
    where
        F: Fn(serde_json::Value) -> Fut + Send + Sync + 'static,
        Fut: Future<Output = Result<serde_json::Value>> + Send + 'static,
    {
        let subject = subject.to_string();
        let wrapped: RawHandler = Arc::new(move |val| Box::pin(handler(val)));
        self.handlers.push((subject, wrapped));
        self
    }

    /// Consume the builder and produce a [`Worker`].
    pub fn build(self) -> Worker {
        let mut handler_map: HashMap<String, RawHandler> = HashMap::new();
        for (subject, handler) in self.handlers {
            handler_map.insert(subject, handler);
        }
        Worker::new(self.config, handler_map)
    }
}

// ---------------------------------------------------------------------------
// Worker
// ---------------------------------------------------------------------------

/// The core worker runtime that manages NATS connections, registrations,
/// heartbeats, message dispatch, and graceful shutdown.
///
/// You normally construct one via [`WorkerBuilder`].
pub struct Worker {
    config: Config,
    client: Option<Client>,
    handlers: HashMap<String, RawHandler>,
    running: Arc<RwLock<bool>>,
    shutdown_tx: Option<watch::Sender<bool>>,
    shutdown_rx: watch::Receiver<bool>,
    heartbeat_task: Option<tokio::task::JoinHandle<()>>,
    dispatch_tasks: Vec<tokio::task::JoinHandle<()>>,
}

impl Worker {
    /// Create a new Worker from a parsed config and handler map.
    pub fn new(config: Config, handlers: HashMap<String, RawHandler>) -> Self {
        let (shutdown_tx, shutdown_rx) = watch::channel(false);

        // Log warning for handlers without config items
        for subject in handlers.keys() {
            let has_config = config.registration.items.iter().any(|i| &i.subject == subject);
            if !has_config {
                warn!(
                    "Handler registered for subject '{}' but no matching config item found",
                    subject
                );
            }
        }

        // Validate TTL configuration (same logic as Python version)
        Self::validate_ttl_config(&config);

        Self {
            config,
            client: None,
            handlers,
            running: Arc::new(RwLock::new(true)),
            shutdown_tx: Some(shutdown_tx),
            shutdown_rx,
            heartbeat_task: None,
            dispatch_tasks: Vec::new(),
        }
    }

    /// Validate that TTL > heartbeat_interval, with warnings for low TTL.
    fn validate_ttl_config(config: &Config) {
        let interval = config.registration.heartbeat_interval;
        for item in &config.registration.items {
            if item.ttl <= interval {
                panic!(
                    "Item '{}' has ttl={}s, but heartbeat_interval={}s. \
                     TTL must be greater than heartbeat_interval. \
                     Recommended: ttl >= {}s",
                    item.subject,
                    item.ttl,
                    interval,
                    interval * 3,
                );
            }
            if item.ttl < interval * 3 {
                warn!(
                    "'{}' ttl={}s is low (heartbeat_interval={}s). \
                     A single missed heartbeat may cause route expiration. \
                     Recommended: ttl >= {}s",
                    item.subject,
                    item.ttl,
                    interval,
                    interval * 3,
                );
            }
        }
    }

    // ----------------------------------------------------------------
    // Public lifecycle
    // ----------------------------------------------------------------

    /// Start the worker: connect to NATS, register, subscribe, begin heartbeat.
    pub async fn start(&mut self) -> Result<()> {
        info!("Starting worker '{}'...", self.config.worker.name);

        // 1. Connect to NATS
        self.connect_nats().await?;

        // 2. Register with gateway
        self.register().await?;

        // 3. Subscribe to all subjects
        self.subscribe_all().await?;

        // 4. Begin heartbeat loop
        self.start_heartbeat();

        info!(
            "Worker '{}' is running.  Subjects: {:?}",
            self.config.worker.name,
            self.config
                .registration
                .items
                .iter()
                .map(|i| &i.subject)
                .collect::<Vec<_>>(),
        );

        Ok(())
    }

    /// Run the worker until a shutdown signal is received.
    ///
    /// This is the main entry point.  It starts the worker, then waits for
    /// SIGINT / SIGTERM before performing graceful shutdown.
    pub async fn run(&mut self) -> Result<()> {
        self.start().await?;

        // Wait for shutdown signal
        let mut rx = self.shutdown_rx.clone();
        tokio::select! {
            _ = tokio::signal::ctrl_c() => {
                info!("Received SIGINT");
            }
            _ = rx.changed() => {
                // shutdown requested internally
            }
        }

        self.shutdown().await?;
        Ok(())
    }

    /// Gracefully shut down the worker: cancel heartbeat, unsubscribe,
    /// deregister, drain NATS.
    pub async fn shutdown(&mut self) -> Result<()> {
        info!("Shutting down...");

        // Signal shutdown
        if let Some(tx) = self.shutdown_tx.take() {
            let _ = tx.send(true);
        }

        // Stop running flag
        {
            let mut running = self.running.write().await;
            *running = false;
        }

        // Cancel heartbeat
        if let Some(task) = self.heartbeat_task.take() {
            task.abort();
        }

        // Cancel dispatch tasks
        for task in self.dispatch_tasks.drain(..) {
            task.abort();
        }

        // Deregister
        if let Some(client) = &self.client {
            self.deregister(client).await.ok();
        }

        // Drain NATS connection
        if let Some(client) = &self.client {
            if let Err(e) = client.drain().await {
                error!("Failed to drain NATS: {}", e);
            }
        }

        info!("Shutdown complete");
        Ok(())
    }

    // ----------------------------------------------------------------
    // Internal helpers
    // ----------------------------------------------------------------

    /// Connect to the NATS cluster.
    async fn connect_nats(&mut self) -> Result<()> {
        let urls = self.config.nats.urls.clone();
        let url_str = urls
            .first()
            .cloned()
            .ok_or_else(|| anyhow::anyhow!("No NATS URLs configured"))?;
        info!("Connecting to NATS: {}", url_str);

        let client = async_nats::ConnectOptions::new()
            .retry_on_initial_connect()
            .connect(&url_str)
            .await?;

        info!("Connected to NATS");
        self.client = Some(client);
        Ok(())
    }

    /// Send registration message to gateway.
    async fn register(&self) -> Result<()> {
        let client = self.client.as_ref().expect("NATS client not connected");
        let msg = RegisterMessage {
            msg_type: "register".to_string(),
            service: self.config.registration.service.clone(),
            router_prefix: self.config.registration.router_prefix.clone(),
            tags: self.config.registration.tags.clone(),
            items: self.config.registration.items.clone(),
        };
        let payload = serde_json::to_vec(&msg)?;
        client.publish("service.registry", payload.into()).await?;
        info!("Registered service: {}", self.config.registration.service);
        Ok(())
    }

    /// Send deregistration message on shutdown.
    async fn deregister(&self, client: &Client) -> Result<()> {
        let msg = DeregisterMessage {
            msg_type: "deregister".to_string(),
            service: self.config.registration.service.clone(),
            router_prefix: self.config.registration.router_prefix.clone(),
        };
        let payload = serde_json::to_vec(&msg)?;
        client.publish("service.registry", payload.into()).await?;
        info!("Deregistered from gateway");
        Ok(())
    }

    /// Subscribe to all configured subjects using queue groups.
    async fn subscribe_all(&mut self) -> Result<()> {
        let client = self.client.as_ref().expect("NATS client not connected");
        let queue_group = self
            .config
            .registration
            .queue_group
            .clone()
            .unwrap_or_else(|| self.config.registration.service.clone());

        // Build a set of subjects: from config items + from registered handlers
        let mut subjects: Vec<String> = Vec::new();
        for item in &self.config.registration.items {
            if !subjects.contains(&item.subject) {
                subjects.push(item.subject.clone());
            }
        }
        for subject in self.handlers.keys() {
            if !subjects.contains(subject) {
                subjects.push(subject.clone());
            }
        }

        if subjects.is_empty() {
            warn!("No subjects configured or handlers registered");
            return Ok(());
        }

        let handlers = Arc::new(self.handlers.clone());
        let running = self.running.clone();

        for subject in &subjects {
            let sub_handlers = handlers.clone();
            let sub_client = client.clone();
            let sub_name = subject.clone();

            // Subscribe using queue group for load balancing
            let subscriber = client
                .queue_subscribe(subject.clone(), queue_group.clone())
                .await?;

            info!(
                "Subscribed to '{}' (queue_group={})",
                subject, queue_group
            );

            // Spawn dispatch loop for this subscriber
            let task_running = running.clone();
            let task = tokio::spawn(async move {
                Self::dispatch_loop(subscriber, sub_client, sub_handlers, sub_name, task_running).await;
            });
            self.dispatch_tasks.push(task);
        }

        Ok(())
    }

    /// Dispatch loop: process incoming messages for a single subscription.
    async fn dispatch_loop(
        mut subscriber: Subscriber,
        client: Client,
        handlers: Arc<HashMap<String, RawHandler>>,
        subject_name: String,
        running: Arc<RwLock<bool>>,
    ) {
        debug!("Dispatch loop started for '{}'", subject_name);
        while let Some(msg) = subscriber.next().await {
            // Check if we're still running
            {
                let is_running = *running.read().await;
                if !is_running {
                    break;
                }
            }

            let client = client.clone();
            let handlers = handlers.clone();
            let subject = subject_name.clone();

            tokio::spawn(async move {
                if let Err(e) = Self::handle_message(client, msg, handlers, &subject).await {
                    error!("Error handling message on '{}': {}", subject, e);
                }
            });
        }
        debug!("Dispatch loop ended for '{}'", subject_name);
    }

    /// Process a single NATS message.
    async fn handle_message(
        client: Client,
        msg: Message,
        handlers: Arc<HashMap<String, RawHandler>>,
        subject: &str,
    ) -> Result<()> {
        // Extract request_id from headers for distributed tracing (matching Python version)
        let request_id = msg
            .headers
            .as_ref()
            .and_then(|h| h.get("request_id"))
            .cloned();

        // Parse JSON payload
        let payload: serde_json::Value = match serde_json::from_slice(&msg.payload) {
            Ok(v) => v,
            Err(e) => {
                let err_msg = serde_json::json!({"error": format!("Invalid JSON: {}", e)});
                if let Some(reply) = &msg.reply {
                    client
                        .publish(reply.clone(), serde_json::to_vec(&err_msg)?.into())
                        .await?;
                }
                return Ok(());
            }
        };

        // Find handler
        let handler = match handlers.get(subject) {
            Some(h) => h,
            None => {
                warn!("No handler for subject: {}", subject);
                let err_msg = serde_json::json!({"error": format!("handler not found: {}", subject)});
                if let Some(reply) = &msg.reply {
                    client
                        .publish(reply.clone(), serde_json::to_vec(&err_msg)?.into())
                        .await?;
                }
                return Ok(());
            }
        };

        // Call handler
        let result = match handler(payload).await {
            Ok(val) => val,
            Err(e) => {
                error!("Handler for '{}' failed: {}", subject, e);
                serde_json::json!({"error": format!("Handler error: {}", e)})
            }
        };

        // Respond with optional request_id header
        if let Some(reply) = &msg.reply {
            let bytes = serde_json::to_vec(&result)?;
            client.publish(reply.clone(), bytes.into()).await?;
            debug!("Responded to '{}'", subject);
        }

        if let Some(rid) = request_id {
            debug!("Handled '{}' [request_id={}]", subject, rid);
        }

        Ok(())
    }

    /// Start the periodic heartbeat task.
    fn start_heartbeat(&mut self) {
        let config = self.config.clone();
        let client = self.client.clone().expect("NATS client not connected");
        let running = self.running.clone();

        let task = tokio::spawn(async move {
            Self::heartbeat_loop(client, config, running).await;
        });

        self.heartbeat_task = Some(task);
    }

    /// Heartbeat loop: periodically sends heartbeats to the gateway.
    ///
    /// Mirrors the Python implementation:
    /// - Most cycles: send individual heartbeats per subject
    /// - Every `REREGISTER_CYCLES` cycles: send a batch heartbeat with full metadata
    async fn heartbeat_loop(client: Client, config: Config, running: Arc<RwLock<bool>>) {
        let interval_secs = config.registration.heartbeat_interval;
        let mut interval = time::interval(Duration::from_secs(interval_secs));
        let mut count: u64 = 0;

        let items = config.registration.items.clone();
        let service = config.registration.service.clone();
        let router_prefix = config.registration.router_prefix.clone();
        let tags = config.registration.tags.clone();

        loop {
            interval.tick().await;

            // Check running flag
            {
                let is_running = *running.read().await;
                if !is_running {
                    break;
                }
            }

            count += 1;

            if count % REREGISTER_CYCLES == 0 {
                // Batch heartbeat (renews all routes with full metadata)
                // Equivalent to Python's: heartbeat_batch with subjects and items
                let batch_msg = HeartbeatMessage {
                    msg_type: "heartbeat".to_string(),
                    service: service.clone(),
                    subject: None,
                    subjects: Some(items.iter().map(|i| i.subject.clone()).collect()),
                    items: Some(items.clone()),
                    router_prefix: Some(router_prefix.clone()),
                    tags: Some(tags.clone()),
                };
                let payload = match serde_json::to_vec(&batch_msg) {
                    Ok(p) => p,
                    Err(e) => {
                        error!("Failed to serialize batch heartbeat: {}", e);
                        continue;
                    }
                };
                match client.publish("service.registry", payload.into()).await {
                    Ok(_) => debug!("Batch heartbeat sent"),
                    Err(e) => error!("Batch heartbeat failed: {}", e),
                }
            } else {
                // Single heartbeat per subject
                // Equivalent to Python's: heartbeat_per_subject with type=heartbeat
                for item in &items {
                    let single_msg = HeartbeatMessage {
                        msg_type: "heartbeat".to_string(),
                        service: service.clone(),
                        subject: Some(item.subject.clone()),
                        subjects: None,
                        items: None,
                        router_prefix: None,
                        tags: None,
                    };
                    let payload = match serde_json::to_vec(&single_msg) {
                        Ok(p) => p,
                        Err(e) => {
                            error!(
                                "Failed to serialize heartbeat for {}: {}",
                                item.subject, e
                            );
                            continue;
                        }
                    };
                    if let Err(e) = client.publish("service.registry", payload.into()).await {
                        error!("Heartbeat for '{}' failed: {}", item.subject, e);
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Free functions
// ---------------------------------------------------------------------------

/// Get the current Unix timestamp as seconds with fractional part.
pub fn current_timestamp() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}
