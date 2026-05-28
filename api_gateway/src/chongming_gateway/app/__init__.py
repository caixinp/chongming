import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
import nats
import asyncio
import json
import time
from typing import Dict, Any, Optional

from .core.nats_client import get_nats_client
from .core.dynamic_route import DynamicRoute
from chongming_config import load_gateway_config
from chongming_cache import ChongmingCache
from chongming_lock import MutexLock, LockFactory

logger = logging.getLogger("chongming.gateway")
gateway_config = load_gateway_config("config.toml")
routes_registry: Dict[str, Dict[str, Any]] = {}

# 清理检查间隔（秒），可从配置读取，默认 10 秒
_cleanup_interval: int = 10

# 全局锁工厂实例（lifespan 中初始化）
_lock_factory: Optional[LockFactory] = None


def _infer_prefix_from_path(path: str) -> str:
    parts = path.split('/')
    if len(parts) > 1 and parts[1]:
        return f"/{parts[1]}"
    return "/default"


def _validate_ttl_config(items: list[dict]) -> None:
    """校验注册的 TTL 配置是否合理：TTL 必须大于清理检查间隔的 2 倍，否则路由可能在
    两次清理检查之间过期仍未被清理，或者因清理过于频繁而导致路由被误清理。"""
    for item in items:
        ttl = item.get("ttl", 30)
        if ttl < _cleanup_interval:
            raise ValueError(
                f"Item '{item.get('subject', 'unknown')}' has ttl={ttl}s, "
                f"but cleanup_interval={_cleanup_interval}s. "
                f"TTL must be >= cleanup_interval to avoid premature route removal. "
                f"Recommended: ttl >= {_cleanup_interval * 3}s"
            )
        if ttl < _cleanup_interval * 3:
            subject = item.get("subject", "unknown")
            logger.warning(
                "'%s' ttl=%ds is low (cleanup_interval=%ds). "
                "A single cleanup cycle may delete the route. "
                "Recommended: ttl >= %ds",
                subject, ttl, _cleanup_interval, _cleanup_interval * 3,
            )


async def _routes_registry_update(subject: str, info: Optional[Dict[str, Any]]) -> None:
    """带分布式锁的 routes_registry 更新操作

    使用 MutexLock 保护 routes_registry 的并发修改，防止多网关实例
    同时处理注册/心跳/清理时产生竞态条件。
    """
    global routes_registry
    lock_name = "__gw_routes_registry__"
    async with MutexLock(_lock_factory._cache, lock_name, ttl=10)(timeout=5.0): # type: ignore
        if info is not None:
            routes_registry[subject] = info
        else:
            routes_registry.pop(subject, None)


async def _routes_registry_batch_update(updates: Dict[str, Optional[Dict[str, Any]]]) -> None:
    """批量更新 routes_registry（带分布式锁）"""
    global routes_registry
    lock_name = "__gw_routes_registry__"
    async with MutexLock(_lock_factory._cache, lock_name, ttl=10)(timeout=5.0): # type: ignore
        for subject, info in updates.items():
            if info is not None:
                routes_registry[subject] = info
            else:
                routes_registry.pop(subject, None)


