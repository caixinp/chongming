"""
Worker 初始化与日志配置
========================

集中管理 WorkerLifespan 实例化、MinIO 日志持久化等全局初始化逻辑。
"""

import logging
from typing import Optional

from chongming_worker.worker_lifespan import WorkerLifespan
from chongming_config import load_config
from chongming_cache import ChongmingCache
from chongming_permission import init_permission_cache, register_permission_loader

from .listeners import listen_gateway_config_changes, stop_listener
from .database_models import *
from .utils.snowflake import snowflake_generator
from .utils.rbac import seed_default_rbac, seed_default_admin_user, subscribe_routes_permission_sync


logger = logging.getLogger("chongming.worker.user_auth")

# ── 全局 Worker 应用实例 ──────────────────────────────────────────
# 所有 handler 模块通过 from app.bootstrap import app 引入
app = WorkerLifespan("config.toml")

# Snowflake 节点注册专用缓存连接（_worker_id_ 桶）
_snowflake_cache: Optional[ChongmingCache] = None


def setup_minio_logging() -> None:
    """初始化 MinIO 日志持久化（非阻塞，失败不影响 Worker 启动）"""
    try:
        from chongming_logging.minio_logger import setup_worker_minio_logging

        _config = load_config("config.toml")
        _minio_cfg = _config.get("logging", {}).get("minio", {})
        if _minio_cfg.get("enabled", True):
            setup_worker_minio_logging(
                worker_name=_config["worker"]["name"], # type: ignore
                endpoint=_minio_cfg.get("endpoint", "localhost:9000"),
                bucket=_minio_cfg.get("bucket", "chongming-logs"),
                retention_days=int(_minio_cfg.get("retention_days", 30)),
                level=logging.INFO,
            )
            logger.info(
                "MinIO logging initialized: worker/%s -> %s (retention: %sd)",
                _config["worker"]["name"], # type: ignore
                _minio_cfg.get("bucket", "chongming-logs"),
                _minio_cfg.get("retention_days", 30),
            )
    except ImportError:
        logger.debug("minio package not installed, MinIO logging disabled")
    except Exception as e:
        logger.warning("Failed to initialize MinIO logging: %s", e)


async def _init_snowflake():
    """初始化 Snowflake 生成器（通过 NATS KV 注册节点 ID）"""
    global _snowflake_cache

    try:
        _snowflake_cache = ChongmingCache(logger, bucket="_worker_id_")
        await _snowflake_cache.connect()

        _config = load_config("config.toml")
        worker_name = _config.get("worker", {}).get("name", "user_auth")

        await snowflake_generator.register(
            app_name=worker_name,
            cache=_snowflake_cache,
        )
        logger.info(
            "Snowflake 初始化完成: worker_id=%d, config=%s",
            snowflake_generator.worker_id,
            snowflake_generator.config,
        )
    except Exception as e:
        logger.error("Snowflake 初始化失败: %s", e, exc_info=True)
        raise


async def _cleanup_snowflake():
    """清理 Snowflake 节点注册（释放节点 ID）"""
    global _snowflake_cache

    await snowflake_generator.unregister(cache=_snowflake_cache)

    if _snowflake_cache is not None:
        await _snowflake_cache.close()
        _snowflake_cache = None
        logger.info("Snowflake 节点注册缓存已关闭")


async def on_start():
    """Worker 启动时的初始化逻辑"""
    from .listeners import get_db_session_master

    setup_minio_logging()

    # 必须先初始化 Snowflake（handler 依赖它生成 ID）
    await _init_snowflake()

    await listen_gateway_config_changes()

    # 从网关 KV 初始化 RBAC 种子数据
    routes_kv_cache: Optional[ChongmingCache] = None
    try:
        routes_kv_cache = ChongmingCache(logger, bucket="_gw_routes_")
        await routes_kv_cache.connect()
        async for session in get_db_session_master():
            await seed_default_rbac(session, routes_kv_cache)
            await seed_default_admin_user(session)
    except Exception as e:
        logger.warning("RBAC seed data initialization skipped: %s", e)

    # 订阅网关路由变更事件驱动权限同步
    try:
        from .listeners import get_db_session_master as _session_getter
        await subscribe_routes_permission_sync(app, _session_getter)
    except Exception as e:
        logger.warning("Runtime permission sync subscription skipped: %s", e)

    # 初始化权限缓存
    try:
        permission_cache = ChongmingCache(logger, bucket="_permission_cache_")
        await permission_cache.connect()
        init_permission_cache(permission_cache, ttl=600)
        register_permission_loader(load_permissions_from_db)
        logger.info("🔐 Permission cache initialized")
    except Exception as e:
        logger.warning("Permission cache initialization skipped: %s", e)


async def load_permissions_from_db(user_id: str) -> list[str]:
    """权限加载函数：从数据库查询用户权限列表

    兼容 user_auth Worker 的主从复制架构，使用从库查询。

    Args:
        user_id: 用户 ID（字符串形式）

    Returns:
        权限名称列表
    """
    from app.database_models import User, Permission
    from sqlmodel import select
    from .listeners import get_db_session_slave

    async for session in get_db_session_slave():
        user = await session.get(User, int(user_id))
        if user is None:
            return []
        if user.is_superuser:
            stmt = select(Permission.name)
            result = await session.execute(stmt)
            return list(result.scalars().all())

        # 通过 UserRole -> RolePermission -> Permission 链获取
        from sqlalchemy import text
        sql = text("""
            SELECT DISTINCT p.name
            FROM permission p
            JOIN role_permission rp ON rp.permission_id = p.id
            JOIN user_role ur ON ur.role_id = rp.role_id
            WHERE ur.user_id = :user_id
        """)
        result = await session.execute(sql, {"user_id": int(user_id)})
        return [row[0] for row in result.all()]

    return []


async def on_stop():
    """Worker 关闭前的清理逻辑"""
    await stop_listener()
    await _cleanup_snowflake()


app.on_start(on_start)
app.on_stop(on_stop)
setup_minio_logging()
