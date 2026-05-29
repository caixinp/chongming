# API Gateway — Chongming Gateway

**Package:** `chongming_gateway`  
**Location:** `api_gateway/src/chongming_gateway/`  
**Entry Point:** `chongming_gateway.app:app`  
**Server:** FastAPI + Uvicorn / Gunicorn  

基于 FastAPI 的动态 API 网关，通过 NATS 消息队列与后端 Worker 通信，支持动态路由注册、分布式锁保护、OpenAPI 文档自动生成。

---

## 目录

- [启动方式](#启动方式)
- [HTTP 端点](#http-端点)
- [NATS 消息协议](#nats-消息协议)
- [核心模块](#核心模块)

---

## 启动方式

### 开发模式（Uvicorn + 热重载）

```python
from chongming_gateway import serve
serve()  # 默认 0.0.0.0:8000
```

或通过 CLI：

```bash
chongming gateway
chongming gateway --host 127.0.0.1 --port 8080 --reload
```

### 生产模式（Gunicorn + 多进程）

```python
from chongming_gateway import gunicorn_serve
gunicorn_serve()  # 4 workers, 0.0.0.0:8000
```

或通过 CLI：

```bash
chongming gateway --production
```

---

## HTTP 端点

### `GET /health`

健康检查，返回状态和已注册路由列表。

```json
{
    "status": "ok",
    "registered_services": ["calc.add", "calc.subtract", "calc.multiply", "calc.divide"]
}
```

### `GET /debug/routes`

调试端点，列出所有已注册动态路由详情。

```json
{
    "routes": [
        {
            "prefix": "/calc",
            "path": "/calc/add",
            "methods": ["GET"],
            "name": "calc.add"
        }
    ],
    "router_prefixes": ["/calc"],
    "registry_lock_type": "chongming_lock.MutexLock (distributed)",
    "total_registered": 4
}
```

### 动态路由

由 Worker 通过 NATS 消息动态注册，自动出现在 FastAPI OpenAPI schema。

**请求参数规范：**

| 格式 | 示例 | 说明 |
|------|------|------|
| 纯参数名 | `["a", "b"]` | 类型默认为 `str` |
| 带类型声明 | `["a: float", "b: float"]` | 网关层严格类型校验 |

**支持的参数类型：** `str`、`int`、`float`、`bool`

**校验失败时返回 HTTP 400 Bad Request。**

---

## NATS 消息协议

### 服务注册 (`service.registry`)

Gateway 订阅 `service.registry` 主题，处理以下消息类型：

#### `type = "register"` — 服务注册

Worker 首次启动或 NATS 重连后发送。

```json
{
    "type": "register",
    "service": "example",
    "router_prefix": "/calc",
    "tags": ["calc"],
    "items": [
        {
            "subject": "calc.add",
            "method": "GET",
            "path": "/calc/add",
            "summary": "加法运算",
            "docstring": "两数相加",
            "params": ["a: float", "b: float"],
            "ttl": 60,
            "timeout": 2.0,
            "response_model": {
                "result": "float",
                "operation": "str",
                "timestamp": "float"
            }
        }
    ]
}
```

#### `type = "heartbeat"` — 心跳保活

**单个路由心跳（常规周期）：**
```json
{
    "type": "heartbeat",
    "service": "example",
    "subject": "calc.add"
}
```

**批量路由心跳（每 3 次心跳周期，推荐）：**
```json
{
    "type": "heartbeat",
    "service": "example",
    "subjects": ["calc.add", "calc.subtract", "calc.multiply", "calc.divide"],
    "items": [/* 完整路由信息 */],
    "router_prefix": "/calc",
    "tags": ["calc"]
}
```

批量心跳携带完整 items，Gateway 重启后自动恢复路由。

#### `type = "deregister"` — 服务注销

Worker 优雅关闭时发送。

```json
{
    "type": "deregister",
    "service": "example",
    "router_prefix": "/calc"
}
```

---

## 核心模块

### `chongming_gateway.app`

| 函数 | 说明 |
|------|------|
| `registry_listener(msg, app)` | 处理注册/心跳/注销消息，使用分布式锁保护注册表 |
| `cleanup_expired_routes(app)` | 后台任务，定期清理 TTL 过期路由 |
| `lifespan(app)` | FastAPI 生命周期：连接 NATS、初始化缓存与锁、订阅主题、启动清理任务 |

### `chongming_gateway.app.core.dynamic_route`

**`class DynamicRoute`** — 动态路由管理器，采用 `app.state` 单例模式。

| 方法 | 说明 |
|------|------|
| `add_dynamic_route(...)` | 添加动态路由到 FastAPI app.router |
| `remove_dynamic_route(prefix, path, method)` | 移除指定动态路由 |
| `get_registered_routes()` | 获取所有已注册路由详情 |
| `get_registered_prefixes()` | 获取所有 router prefix 列表 |

**参数：**

- `subject` (str): NATS subject
- `method` (str): HTTP 方法 (GET/POST/PUT/DELETE)
- `path` (str): 路由路径
- `params` (list[str]): 参数列表，支持 `"name: type"` 格式
- `timeout` (float): NATS 请求超时（默认 2.0s）
- `response_model` (dict|BaseModel|list|null): Pydantic 响应模型定义

### `chongming_gateway.app.core.nats_client`

| 函数 | 说明 |
|------|------|
| `get_nats_client()` | 获取 NATS 客户端单例，自动从环境变量或配置读取服务器地址 |
| `_get_nats_urls()` | 获取 NATS 服务器地址列表 |

**NATS 地址优先级：**

1. 环境变量 `NATS_SERVERS`（逗号分隔）
2. 配置文件 `config.toml` 中 `nats.urls`
3. 默认值 `["nats://localhost:4222", "nats://localhost:4223", "nats://localhost:4224"]`