async def registry_listener(msg: nats.aio.client.Msg, app: FastAPI): # type: ignore
    """处理注册和心跳消息

    从 app.state.dynamic_route_manager 获取单例 DynamicRoute 实例。

    支持的消息类型：
    - type=register: 注册新服务（首次启动或 NATS 重连后发送）
    - type=heartbeat (带 subject): 单个路由心跳续期
    - type=heartbeat (带 subjects + items): 批量路由心跳续期，路由不存在时自动重建
      （替代原定期 type=register 触发路由删除重建的不稳定行为）
      即使 gateway 重启后 routes_registry 清空，也能通过 items 信息自动恢复路由
    - type=deregister: 服务注销

    分布式锁保护：
    - 同一个 worker 的路由注册操作使用分布式锁，防止多网关实例同时处理同一 worker
      的注册消息导致路由重复创建或状态不一致
    """
    dynamic_route_manager: DynamicRoute = app.state.dynamic_route_manager

    try:
        data = json.loads(msg.data.decode())
        msg_type = data.get("type")

        if msg_type == "register":
            # 使用分布式锁保护同一 worker 的路由注册过程
            service_name = data.get("service", "unknown")
            # 锁名称使用服务名，确保同一个服务的路由注册在不同 gateway 实例间互斥
            async with MutexLock(_lock_factory._cache, f"__gw_register_{service_name}__", ttl=30)(timeout=10.0): # type: ignore
                router_prefix = data.get("router_prefix")
                tags = data.get("tags")
                items = data.get("items", [])
                # 校验 TTL 配置
                _validate_ttl_config(items)

                # 先批量移除该 service 的所有已有路由（防止重复）
                subjects_to_remove = []
                for subject, info in list(routes_registry.items()):
                    if info.get("router_prefix") == router_prefix:
                        subjects_to_remove.append((subject, info))
                for subject, info in subjects_to_remove:
                    await dynamic_route_manager.remove_dynamic_route(
                        info["router_prefix"], info["path"], info["method"]
                    )

                # 注册新路由
                route_updates = {}
                for item in items:
                    subject = item.get("subject")
                    method = item.get("method", "GET").upper()
                    path = item.get("path")
                    summary = item.get("summary", f"Handler for {subject}")
                    docstring = item.get("docstring", f"Handler for {subject}")
                    params = item.get("params", [])
                    ttl = item.get("ttl", 30)
                    timeout = item.get("timeout", 2.0)
                    response_model = item.get("response_model", None)
                    await dynamic_route_manager.add_dynamic_route(
                        subject,
                        method,
                        path,
                        params,
                        summary=summary,
                        docstring=docstring,
                        router_prefix=router_prefix,
                        tags=tags,
                        timeout=timeout,
                        response_model=response_model,
                    )
                    route_updates[subject] = {
                        "path": path,
                        "method": method,
                        "ttl": ttl,
                        "last_heartbeat": time.time(),
                        "params": params,
                        "router_prefix": router_prefix or _infer_prefix_from_path(path),
                        "tags": tags or [router_prefix.strip("/")] if router_prefix else None,
                    }

                # 批量更新 routes_registry（同样带分布式锁）
                await _routes_registry_batch_update(route_updates)

        elif msg_type == "heartbeat":
            # 检查是否是批量心跳（带 subjects + items 字段）
            subjects = data.get("subjects")
            items = data.get("items")
            if subjects and isinstance(subjects, list):
                # 批量心跳续期：一次性续期多个路由
                updated_count = 0
                registered_count = 0

                # 构建 subject -> item 的映射，用于路由不存在时自动注册
                items_map = {}
                if items and isinstance(items, list):
                    for item in items:
                        items_map[item.get("subject")] = item

                # 收集需要更新的路由
                registry_updates = {}
                for subject in subjects:
                    if subject in routes_registry:
                        registry_updates[subject] = {**routes_registry[subject], "last_heartbeat": time.time()}
                        updated_count += 1
                    elif subject in items_map:
                        # 路由不存在但 items 中有完整信息 → 自动重建路由（gateway 重启场景）
                        item = items_map[subject]
                        method = item.get("method", "GET").upper()
                        path = item.get("path")
                        params = item.get("params", [])
                        ttl = item.get("ttl", 30)
                        timeout = item.get("timeout", 2.0)
                        response_model = item.get("response_model", None)
                        router_prefix = data.get("router_prefix")
                        tags = data.get("tags")

                        # 使用分布式锁保护自动重建过程
                        async with MutexLock(_lock_factory._cache, f"__gw_autoreg_{subject}__", ttl=30)(timeout=10.0): # type: ignore
                            # 双重检查：可能已经被其他 gateway 实例重建了
                            if subject not in routes_registry:
                                await dynamic_route_manager.add_dynamic_route(
                                    subject,
                                    method,
                                    path,
                                    params,
                                    summary=item.get("summary", f"Handler for {subject}"),
                                    docstring=item.get("docstring", f"Handler for {subject}"),
                                    router_prefix=router_prefix,
                                    tags=tags,
                                    timeout=timeout,
                                    response_model=response_model,
                                )

                        registry_updates[subject] = {
                            "path": path,
                            "method": method,
                            "ttl": ttl,
                            "last_heartbeat": time.time(),
                            "params": params,
                            "router_prefix": router_prefix or _infer_prefix_from_path(path),
                            "tags": tags or [router_prefix.strip("/")] if router_prefix else None,
                        }
                        registered_count += 1
                        logger.info("Auto-registered route for %s via batch heartbeat (gateway restart recovery)", subject)
                    else:
                        logger.warning(
                            "Batch heartbeat: unknown subject %s "
                            "(no items info available, worker should re-register)",
                            subject
                        )

                # 批量更新 registry
                if registry_updates:
                    await _routes_registry_batch_update(registry_updates)

                if updated_count > 0:
                    logger.debug("Batch heartbeat: renewed %d/%d routes", updated_count, len(subjects))
            else:
                # 单个心跳更新（兼容旧的心跳格式）
                subject = data.get("subject")
                if subject:
                    await _routes_registry_update(
                        subject,
                        {**routes_registry.get(subject, {}), "last_heartbeat": time.time()}
                    )

        elif msg_type == "deregister":
            # 服务注销：使用分布式锁保护
            service_name = data.get("service", "unknown")
            router_prefix = data.get("router_prefix")

            async with MutexLock(_lock_factory._cache, f"__gw_deregister_{service_name}__", ttl=30)(timeout=10.0): # type: ignore
                # 收集该 service 的所有路由
                subjects_to_remove = []
                for subject, info in list(routes_registry.items()):
                    if info.get("router_prefix") == router_prefix:
                        subjects_to_remove.append((subject, info))

                # 先移除以释放路由
                for subject, info in subjects_to_remove:
                    await dynamic_route_manager.remove_dynamic_route(
                        info["router_prefix"], info["path"], info["method"]
                    )
                    logger.info("Removed route for %s (service: %s)", subject, service_name)

                # 批量从 registry 中删除
                remove_updates = {subject: None for subject, _ in subjects_to_remove}
                await _routes_registry_batch_update(remove_updates) # type: ignore

    except Exception as e:
        logger.error("Error processing registry message: %s", e)


