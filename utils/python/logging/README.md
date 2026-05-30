# chongming-logging — 统一日志配置工具

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

Chongming 微服务体系的统一日志配置工具包，为各组件提供一致的日志输出格式和级别设置。支持**分布式追踪**，自动在日志中注入 `request_id`。

---

## 安装

```bash
uv add chongming-logging
```

---

## 快速开始

```python
from chongming_logging import setup_logging

# 默认配置（INFO 级别，stdout 输出）
setup_logging()
```

### 组件专用配置

```python
from chongming_logging import setup_worker_logging, setup_gateway_logging

# Worker 日志配置
setup_worker_logging()

# Gateway 日志配置
setup_gateway_logging()
```

### 自定义配置

```python
import logging
from chongming_logging import setup_logging

setup_logging(
    level=logging.DEBUG,
    fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    force=True,  # 强制覆盖已有配置
)
```

---

## API 参考

| 函数 | 说明 |
|------|------|
| `setup_logging(level, fmt, force)` | 通用日志配置 |
| `setup_worker_logging(level, fmt)` | Worker 组件专用配置 |
| `setup_gateway_logging(level, fmt)` | Gateway 组件专用配置 |

### 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `level` | `int` | `logging.INFO` | 日志级别 |
| `fmt` | `str` | 带 `[%(request_id)s]` 的格式 | 日志格式字符串 |
| `force` | `bool` | `False` | 是否强制覆盖已有配置 |

### 默认日志格式

```
2024-01-01 12:00:00 [INFO] [550e8400-e29b-41d4-a716-446655440000] chongming.worker: message here
```

---

## 分布式追踪 API

使用 `contextvars` 实现协程安全的 `request_id` 传递，无需修改函数签名。

### `set_request_id(request_id: str)`

设置当前上下文的 request_id。

```python
from chongming_logging import set_request_id

set_request_id("550e8400-e29b-41d4-a716-446655440000")
```

### `get_request_id() -> str`

获取当前上下文的 request_id。

```python
from chongming_logging import get_request_id

rid = get_request_id()  # 返回当前协程的 request_id
```

---

## `RequestIdFilter`

日志 Filter，自动从 contextvars 中获取 request_id 并注入日志记录。

```python
class RequestIdFilter(logging.Filter):
    def filter(self, record) -> bool:
        record.request_id = get_request_id() or "-"
        return True
```

此 Filter 在模块加载时自动挂载到 root logger，确保所有子日志器自动带上 `[request_id]` 字段。

---

## 追踪流程

```
Gateway                          Worker
  |                                |
  |--- NATS request (headers) ---->|  set_request_id(gateway_rid)
  |   {request_id: uuid4}         |
  |                                |  ├── 日志自动带上 [request_id]
  |                                |  └── 响应头回传 request_id
  |<-- NATS response (headers) ----|
  |   {request_id: worker_rid}     |
  |                                |
  校验 request_id 一致性
```

---

## 特性

- 自动检测已有配置，避免重复设置
- `force` 参数可强制覆盖
- 默认输出到 stdout
- 分布式追踪通过 NATS headers 自动传递

---

## 依赖

无外部依赖。
