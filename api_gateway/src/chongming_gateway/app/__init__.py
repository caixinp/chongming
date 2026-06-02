"""FastAPI Application Bootstrap

创建 FastAPI 应用实例，配置生命周期管理（lifespan），
包括 NATS 连接、分布式锁初始化、KV 路由恢复、
NATS 消息订阅和后台过期清理任务等。

职责划分：
- app/__init__.py:          应用启动配置和生命周期编排
- app/core/nats_client.py:  NATS 连接管理
- app/core/dynamic_route.py: FastAPI 动态路由增删 + 类型解析 + 响应模型
- app/core/route_store.py:   NATS KV 持久化存储
- app/core/route_registry.py: 路由注册表管理器（内存 + 锁 + KV 同步 + 清理 + 恢复）
- app/core/registry_handler.py: 注册/心跳/注销消息处理
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import nats
import asyncio
import json
from typing import Dict, Any, Optional

from .core.nats_client import get_nats_client
from .core.dynamic_route import DynamicRoute
from .core.route_store import RouteKVStore
from .core.route_registry import RouteRegistry
from .core.registry_handler import RegistryHandler
from .core.gateway_config_store import GatewayConfigStore
from chongming_jwt import JWTAuth
from chongming_config import load_gateway_config
from chongming_cache import ChongmingCache
from chongming_lock import LockFactory
from chongming_logging import setup_gateway_minio_logging

logger = logging.getLogger("chongming.gateway")

gateway_config = load_gateway_config("config.toml")

# ── 全局单例（lifespan 中初始化） ─────────────────────────
_registry: Optional[RouteRegistry] = None
_lock_factory: Optional[LockFactory] = None
_route_kv_store: Optional[RouteKVStore] = None
_cleanup_interval: int = 10
_gateway_config_store: Optional[GatewayConfigStore] = None


def _setup_minio_logging():
    """根据配置初始化 MinIO 日志持久化"""
    try:
        minio_cfg = gateway_config.get("logging", {}).get("minio", {})
        if not minio_cfg.get("enabled", True):
            logger.info("MinIO logging is disabled in config")
            return

        gateway_name = gateway_config["default"]["name"] # type: ignore
        setup_gateway_minio_logging(
            gateway_name=gateway_name,
            endpoint=minio_cfg.get("endpoint", "localhost:9000"),
            bucket=minio_cfg.get("bucket", "chongming-logs"),
            retention_days=int(minio_cfg.get("retention_days", 30)),
            level=logging.INFO,
        )
        logger.info(
            "MinIO logging initialized: gateway/%s -> %s (retention: %sd)",
            gateway_name,
            minio_cfg.get("bucket", "chongming-logs"),
            minio_cfg.get("retention_days", 30),
        )
    except ImportError:
        logger.debug("chongming_logging.minio_logger not available (minio package not installed)")
    except Exception as e:
        logger.warning("Failed to initialize MinIO logging: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期管理

    启动时:
    1. 初始化 MinIO 日志持久化
    2. JWT 认证初始化
    3. 连接 NATS 集群
    4. 初始化分布式锁工厂
    5. 创建 DynamicRoute 管理器
    6. 读取清理配置
    7. 初始化 KV 路由存储
    8. RouteRegistry（内存 + 锁 + KV 同步）
    9. 从 KV 恢复路由
    10. RegistryHandler（消息分发）
    11. 后台过期清理任务
    12. 网关配置存入 NATS KV（供所有 worker 读取）

    关闭时:
    1. 取消清理任务
    2. 取消 NATS 订阅
    3. 关闭网关配置存储
    4. 关闭缓存/锁资源
    5. 关闭 KV 路由存储
    6. 关闭 NATS 连接
    """
    global _registry, _lock_factory, _route_kv_store, _cleanup_interval, _gateway_config_store

    # ── 1. MinIO 日志持久化 ──────────────────────────────
    _setup_minio_logging()

    # ── 2. JWT 认证初始化 ────────────────────────────────
    jwt_config = gateway_config.get("jwt", {})
    jwt_auth = JWTAuth(jwt_config) # type: ignore
    app.state.jwt_auth = jwt_auth
    if jwt_auth.enabled:
        logger.info(
            "JWT auth initialized (algorithm=%s, issuer=%s, audience=%s)",
            jwt_auth.algorithm, jwt_auth.issuer, jwt_auth.audience,
        )
    else:
        logger.info("JWT auth is disabled")

    # ── 3. NATS 连接 ─────────────────────────────────────
    nc = await get_nats_client()
    logger.info("FastAPI gateway connected to NATS cluster")

    # ── 4. 分布式锁工厂 ──────────────────────────────────
    cache = ChongmingCache(logger, bucket="_gw_locks_")
    await cache.__aenter__()
    _lock_factory = LockFactory(cache)
    logger.info("Lock factory initialized for distributed locks")

    # ── 5. DynamicRoute 管理器 ────────────────────────────
    dynamic_route_manager = DynamicRoute(app)
    app.state.dynamic_route_manager = dynamic_route_manager

    # ── 6. 清理配置 ──────────────────────────────────────
    try:
        cleanup_config = gateway_config.get("cleanup", {})
        _cleanup_interval = int(cleanup_config.get("interval", 10))
        logger.info("Cleanup interval: %ds", _cleanup_interval)
    except Exception as e:
        logger.warning(
            "Could not load cleanup config, using default interval=%ds: %s",
            _cleanup_interval, e,
        )

    # ── 7. KV 路由存储 ──────────────────────────────────
    route_cache = ChongmingCache(logger, bucket="_gw_routes_")
    await route_cache.__aenter__()
    _route_kv_store = RouteKVStore(route_cache)
    logger.info("Route KV store initialized (bucket: _gw_routes_)")

    # ── 8. RouteRegistry（内存 + 锁 + KV 同步） ─────────
    _registry = RouteRegistry(
        dynamic_route_manager=dynamic_route_manager,
        lock_factory=_lock_factory,
        route_kv_store=_route_kv_store,
        cleanup_interval=_cleanup_interval,
    )
    app.state.route_registry = _registry

    # ── 9. 从 KV 恢复路由 ────────────────────────────────
    restored = await _registry.restore_from_kv()
    if restored > 0:
        logger.info("Gateway startup: restored %d routes from KV", restored)

    # ── 10. RegistryHandler（消息分发） ───────────────────
    registry_handler = RegistryHandler(
        registry=_registry,
        dynamic_route_manager=dynamic_route_manager,
        app=app,
        cleanup_interval=_cleanup_interval,
    )

    async def on_registry_msg(msg):
        """NATS 消息回调：将消息反序列化后交给 RegistryHandler 处理"""
        try:
            data = json.loads(msg.data.decode())
            await registry_handler.handle(data)
        except json.JSONDecodeError as e:
            logger.error("Invalid registry message (not valid JSON): %s", e)
        except Exception as e:
            logger.error("Error processing registry message: %s", e)

    sub = await nc.subscribe("service.registry", cb=on_registry_msg)
    logger.info("Subscribed to service.registry")

    # ── 11. 后台过期清理任务 ─────────────────────────────
    async def cleanup_loop():
        while True:
            await asyncio.sleep(_cleanup_interval)
            if _registry is not None:
                await _registry.cleanup_expired()

    cleanup_task = asyncio.create_task(cleanup_loop())

    # ── 12. 网关配置存入 NATS KV（供所有 worker 读取） ──
    _gateway_config_store = GatewayConfigStore(dict(gateway_config), logger)
    await _gateway_config_store.start()

    # ── 应用运行中 ──────────────────────────────────────
    yield

    # ── 关闭清理 ─────────────────────────────────────────
    cleanup_task.cancel()
    await sub.unsubscribe()
    if _gateway_config_store:
        await _gateway_config_store.stop()
    if _lock_factory:
        await _lock_factory._cache.__aexit__(None, None, None)
    if _route_kv_store:
        await _route_kv_store._cache.__aexit__(None, None, None)
    await nc.close()
    logger.info("Gateway shutdown complete")


