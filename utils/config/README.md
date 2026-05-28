# chongming-config — TOML 配置加载工具

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

Chongming 微服务体系的配置加载工具包，基于 TOML 文件格式，提供强类型配置结构定义。

---

## 安装

```bash
uv add chongming-config
```

---

## 使用示例

```python
from chongming_config import load_config

config = load_config("config.toml")
print(config["worker"]["name"])
print(config["nats"]["urls"])
```

---

## 配置模型

```python
class Config(TypedDict):
    worker: WorkerConfig
    nats: NATSConfig
    registration: RegistrationConfig  # Worker 路由注册
    cleanup: CleanupConfig            # Gateway 路由清理（可选）
```

### WorkerConfig

| 字段 | 类型 | 说明 |
|------|------|------|
| name | str | Worker 名称 |
| version | str | 版本号 |
| description | str | 描述信息 |

### NATSConfig

| 字段 | 类型 | 说明 |
|------|------|------|
| urls | list[str] | NATS 集群地址列表 |

### RegistrationConfig

| 字段 | 类型 | 说明 |
|------|------|------|
| type | str | 消息类型（register） |
| service | str | 服务名称 |
| router_prefix | str | 路由前缀 |
| tags | list[str] | OpenAPI 标签 |
| items | list[RegistrationItemConfig] | 路由注册项 |
| heartbeat_interval | int | 心跳间隔（秒） |

### RegistrationItemConfig

| 字段 | 类型 | 说明 |
|------|------|------|
| subject | str | NATS 主题 |
| method | str | HTTP 方法 |
| path | str | 路由路径 |
| summary | str | 接口摘要 |
| docstring | str | 接口描述 |
| params | list[str] | 参数列表 |
| ttl | int | 路由 TTL（秒） |
| timeout | float | 请求超时（秒） |
| response_model | Any | 响应模型定义 |

---

## 依赖

- **tomli** — TOML 格式解析
