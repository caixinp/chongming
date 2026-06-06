# Chongming API 文档

Chongming 微服务框架的内部 API 参考文档，面向框架开发者和源码阅读者。

---

## 项目结构

```
chongming/
├── api_gateway/        # API 网关（FastAPI + NATS）
├── cli/                # 命令行工具（包含 trace 链路追踪）
├── workers/            # Worker 服务实例
│   ├── example/        # Python Worker 示例（计算器 + Worker 间通讯）
│   ├── example_rs/     # Rust Worker 示例
│   └── user_auth/      # 用户认证 Worker（JWT + Snowflake ID）
├── templates/          # Worker 脚手架模板
│   ├── python/         # Python Worker 模板（来自 example）
│   └── rust/           # Rust Worker 模板（来自 example_rs）
├── utils/              # 工具库（PyPI 独立包）
│   ├── cache/          # chongming-cache — NATS KV 缓存
│   ├── config/         # chongming-config — 配置加载
│   ├── database/       # chongming-database — 数据库管理
│   ├── jwt/            # chongming-jwt — JWT 认证
│   ├── lock/           # chongming-lock — 分布式锁
│   ├── logging/        # chongming-logging — 日志 + 分布式追踪
│   ├── permission/     # chongming-permission — 权限缓存
│   └── worker/         # chongming-worker — Python Worker 框架
├── docker-env/         # Docker 部署配置
├── front/              # Vue 3 管理面板
└── docs/               # 技术文档
```

---

## API 文档索引

| 子项目 | 文档 | 说明 |
|--------|------|------|
| API Gateway | [api_gateway.md](api_gateway.md) | 动态 API 网关核心模块 |
| CLI | [cli.md](cli.md) | 项目管理命令行工具（含 trace 链路追踪） |
| Cache | [utils_cache.md](utils_cache.md) | NATS JetStream KV 缓存库 |
| Config | [utils_config.md](utils_config.md) | TOML 配置加载 |
| Lock | [utils_lock.md](utils_lock.md) | 分布式锁库（6 种） |
| Logging | [utils_logging.md](utils_logging.md) | 日志配置 + 分布式追踪 |
| Worker (Python) | [utils_worker.md](utils_worker.md) | Python Worker 生命周期框架 |
| Worker (Rust) | [rust_worker.md](rust_worker.md) | Rust Worker 生命周期框架 |

---

## 架构概览

```
┌─────────────┐    HTTP     ┌──────────────┐   NATS    ┌──────────────┐
│   Client    │ ────────────│ API Gateway  │ ──────────│   Worker     │
│  (Browser)  │             │  (FastAPI)   │           │  (Python/Rust)│
└─────────────┘             └──────────────┘           └──────────────┘
                                     │                        │
                                     │ NATS JetStream         │
                                     ▼                        ▼
                              ┌──────────────┐       ┌──────────────┐
                              │ Chongming    │       │ Chongming    │
                              │ Cache/Lock   │       │ Config       │
                              └──────────────┘       └──────────────┘
```

### 数据流

1. **客户端** → 发送 HTTP 请求到 **API Gateway**
2. **API Gateway** → 通过 NATS Request-Reply 转发到 **Worker**
3. **Worker** → 处理请求，可选使用 `Cache/Lock` 做状态管理
4. **Worker** → 返回结果，`API Gateway` 响应客户端

### 调试：实时追踪请求链路

```bash
# 追踪一次请求-响应（Core NATS 实时监听）
chongming trace calc.add

# 持续追踪
chongming trace user.register --follow --pretty

# 回放最近 1 小时历史（JetStream）
chongming trace order.create --since 1h --js
```

`chongming trace` 是内置的 NATS 链路追踪工具，详细实现见 [CLI API 文档](cli.md#trace)。

### 关键概念

- **服务注册**：Worker 通过 NATS `service.registry` 主题向 Gateway 注册路由
- **心跳续期**：Worker 定期发送心跳保持路由有效（批量心跳携带完整信息用于恢复）
- **分布式锁**：基于 NATS JetStream KV 的 CAS 乐观锁，6 种锁类型
- **分布式追踪**：Gateway 生成 `request_id`，通过 NATS headers 传递到 Worker
- **链路追踪工具**：`chongming trace` 实时追踪请求-响应，关联 request_id 和耗时