async def cleanup_expired_routes(app: FastAPI):
    """后台任务：定期清理超时未收到心跳的路由

    使用分布式锁保护清理过程，防止多网关实例同时清理产生竞态条件。
    """
    while True:
        await asyncio.sleep(_cleanup_interval)
        now = time.time()

        # 在分布式锁保护下检查和清理
        lock_name = "__gw_route_cleanup__"
        try:
            async with MutexLock(_lock_factory._cache, lock_name, ttl=_cleanup_interval * 2)(timeout=_cleanup_interval): # type: ignore
                expired = []
                for subject, info in list(routes_registry.items()):
                    if now - info["last_heartbeat"] > info["ttl"]:
                        expired.append(subject)

                for subject in expired:
                    info = routes_registry.pop(subject, None)
                    if info:
                        dynamic_route_manager: DynamicRoute = app.state.dynamic_route_manager
                        await dynamic_route_manager.remove_dynamic_route(
                            info["router_prefix"], info["path"], info["method"]
                        )
                        logger.info("Route expired for %s (no heartbeat within %ds)", subject, info["ttl"])

                if expired:
                    logger.info("Cleanup cycle: removed %d expired routes", len(expired))
        except Exception as e:
            logger.debug("Cleanup lock not acquired (another gateway instance may be handling it): %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _cleanup_interval, _lock_factory

    # 连接 NATS
    nc = await get_nats_client()
    logger.info("FastAPI gateway connected to NATS cluster")

    # 初始化 ChongmingCache（用于分布式锁）
    cache = ChongmingCache(logger, bucket="_gw_locks_")
    await cache.__aenter__()
    _lock_factory = LockFactory(cache)
    logger.info("Lock factory initialized for distributed locks")

    # 创建 DynamicRoute 单例并挂载到 app.state
    app.state.dynamic_route_manager = DynamicRoute(app)

    # 读取清理间隔配置（如果有）
    try:
        cleanup_config = gateway_config.get("cleanup", {})
        _cleanup_interval = int(cleanup_config.get("interval", 10))
        logger.info("Cleanup interval: %ds", _cleanup_interval)
    except Exception as e:
        logger.warning("Could not load cleanup config, using default interval=%ds: %s", _cleanup_interval, e)

    # 定义订阅回调函数
    async def on_registry_msg(msg):
        await registry_listener(msg, app)

    # 订阅主题
    sub = await nc.subscribe("service.registry", cb=on_registry_msg)
    logger.info("Subscribed to service.registry")

    # 启动清理任务
    cleanup_task = asyncio.create_task(cleanup_expired_routes(app))

    yield

    # 清理
    cleanup_task.cancel()
    await sub.unsubscribe()
    if _lock_factory:
        await _lock_factory._cache.__aexit__(None, None, None)
    await nc.close()

prefix = gateway_config["default"]["prefix"]
name = gateway_config["default"]["name"]
app = FastAPI(
    lifespan=lifespan,
    root_path=prefix,
    title=f"{name} API Gateway",
    description="Dynamic API Gateway powered by FastAPI and NATS",
    version="1.0.0"
)


@app.get("/health")
async def health():
    return {"status": "ok", "registered_services": list(routes_registry.keys())}


@app.get("/debug/routes")
async def debug_routes():
    """调试端点：列出所有已注册的路由"""
    dynamic_route_manager: DynamicRoute = app.state.dynamic_route_manager
    return {
        "routes": dynamic_route_manager.get_registered_routes(),
        "router_prefixes": dynamic_route_manager.get_registered_prefixes(),
        "registry_lock_type": "chongming_lock.MutexLock (distributed)",
        "total_registered": len(routes_registry),
    }