# ── FastAPI 应用实例 ──────────────────────────────────────
prefix = gateway_config["default"]["prefix"] # type: ignore
name = gateway_config["default"]["name"] # type: ignore

# OpenAPI Bearer token 安全方案（使 /docs 显示 Authorize 按钮）
security_scheme = HTTPBearer(
    scheme_name="JWT",
    description="Enter your JWT token (Bearer <token>)",
    auto_error=False,
)

app = FastAPI(
    lifespan=lifespan,
    root_path=prefix,
    title=f"{name} API Gateway",
    description="Dynamic API Gateway powered by FastAPI and NATS",
    version="1.0.0",
    swagger_ui_parameters={
        "bearerFormat": "JWT",
        "scheme": "bearer",
    },
)


# ── 注册 OpenAPI 全局安全方案（使 /docs 显示 Authorize 按钮） ─
def custom_openapi():
    """自定义 OpenAPI schema，注入 JWT Bearer 安全方案"""
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = app._original_openapi()
    # 注入 securitySchemes 组件
    openapi_schema.setdefault("components", {}).setdefault("securitySchemes", {})
    openapi_schema["components"]["securitySchemes"]["JWT"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "Enter your JWT token (Bearer <token>)",
    }
    # 全局安全要求（仅标记，不强制 /health 等端点，由 jwt_auth 的白名单控制）
    openapi_schema.setdefault("security", [{"JWT": []}])
    app.openapi_schema = openapi_schema
    return app.openapi_schema


# 保存原始 openapi 方法并替换
app._original_openapi = app.openapi
app.openapi = custom_openapi


# ── 健康检查端点 ──────────────────────────────────────────
@app.get("/health")
async def health():
    """健康检查"""
    registered = list(_registry.all.keys()) if _registry else []
    return {"status": "ok", "registered_services": registered}


# ── 调试端点 ──────────────────────────────────────────────
@app.get("/debug/routes")
async def debug_routes():
    """调试端点：列出所有已注册的路由"""
    dynamic_route_manager: DynamicRoute = app.state.dynamic_route_manager
    return {
        "routes": dynamic_route_manager.get_registered_routes(),
        "router_prefixes": dynamic_route_manager.get_registered_prefixes(),
        "registry_lock_type": "chongming_lock.MutexLock (distributed)",
        "total_registered": _registry.count if _registry else 0,
    }


# ── 调试端点：查看网关配置 ────────────────────────────────
@app.get("/debug/config")
async def debug_config():
    """调试端点：查看 NATS KV 中存储的网关配置"""
    from .core.gateway_config_store import GatewayConfigStore
    gw_config = await GatewayConfigStore.get_config(logger)
    if gw_config:
        return {"status": "ok", "config": gw_config}
    return {"status": "error", "message": "Gateway config not found in NATS KV"}
