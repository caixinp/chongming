# chongming-config — TOML 配置加载工具

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

Chongming 微服务体系的配置加载工具包，基于 **TOML** 文件格式，提供类型安全的配置结构定义，支持 Worker 和 Gateway 两种配置模型。

---

## 安装

```bash
uv add chongming-config
```

---

## 快速开始

```python
from chongming_config import load_config, load_gateway_config

# 加载 Worker 配置
config = load_config("config.toml")
print(config["worker"]["name"])  # Worker 名称
print(config["nats"]["urls"])    # NATS 集群地址

# 加载 Gateway 配置
gateway_config = load_gateway_config("config.toml")
print(gateway_config["default"]["prefix"])  # 路由前缀
```

---

## 配置模型

### Worker 配置 (`Config`)

```python
class Config(TypedDict):
    worker: WorkerConfig           # Worker 基本信息
    nats: NATSConfig               # NATS 连接配置
    registration: RegistrationConfig  # 服务注册配置
    cleanup: CleanupConfig         # 路由清理配置（可选）
```

### Gateway 配置 (`GatewayConfig`)

```python
class GatewayConfig(TypedDict):
    default: DefaultConfig         # Gateway 默认配置
    nats: NATSConfig               # NATS 连接配置
    database: DataBaseConfig       # 数据库配置
    cleanup: CleanupConfig         # 路由清理配置
```

---

## 配置类型详情

### `WorkerConfig`

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | `str` | Worker 名称 |
| `version` | `str` | 版本号 |
| `description` | `str` | 描述信息 |

### `NATSConfig`

| 字段 | 类型 | 说明 |
|------|------|------|
| `urls` | `list[str]` | NATS 集群地址列表 |

### `RegistrationConfig`

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | `str` | 消息类型（`register`） |
| `service` | `str` | 服务名称 |
| `router_prefix` | `str` | 路由前缀 |
| `tags` | `list[str]` | OpenAPI 标签 |
| `items` | `list[RegistrationItemConfig]` | 路由注册项列表 |
| `heartbeat_interval` | `int` | 心跳间隔（秒），默认 15 |

### `RegistrationItemConfig`

| 字段 | 类型 | 说明 |
|------|------|------|
| `subject` | `str` | NATS 主题 |
| `method` | `str` | HTTP 方法 |
| `path` | `str` | 路由路径 |
| `summary` | `str` | 接口摘要 |
| `docstring` | `str` | 接口描述 |
| `params` | `list[str]` | 参数列表，支持 `"name: type"` 格式 |
| `ttl` | `int` | 路由 TTL（秒） |
| `timeout` | `float` | 请求超时（秒） |
| `response_model` | `Any` | 响应模型定义 |

### `DefaultConfig` (Gateway)

| 字段 | 类型 | 说明 |
|------|------|------|
| `debug` | `bool` | 调试模式 |
| `name` | `str` | 网关名称 |
| `version` | `str` | 版本号 |
| `prefix` | `str` | 路由前缀 |
| `env` | `str` | 运行环境（`development` / `production`） |

### `CleanupConfig`

| 字段 | 类型 | 说明 |
|------|------|------|
| `interval` | `float` | 过期路由清理检查间隔（秒），默认 10 |

---

## 示例配置（Worker）

```toml
[worker]
name = "example"
version = "0.1.0"
description = "chongming worker example"

[nats]
urls = [
    "nats://localhost:4222",
    "nats://localhost:4223",
    "nats://localhost:4224",
]

[registration]
type = "register"
service = "calc"
router_prefix = "/calc"
tags = ["calculator"]
heartbeat_interval = 15

[[registration.items]]
subject = "calc.add"
method = "GET"
path = "/add"
summary = "加法运算"
docstring = "两数相加"
params = ["a: float", "b: float"]
ttl = 60
timeout = 2.0
[registration.items.response_model]
result = "float"
operation = "str"
timestamp = "float"
```

---

## 依赖

- **tomli** — TOML 格式解析（Python 3.11+ 内置，3.10 以下需额外安装）
