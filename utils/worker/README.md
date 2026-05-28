# chongming-worker — Worker 生命周期框架

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![NATS](https://img.shields.io/badge/NATS-2.10-green.svg)](https://nats.io/)

Chongming 微服务体系的 Worker 生命周期管理框架。自动处理 NATS 连接、服务注册、心跳保活、消息分发和优雅关闭，开发者只需关注纯业务逻辑函数。

---

## 核心能力

| 能力 | 说明 |
|------|------|
| NATS 连接与重连 | 自动连接 NATS 集群，断线自动重连 |
| 服务注册 | 启动时自动向 Gateway 注册路由 |
| 心跳保活 | 定期发送心跳，防止路由被清理 |
| 消息分发与参数解析 | 自动解析 NATS 消息参数并调用处理函数 |
| 优雅关闭 | SIGINT/SIGTERM 时自动注销并关闭连接 |
| 负载均衡 | 通过 NATS Queue Group 分发请求 |

---

## 安装

```bash
uv add chongming-worker
```

---

## 使用示例

```python
from chongming_worker.worker_lifespan import WorkerLifespan
import time

# 1. 创建应用实例
app = WorkerLifespan("config.toml")

# 2. 注册消息处理函数
@app.handler("calc.add")
async def add(a: float, b: float) -> dict:
    """加法运算"""
    return {
        "result": a + b,
        "operation": "add",
        "timestamp": time.time(),
    }

# 3. 启动
if __name__ == "__main__":
    app.run()
```

---

## API 参考

### WorkerLifespan

```python
app = WorkerLifespan(config_path: str = "config.toml")
```

#### `handler(subject: str)`
装饰器：将 async 函数注册为指定 NATS subject 的消息处理器。

- `subject`: 要订阅的 NATS 主题，未指定则从配置推断
- 函数参数名应与配置 `items[].params` 一一对应
- 应返回 dict

#### `run()`
同步入口：启动事件循环并运行 Worker。自动注册 SIGINT/SIGTERM 信号处理。

#### `start()`
异步启动 Worker：连接 NATS → 注册服务 → 订阅主题 → 开始心跳。

#### `shutdown()`
异步关闭 Worker：取消心跳 → 取消订阅 → 注销服务 → 关闭 NATS 连接。

---

## 配置示例

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
queue_group = "calc-workers"
router_prefix = "/calc"
tags = ["calculator"]
heartbeat_interval = 15
items = [
    {
        subject = "calc.add",
        method = "GET",
        path = "/add",
        params = ["a", "b"],
        ttl = 30,
        timeout = 2.0,
        response_model = {
            result = ["float", "__required__"],
            operation = ["str", "add"],
            timestamp = ["float", 0.0],
        }
    }
]
```

---

## 配置校验

框架在初始化时自动校验配置合理性：
- TTL 必须大于心跳间隔，否则路由会在心跳到来前被清理
- TTL 不足时发出警告，建议 TTL ≥ 心跳间隔 × 3

---

## 依赖

| 包 | 用途 |
|------|------|
| **chongming-config** | 配置加载 |
| **chongming-logging** | 日志配置 |
| **nats-py** | NATS 消息队列客户端 |
