# User Auth Worker — 用户认证与授权服务

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![NATS](https://img.shields.io/badge/NATS-2.10-green.svg)](https://nats.io/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg)](https://www.postgresql.org/)

基于 `chongming-worker` 框架开发的用户认证与授权微服务，提供用户注册、登录、JWT Token 发放与验证、用户信息管理等功能，是 Chongming 微服务体系的身份认证中心。

---

## 业务功能

| 接口 | 方法 | 路径 | 说明 | 认证要求 |
|------|------|------|------|----------|
| 用户注册 | POST | `/api/v1/user/auth/register` | 创建新用户 | ❌ 公开 |
| 用户登录 | POST | `/api/v1/user/auth/login` | 密码验证，发放 Token | ❌ 公开 |
| Token 刷新 | POST | `/api/v1/user/auth/refresh` | 刷新过期 Token | ❌ 公开 |
| 获取用户信息 | GET | `/api/v1/user/info` | 获取当前用户信息 | ✅ 需认证 |
| 更新用户信息 | PUT | `/api/v1/user/update` | 更新用户资料 | ✅ 需认证 |

---

## 快速开始

### 前置条件

- Python 3.12+
- NATS 集群运行中（参考 `docker-env/README.md`）
- PostgreSQL 数据库就绪

### 启动 Worker

```bash
cd workers/user_auth
uv sync
python main.py
```

### 测试 API

```bash
# 用户注册
curl -X POST "http://localhost:8000/api/v1/user/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "secure123", "email": "alice@example.com"}'

# 用户登录
curl -X POST "http://localhost:8000/api/v1/user/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "secure123"}'

# Token 刷新
curl -X POST "http://localhost:8000/api/v1/user/auth/refresh" \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "..."}'

# 获取用户信息（需携带 Token）
curl "http://localhost:8000/api/v1/user/info" \
  -H "Authorization: Bearer <access_token>"

# Swagger UI
open http://localhost:8000/docs
```

---

## 代码结构

```
workers/user_auth/
├── main.py                     # ★ 入口文件
├── config.toml                 # ★★ 核心配置文件（NATS、路由、数据库）
├── pyproject.toml              #   Python 项目配置
├── app/
│   ├── __init__.py
│   ├── bootstrap.py            # ★ WorkerLifespan 实例
│   ├── database_models/
│   │   ├── __init__.py         #   SQLAlchemy ORM 模型（User）
│   │   └── ...
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── auth.py             #   认证相关 handler
│   │   └── user.py             #   用户信息管理 handler
│   ├── listeners/
│   │   ├── __init__.py         #   NATS KV 配置监听
│   │   └── ...
│   └── utils/
│       └── snowflake.py        #   Snowflake ID 生成器
├── models/
│   └── __init__.py             #   自动生成的 Pydantic 模型
└── public/
    └── __init__.py             #   共享模型（跨 Worker 复用）
```

---

## 核心特性

### JWT 认证全链路

```
客户端 ─── POST/login ──→ Gateway ── NATS ──→ User-Auth Worker
  │                                                    │
  │                                                    ├─ 验证用户名密码
  │                                                    ├─ 生成 Access Token（短时效）
  │                                                    ├─ 生成 Refresh Token（长时效）
  │                                                    └─ 返回 Tokens
  │
  │── 后续请求携带 Authorization: Bearer <token> ──→ Gateway
                                                       │
                                                       ├─ 验证 Token 有效性
                                                       ├─ 注入 User-Id Header
                                                       └─ 转发 Worker
```

### 动态 JWT 密钥更新

通过 NATS KV Store (`_gw_config_` 桶) 实时监听 Gateway 配置变更：

```python
# app/listeners/__init__.py
@app.on_start
async def listen_gateway_config_changes():
    """Gateway 更新 JWT 密钥时，实时同步更新"""
    # 1. 连接 _gw_config_ KV 桶
    # 2. 读取当前 gateway_config
    # 3. 订阅 gateway_config 变更
    # 4. 配置变更时自动更新 JWTAuth 实例
```

**流程：** Gateway 配置变更 → NATS KV 更新 → Listener 回调 → JWTAuth 实例自动替换

### Snowflake ID 生成

替代数据库自增主键，生成全局唯一的分布式 ID：

```python
from app.utils.snowflake import snowflake_generator

# 生成用户 ID
user_id = await snowflake_generator.generate()  # → 1523412345678901234

# 提取创建时间戳
ts = snowflake_generator.extract_timestamp(user_id)
```

**ID 结构：**
```
0         41              51          64
├─────────┼─────────────────┼───────────┤
│  时间戳  │    节点 ID      │  序列号   │
│  (ms)   │   (0-1023)      │  (0-4095) │
├─────────┼─────────────────┼───────────┤
```

### 分布式追踪

请求链路通过 `request_id` 贯穿 Gateway → Worker → 日志，便于问题排查：

```
Gateway 生成 request_id ──NATS headers──→ Worker
                                            │
                                            ├─ 日志自动注入 [request_id]
                                            ├─ 数据库操作记录 request_id
                                            └─ 异常上报附带 request_id
```

---

## 数据库迁移

使用 `chongming db` 管理数据库迁移：

```bash
# 查看当前版本
chongming db current --db-url "postgresql://myuser:mypassword@localhost:5432/mydb"

# 创建迁移
chongming db migrate -m "add user table" --db-url "..."

# 应用迁移
chongming db upgrade --db-url "..."
```

### 迁移文件

```
utils/python/database/migrations/
├── env.py                       # Alembic 环境配置
├── versions/
│   ├── 0001_initial_empty.py    # 空基线（标记初始状态）
│   └── 0002_user_id_bigint.py   # Snowflake ID 迁移
└── ...
```

---

## 共享模型

此 Worker 的部分模型可以在其他 Worker 中复用：

```bash
# 生成共享模型
chongming gen-models user_auth --output workers/user_auth/public/__init__.py --shared
```

```python
# 在其他 Worker 中导入
from workers.user_auth.public import AuthLoginOutput, UserInfoOutput
```

---

## 配置参考

### config.toml 注册的路由

```toml
[registration]
items = [
    { subject = "user.auth.register", method = "POST", path = "/auth/register", ... },
    { subject = "user.auth.login",    method = "POST", path = "/auth/login",    ... },
    { subject = "user.auth.refresh",  method = "POST", path = "/auth/refresh",  ... },
    { subject = "user.info",         method = "GET",  path = "/info",          auth_required = true },
    { subject = "user.update",       method = "PUT",  path = "/update",        auth_required = true },
]
```

完整配置格式参考 [Worker 框架文档](../../utils/python/worker/README.md) 或 [config.toml 详解](../../cli/README.md#worker-configtoml-配置详解)。

---

## 依赖

| 包 | 用途 |
|------|------|
| **chongming-worker** | Worker 生命周期框架 |
| **chongming-config** | TOML 配置加载 |
| **chongming-logging** | 统一日志 + 分布式追踪 |
| **chongming-jwt** | JWT Token 创建与验证 |
| **chongming-cache** | NATS KV 缓存（监听配置变更） |
| **chongming-database** | 数据库连接初始化 |
| **SQLAlchemy** | ORM 框架 |
| **Alembic** | 数据库迁移 |
| **asyncpg** | PostgreSQL 异步驱动 |

---

## 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| 注册成功但无法登录 | 密码哈希算法不一致 | 确保 `register` 和 `login` 使用相同的哈希方式 |
| Token 验证失败 | JWT 密钥不匹配 | 检查 Gateway 和 Worker 的密钥配置是否一致 |
| Snowflake ID 冲突 | 节点 ID 超出范围 | 检查 NATS KV `_worker_id_` 桶状态 |
| 数据库连接失败 | PostgreSQL 未启动或配置错误 | 确认 `docker compose ps` 中 pg 状态正常 |

---

## 下一步

- 阅读 [Worker 框架文档](../../utils/python/worker/README.md) 了解 Worker 开发细节
- 阅读 [CLI 文档](../../cli/README.md) 了解构建和部署
- 阅读 [Docker 部署文档](../../docker-env/README.md) 了解生产环境配置
