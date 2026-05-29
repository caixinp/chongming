# Utils Logging — chongming-logging

**Package:** `chongming_logging`  
**Location:** `utils/logging/src/chongming_logging/`

统一日志配置工具包，支持分布式追踪上下文（request_id）的自动注入。

---

## Core API

### `setup_logging(level=INFO, fmt=..., force=False)`

配置日志输出格式。

```python
from chongming_logging import setup_logging

setup_logging()                         # 默认级别 INFO
setup_logging(level=logging.DEBUG)      # 设置 DEBUG 级别
setup_logging(force=True)               # 强制覆盖已有配置
```

**参数：**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `level` | int | `logging.INFO` | 日志级别 |
| `fmt` | str | 带 `[%(request_id)s]` 的格式 | 日志格式字符串 |
| `force` | bool | `False` | 是否强制覆盖已有配置 |

**日志格式：**
```
2024-01-01 12:00:00 [INFO] [550e8400-e29b-41d4-a716-446655440000] chongming.worker: message here
```

### `setup_worker_logging(level=INFO, fmt=...)`

Worker 日志便捷配置函数。

### `setup_gateway_logging(level=INFO, fmt=...)`

Gateway 日志便捷配置函数。

---

## 分布式追踪 API

使用 `contextvars` 实现协程安全的 request_id 传递。

### `set_request_id(request_id: str)`

设置当前上下文的 request_id。

```python
from chongming_logging import set_request_id

set_request_id("550e8400-e29b-41d4-a716-446655440000")
```

### `get_request_id() -> str`

获取当前上下文的 request_id。

```python
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

此 Filter 在模块加载时自动挂载到 root logger。

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
