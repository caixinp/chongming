# chongming-database — 数据库初始化与迁移工具

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-red.svg)](https://www.sqlalchemy.org/)
[![Alembic](https://img.shields.io/badge/Alembic-1.13-00BFFF.svg)](https://alembic.sqlalchemy.org/)

Chongming 微服务体系的数据库初始化、会话管理和迁移工具包，基于 **SQLAlchemy Async** 和 **Alembic** 构建，为各 Worker 提供统一的数据库连接管理和迁移能力。

---

## 安装

```bash
uv add chongming-database
```

---

## 快速开始

### 数据库初始化

```python
from chongming_database import DatabaseManager

# 创建数据库管理器
db = DatabaseManager(
    url="postgresql+asyncpg://myuser:mypassword@localhost:5432/mydb",
    pool_size=10,
    max_overflow=20,
)

# 初始化连接池
await db.initialize()

# 获取会话
async with db.session() as session:
    result = await session.execute(text("SELECT 1"))
    print(result.scalar())

# 关闭连接池
await db.close()
```

---

## API 参考

### `DatabaseManager`

数据库连接管理器，使用 SQLAlchemy async engine 管理连接池。

| 方法 | 说明 |
|------|------|
| `initialize()` | 初始化连接池 |
| `session()` | 获取异步数据库会话（上下文管理器） |
| `close()` | 关闭连接池 |

### 配置示例

```python
from chongming_database import DatabaseManager

db = DatabaseManager(
    url="postgresql+asyncpg://user:password@host:port/dbname",
    pool_size=5,           # 连接池大小
    max_overflow=10,       # 最大溢出连接数
    pool_pre_ping=True,    # 连接前 Ping 检测
    echo=False,            # SQL 日志
)
```

---

## 与 Alembic 集成

项目使用 **Alembic** 管理数据库迁移，迁移文件位于 `utils/python/database/migrations/`。

### 迁移目录结构

```
utils/python/database/
├── alembic.ini                    # Alembic 配置文件
├── migrations/
│   ├── env.py                     # Alembic 环境配置
│   ├── script.py.mako             # 迁移模板
│   └── versions/
│       ├── 0001_initial_empty.py  # 空基线（标记初始状态）
│       └── 0002_user_id_bigint.py # Snowflake ID 迁移
└── src/
    └── chongming_database/
        ├── __init__.py            # DatabaseManager 导出
        └── ...
```

### 通过 CLI 管理迁移

```bash
# 查看当前数据库版本
chongming db current --db-url "postgresql://user:pass@localhost:5432/dbname"

# 创建新迁移
chongming db migrate -m "add user table" --db-url "..."

# 应用迁移
chongming db upgrade --db-url "..."

# 回滚迁移
chongming db downgrade --db-url "..."

# 标记已有数据库
chongming db stamp 0001 --db-url "..."

# 离线生成 SQL 脚本
chongming db upgrade head --sql
```

---

## 在 Worker 中使用

```python
# app/bootstrap.py
from chongming_database import DatabaseManager
from chongming_worker.worker_lifespan import WorkerLifespan

app = WorkerLifespan("config.toml")
db = DatabaseManager(
    url="postgresql+asyncpg://myuser:mypassword@localhost:5432/mydb",
)

@app.on_start
async def init_db():
    """Worker 启动时初始化数据库连接"""
    await db.initialize()

@app.on_stop
async def close_db():
    """Worker 关闭时释放数据库连接"""
    await db.close()
```

---

## 依赖

| 包 | 用途 |
|------|------|
| **SQLAlchemy** | ORM 框架（Async 模式） |
| **asyncpg** | PostgreSQL 异步驱动 |
| **Alembic** | 数据库迁移管理 |
| **chongming-config** | TOML 配置加载（可选） |

---

## 相关文档

- [CLI 迁移命令](../../cli/README.md#数据库迁移管理) — `chongming db` 命令详解
- [Worker 生命周期框架](../worker/README.md) — Worker 启动/关闭钩子
- [User Auth Worker](../../workers/user_auth/README.md) — 实际使用示例
