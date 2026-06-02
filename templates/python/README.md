# Python Worker 模板

基于 `chongming-worker` 框架的 Python Worker 脚手架模板。使用 CLI 命令 `chongming new my-worker` 时，从此模板复制并自动重命名。

---

## 🎯 使用方式

```bash
# 创建 Python Worker（默认）
chongming new my-service

# 创建时跳过虚拟环境创建
chongming new my-service --no-venv
```

创建后的第一件事：**编辑 `config.toml`**，修改 Worker 名称、NATS 地址、添加你的路由定义。

---

## 模板结构

```
your-worker/
├── main.py                 # ★ 入口文件（最简单的：from app.bootstrap import app; app.run()）
├── config.toml             # ★★ 核心配置文件——Worker 的"心脏"
│                           #    定义所有路由、参数、NATS 连接、心跳间隔
├── pyproject.toml          #   Python 项目配置
├── app/
│   ├── __init__.py
│   ├── bootstrap.py        # ★ WorkerLifespan 实例（加载 config.toml）
│   └── handlers/
│       ├── __init__.py     # ★ 导入并注册所有 handler 模块
│       ├── calc.py         #   纯业务 handler 示例
│       ├── user.py         #   被动服务 handler 示例
│       ├── order.py        #   主动调用 + publish 接收 示例
│       └── system.py       #   _nc / _app 注入演示
├── models/
│   └── __init__.py         #   自动生成的 Pydantic 模型文件
└── public/
    └── config.toml         #   公开配置（可选）
```

---

## 核心设计：`config.toml` 驱动一切

这个模板演示了 **5 大核心特性**，全部由 `config.toml` 驱动：

| # | 特性 | Handler | 说明 |
|---|------|---------|------|
| 1 | **基本 Handler 注册** | `calc.add/subtract/multiply/divide` | 最基础的 handler，纯业务逻辑 |
| 2 | **被动服务** | `user.query` | 被其他 handler 通过 `_app.request()` 调用 |
| 3 | **主动调用 + 异步广播** | `order.create` | `_app.request()` 同步调用 + `_app.publish()` 异步广播 |
| 4 | **异步通知接收** | `notification.order_created` | 通过 publish 触发的独立 handler |
| 5 | **框架注入** | `system.info` / `user.health_check` | `_app` 和 `_nc` 参数由框架自动注入 |

---

## 快速开始

### 1. 启动基础设施

```bash
cd docker-env
docker compose up -d
```

### 2. 启动 API Gateway

```bash
cd api_gateway
uv sync
uv run serve
```

### 3. 启动 Worker

```bash
cd workers/<your-worker>
uv sync
python main.py
```

### 4. 测试

```bash
curl "http://localhost:8000/api/v1/calc/add?a=10&b=20"
curl -X POST "http://localhost:8000/api/v1/order/create" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "u001", "amount": 30, "item": "book"}'
```

---

## 配置参考

### config.toml 基础结构

```toml
[worker]
name = "my-worker"           # ← 创建后第一件事：修改这里
version = "0.1.0"
description = "my worker"

[nats]
urls = ["nats://localhost:4222"]

[registration]
type = "register"
service = "my-worker"
queue_group = "my-workers"
heartbeat_interval = 15

items = [
    # 在这里添加你的路由定义
]

[logging.minio]
enabled = true
endpoint = "localhost:9000"
bucket = "chongming-logs"
retention_days = 30
```

完整配置格式参考 [Worker 框架文档](../../utils/python/worker/README.md)。

---

## 与 workers/example/ 的关系

| 对比 | `workers/example/` | `templates/python/` |
|------|-------------------|---------------------|
| 定位 | 可运行的完整示例 | 脚手架模板（用于 `chongming new`） |
| 内容 | 包含完整注释和文档 | 精简版，预留自定义空间 |
| 更新 | 跟随框架特性更新 | 定期从 example 同步新特性 |

---

## 相关文档

- [Worker 生命周期框架](../../utils/python/worker/README.md) — Worker 的核心 API
- [CLI 工具](../../cli/README.md) — `chongming new` 等命令详解
- [示例 Worker 文档](../../workers/example/README.md) — 完整功能学习指南
- [Docker 部署](../../docker-env/README.md) — 生产环境配置
