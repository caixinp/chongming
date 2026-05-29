# Utils Config — chongming-config

**Package:** `chongming_config`  
**Location:** `utils/config/src/chongming_config/`  
**Entry Point:** `chongming_config.load_config`

TOML 配置加载工具，为 Worker 和 Gateway 提供类型安全的配置加载能力。

---

## Core API

### `load_config(path: str) -> Config`

加载 Worker 配置。

```python
from chongming_config import load_config

config = load_config("config.toml")
```

### `load_gateway_config(path: str) -> GatewayConfig`

加载 Gateway 配置。

```python
from chongming_config import load_gateway_config

config = load_gateway_config("config.toml")
```

---

## 配置类型

### `Config` (Worker)

```python
class Config(TypedDict):
    worker: WorkerConfig           # Worker 基本信息
    nats: NATSConfig               # NATS 连接配置
    registration: RegistrationConfig  # 服务注册配置
    cleanup: Optional[CleanupConfig]  # 路由清理配置（可选）
```

### `GatewayConfig`

```python
class GatewayConfig(TypedDict):
    default: DefaultConfig          # Gateway 默认配置
    nats: NATSConfig                # NATS 连接配置
    database: DataBaseConfig        # 数据库配置
    cleanup: CleanupConfig          # 路由清理配置
```

### 子配置类型

| 类型 | 字段 | 说明 |
|------|------|------|
| `WorkerConfig` | `name`, `version`, `description` | Worker 基本信息 |
| `NATSConfig` | `urls: list[str]` | NATS 集群地址 |
| `RegistrationConfig` | `type`, `service`, `router_prefix`, `tags`, `items`, `heartbeat_interval` | 路由注册配置 |
| `RegistrationItemConfig` | `subject`, `method`, `path`, `summary`, `docstring`, `params`, `ttl`, `timeout`, `response_model` | 单个路由配置 |
| `DefaultConfig` | `debug`, `name`, `version`, `prefix`, `env` | Gateway 配置 |
| `DataBaseConfig` | `dsn`, `echo` | 数据库配置 |
| `CleanupConfig` | `interval: float` | 路由清理间隔 |

---

## 实现细节

### `get_config_path(config_path: str) -> str`

解析配置文件路径：
1. 如果是绝对路径，直接返回
2. 如果是相对路径，连接基目录（`/app/`）后返回

### 错误处理

- 文件不存在 → `FileNotFoundError`（由配置加载器自动处理）
- 格式错误 → `toml.TomlDecodeError`（由 tomli 库处理）
- 配置项非可选 → KeyError
