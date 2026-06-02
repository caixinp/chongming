# 🔐 chongming-permission

基于 NATS JetStream KV 的分布式权限缓存工具包。

## 架构

```
┌─────────────────┐     ┌─────────────────────┐
│  require_permission  │     │  _permission_cache_  │
│  (装饰器)        │────▶│  (NATS KV 桶)       │
└─────────────────┘     └─────────────────────┘
        │                         │
        │ 缓存未命中              │ 缓存命中
        ▼                         ▼
┌─────────────────┐     ┌─────────────────────┐
│  数据库加载器    │     │  直接返回权限列表    │
│  (业务侧注册)    │     │                     │
└─────────────────┘     └─────────────────────┘
```

## 安装

```bash
# 本地路径引用（推荐）
pip install -e utils/python/permission

# 或通过 uv 添加
uv add chongming-permission --source-path ../../utils/python/permission
```

## 快速开始

### 1. 初始化

在 Worker 启动时初始化权限缓存：

```python
from chongming_cache import ChongmingCache
from chongming_permission import init_permission_cache, register_permission_loader

# 创建并连接缓存
cache = ChongmingCache(logger, bucket="_permission_cache_")
await cache.connect()

# 初始化权限缓存（TTL 默认 300 秒）
init_permission_cache(cache, ttl=600)

# 注册权限加载函数（从数据库查询）
async def load_permissions_from_db(user_id: str) -> list[str]:
    async for session in get_db_session_slave():
        # ... 数据库查询逻辑 ...
        return permissions

register_permission_loader(load_permissions_from_db)
```

### 2. 使用装饰器

```python
from chongming_permission import require_permission

@app.handler("user.delete")
@require_permission("user.delete")
async def delete_user(input: UserDeleteInput) -> UserDeleteOutput:
    ...
```

### 3. 缓存失效

用户角色变更时主动清除缓存：

```python
from chongming_permission import invalidate_user_permissions

# 在角色分配/撤销后调用
await invalidate_user_permissions(str(user_id))
```

## API

| 函数 | 说明 |
|------|------|
| `init_permission_cache(cache, ttl=300)` | 初始化全局权限缓存 |
| `register_permission_loader(callback)` | 注册权限加载函数 |
| `require_permission(name)` | 权限校验装饰器 |
| `invalidate_user_permissions(user_id)` | 清除用户权限缓存 |
| `get_user_permissions(user_id)` | 获取用户权限列表 |

## 依赖

- Python >= 3.12
- chongming-cache

## 缓存键格式

- 桶名：`_permission_cache_`
- Key：`user_perms:{user_id}`
- Value：JSON 序列化的权限名称列表
