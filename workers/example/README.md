# Example Worker — 计算器微服务

基于 `chongming-worker` 框架开发的示例微服务，提供四则运算功能，演示 Worker 开发标准流程。

---

## 业务功能

| 接口 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 加法 | GET | `/calc/add?a=10&b=20` | 两数相加 |
| 减法 | GET | `/calc/subtract?a=30&b=10` | 两数相减 |
| 乘法 | GET | `/calc/multiply?a=6&b=7` | 两数相乘 |
| 除法 | GET | `/calc/divide?a=100&b=3` | 两数相除（除数不能为 0） |

### 响应格式

```json
{
    "result": 30.0,
    "operation": "add",
    "timestamp": 1234567890.123
}
```

---

## 快速开始

### 前置条件

1. 启动 NATS 集群（参考 `docker-env/README.md`）
2. 启动 API Gateway

### 启动 Worker

```bash
cd workers/example
uv sync
python main.py
```

启动后自动：
1. 连接 NATS 集群
2. 向 Gateway 注册路由
3. 开始心跳保活

### 测试

```bash
# 加法
curl "http://localhost:8000/api/v1/calc/add?a=10&b=20"

# 减法
curl "http://localhost:8000/api/v1/calc/subtract?a=30&b=10"

# 乘法
curl "http://localhost:8000/api/v1/calc/multiply?a=6&b=7"

# 除法
curl "http://localhost:8000/api/v1/calc/divide?a=100&b=3"

# 除零错误
curl "http://localhost:8000/api/v1/calc/divide?a=1&b=0"
# → {"error": "除数不能为 0"}
```

---

## 代码结构

```
workers/example/
├── main.py       # 业务逻辑（仅纯函数实现）
├── config.toml   # 服务配置（NATS、路由注册、心跳）
├── pyproject.toml
├── uv.lock
└── README.md
```

### main.py

```python
import logging
import time
from chongming_worker.worker_lifespan import WorkerLifespan

# 创建应用实例
app = WorkerLifespan("config.toml")

# 注册业务处理函数
@app.handler("calc.add")
async def add(a: float, b: float) -> dict:
    """加法运算"""
    result = a + b
    return {"result": result, "operation": "add", "timestamp": time.time()}

# 启动
if __name__ == "__main__":
    app.run()
```

开发者只需关注纯函数的业务逻辑实现，无需关心基础设施代码。

---

## 配置参考

`config.toml` 定义了 NATS 连接、路由注册、心跳等基础设施配置。详见 [chongming-worker 配置文档](../../utils/worker/README.md#配置示例)。
