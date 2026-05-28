# chongming-logging — 统一日志配置工具

Chongming 微服务体系的统一日志配置工具包，为各组件提供一致的日志输出格式和级别设置。

---

## 安装

```bash
uv add chongming-logging
```

---

## 使用示例

```python
from chongming_logging import setup_logging

# 默认配置（INFO 级别，stdout 输出）
setup_logging()
```

### 组件专用配置

```python
from chongming_logging import setup_worker_logging, setup_gateway_logging

setup_worker_logging()
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
| `setup_worker_logging(level, fmt)` | Worker 组件专用 |
| `setup_gateway_logging(level, fmt)` | Gateway 组件专用 |

### 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `level` | int | `logging.INFO` | 日志级别 |
| `fmt` | str | `"%(asctime)s [%(levelname)s] %(name)s: %(message)s"` | 日志格式 |
| `force` | bool | `False` | 是否强制覆盖已有配置 |

---

## 特性

- 自动检测已有配置，避免重复设置
- `force` 参数可强制覆盖
- 默认输出到 stdout

---

## 依赖

无外部依赖。
