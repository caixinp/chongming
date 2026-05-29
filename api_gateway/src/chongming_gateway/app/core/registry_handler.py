"""路由注册消息处理器

处理来自 worker 的注册/心跳/注销消息，按消息类型分发到不同的处理逻辑。
"""

import time
import logging
from typing import Dict, Any, Optional, List

from fastapi import FastAPI

from .dynamic_route import DynamicRoute
from .route_registry import RouteRegistry

logger = logging.getLogger("chongming.gateway.registry_handler")


def _infer_prefix_from_path(path: str) -> str:
    """从路径字符串推断 router_prefix"""
    parts = path.split("/")
    if len(parts) > 1 and parts[1]:
        return f"/{parts[1]}"
    return "/default"


def _validate_ttl_config(items: list[dict], cleanup_interval: int) -> None:
    """校验注册的 TTL 配置是否合理

    TTL 必须大于等于清理检查间隔，否则路由可能在两次清理检查之间过期
    或被清理时误删。
    """
    for item in items:
        ttl = item.get("ttl", 30)
        if ttl < cleanup_interval:
            raise ValueError(
                f"Item '{item.get('subject', 'unknown')}' has ttl={ttl}s, "
                f"but cleanup_interval={cleanup_interval}s. "
                f"TTL must be >= cleanup_interval to avoid premature route removal. "
                f"Recommended: ttl >= {cleanup_interval * 3}s"
            )
        if ttl < cleanup_interval * 3:
            subject = item.get("subject", "unknown")
            logger.warning(
                "'%s' ttl=%ds is low (cleanup_interval=%ds). "
                "A single cleanup cycle may delete the route. "
                "Recommended: ttl >= %ds",
                subject, ttl, cleanup_interval, cleanup_interval * 3,
            )


class RegistryHandler:
    """处理来自 worker 的注册/心跳/注销 NATS 消息

    使用方式（由 app/__init__.py 中的 NATS 消息回调创建并调用）:
        handler = RegistryHandler(registry, dynamic_route_manager, app)
        await handler.handle(data)
    """

    def __init__(
        self,
        registry: RouteRegistry,
        dynamic_route_manager: DynamicRoute,
        app: FastAPI,
        cleanup_interval: int = 10,
    ):
        self._registry = registry
        self._dynamic_route_manager = dynamic_route_manager
        self._app = app
        self._cleanup_interval = cleanup_interval

    async def handle(self, data: Dict[str, Any]) -> None:
        """根据消息类型分发处理"""
        msg_type = data.get("type")
        if msg_type == "register":
            await self._handle_register(data)
        elif msg_type == "heartbeat":
            await self._handle_heartbeat(data)
        elif msg_type == "deregister":
            await self._handle_deregister(data)
        else:
            logger.warning("Unknown message type: %s", msg_type)

    # ──────────────────────────────────────────────
    # 注册（register）
    # ──────────────────────────────────────────────

    async def _handle_register(self, data: Dict[str, Any]) -> None:
        """处理服务注册消息"""
        service_name = data.get("service", "unknown")
        router_prefix = data.get("router_prefix")
        tags = data.get("tags")
        items = data.get("items", [])
        _validate_ttl_config(items, self._cleanup_interval)

        # ⚠️ 关键修复：必须同时从 routes_registry 和 app.routes 中移除旧路由
        # 如果后面 add_dynamic_route 中途失败，batch_update 不会执行，
        # 就会导致 registry 中有旧记录但 app.routes 中缺少路由的不一致状态。
        subjects_to_remove = self._registry.find_by_prefix(router_prefix) # type: ignore

        # 先从 registry 和 KV 中删除旧路由，防止中途失败导致不一致
        if subjects_to_remove:
            old_updates = {subject: None for subject, _ in subjects_to_remove}
            await self._registry.batch_update(old_updates) # type: ignore

            # 再从 app.routes 中移除
            for subject, info in subjects_to_remove:
                await self._dynamic_route_manager.remove_dynamic_route(
                    router_prefix=info["router_prefix"],
                    path=info["path"],
                    method=info["method"],
                )
            logger.info(
                "Removed %d old routes for service '%s' (prefix=%s) before re-registration",
                len(subjects_to_remove), service_name, router_prefix,
            )

        # 注册新路由
        route_updates: Dict[str, Optional[Dict[str, Any]]] = {}
        failed_items: List[str] = []

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
            is_internal = item.get("internal", False)

            if not is_internal:
                try:
                    await self._dynamic_route_manager.add_dynamic_route(
                        subject=subject,
                        method=method,
                        path=path,
                        params=params,
                        summary=summary,
                        docstring=docstring,
                        router_prefix=router_prefix,
                        tags=tags,
                        timeout=timeout,
                        response_model=response_model,
                    )
                except Exception as e:
                    logger.error(
                        "Failed to register route '%s' for service '%s': %s",
                        subject, service_name, e,
                    )
                    failed_items.append(subject)
                    continue
            else:
                logger.info(
                    "Internal subject '%s' (no HTTP route, worker-to-worker only)",
                    subject,
                )

            route_updates[subject] = {
                "path": path,
                "method": method,
                "ttl": ttl,
                "last_heartbeat": time.time(),
                "params": params,
                "router_prefix": router_prefix or _infer_prefix_from_path(path),
                "tags": tags or [router_prefix.strip("/")] if router_prefix else None,
                "internal": is_internal,
            }

        # 提交注册结果
        if failed_items:
            logger.warning(
                "Service '%s' partially registered: %d/%d routes succeeded, "
                "%d failed: %s. Failed routes will be retried on next heartbeat.",
                service_name, len(route_updates), len(items),
                len(failed_items), failed_items,
            )

        if route_updates:
            await self._registry.batch_update(route_updates)
            logger.info(
                "Service '%s': %d routes committed (prefix=%s)",
                service_name, len(route_updates), router_prefix,
            )

    # ──────────────────────────────────────────────
    # 心跳（heartbeat）
    # ──────────────────────────────────────────────

    async def _handle_heartbeat(self, data: Dict[str, Any]) -> None:
        """处理心跳续期消息

        支持格式：
        - 单个心跳：{"subject": "xxx"}
        - 批量心跳：{"subjects": ["x", "y"], "items": [...]}
        """
        subjects = data.get("subjects")
        if subjects and isinstance(subjects, list):
            await self._handle_batch_heartbeat(data, subjects)
        else:
            subject = data.get("subject")
            if subject:
                await self._handle_single_heartbeat(subject)

    async def _handle_single_heartbeat(self, subject: str) -> None:
        """处理单个心跳续期"""
        current = self._registry.get(subject)
        if current:
            await self._registry.update(
                subject,
                {**current, "last_heartbeat": time.time()},
            )

    async def _handle_batch_heartbeat(
        self, data: Dict[str, Any], subjects: List[str]
    ) -> None:
        """处理批量心跳续期

        对于 registry 中存在的路由→续期 last_heartbeat
        对于 registry 中不存在但 items 提供了信息的路由→自动重建
        （网关重启后 registry 清空时使用 items 信息恢复）
        """
        items = data.get("items", [])
        items_map = {item.get("subject"): item for item in items if isinstance(item, dict)}
        router_prefix = data.get("router_prefix")
        tags = data.get("tags")

        registry_updates: Dict[str, Optional[Dict[str, Any]]] = {}
        updated_count = 0
        recovered_count = 0

        for subject in subjects:
            existing_info = self._registry.get(subject)

            if existing_info:
                # 路由已存在 → 续期
                is_internal = existing_info.get("internal", False)

                # 检查路由是否真的在 app.routes 中
                if not is_internal and not self._registry.route_exists_in_app(
                    self._app, subject
                ):
                    logger.warning(
                        "Route %s exists in registry but missing from app.routes! "
                        "Attempting recovery via batch heartbeat...", subject,
                    )
                    await self._dynamic_route_manager.add_dynamic_route(
                        subject=subject,
                        method=existing_info.get("method", "GET"),
                        path=existing_info.get("path", "/"),
                        params=existing_info.get("params", []),
                        summary=existing_info.get("summary", f"Handler for {subject}"),
                        docstring=existing_info.get("docstring", f"Handler for {subject}"),
                        router_prefix=existing_info.get("router_prefix"),
                        tags=existing_info.get("tags"),
                        timeout=existing_info.get("timeout", 2.0),
                        response_model=existing_info.get("response_model"),
                    )
                    recovered_count += 1

                registry_updates[subject] = {
                    **existing_info,
                    "last_heartbeat": time.time(),
                }
                updated_count += 1

            elif subject in items_map:
                # 路由不存在但 items 提供了信息 → 自动重建
                item = items_map[subject]
                method = item.get("method", "GET").upper()
                path = item.get("path")
                params = item.get("params", [])
                ttl = item.get("ttl", 30)
                timeout = item.get("timeout", 2.0)
                response_model = item.get("response_model", None)
                prefix = router_prefix or _infer_prefix_from_path(path) # type: ignore
                is_internal = item.get("internal", False)

                if not is_internal:
                    await self._dynamic_route_manager.add_dynamic_route(
                        subject=subject,
                        method=method,
                        path=path, # type: ignore
                        params=params,
                        summary=item.get("summary", f"Handler for {subject}"),
                        docstring=item.get("docstring", f"Handler for {subject}"),
                        router_prefix=prefix,
                        tags=tags,
                        timeout=timeout,
                        response_model=response_model,
                    )
                else:
                    logger.info(
                        "Batch heartbeat: internal subject '%s' (no HTTP route)",
                        subject,
                    )

                registry_updates[subject] = {
                    "path": path,
                    "method": method,
                    "ttl": ttl,
                    "last_heartbeat": time.time(),
                    "params": params,
                    "router_prefix": prefix,
                    "tags": tags or [prefix.strip("/")] if prefix else None,
                    "internal": is_internal,
                }
                logger.info(
                    "Auto-registered route for %s via batch heartbeat "
                    "(gateway restart recovery)", subject,
                )

            else:
                logger.warning(
                    "Batch heartbeat: unknown subject %s "
                    "(no items info available, worker should re-register)",
                    subject,
                )

        if registry_updates:
            await self._registry.batch_update(registry_updates)

        if updated_count > 0:
            logger.debug(
                "Batch heartbeat: renewed %d, recovered %d/%d routes",
                updated_count, recovered_count, len(subjects),
            )

    # ──────────────────────────────────────────────
    # 注销（deregister）
    # ──────────────────────────────────────────────

    async def _handle_deregister(self, data: Dict[str, Any]) -> None:
        """处理服务注销消息"""
        service_name = data.get("service", "unknown")
        router_prefix = data.get("router_prefix")

        async with self._registry.create_lock(
            f"__gw_deregister_{service_name}__", ttl=30,
        )(timeout=10.0):
            subjects_to_remove = self._registry.find_by_prefix(router_prefix) # type: ignore

            for subject, info in subjects_to_remove:
                await self._dynamic_route_manager.remove_dynamic_route(
                    router_prefix=info["router_prefix"],
                    path=info["path"],
                    method=info["method"],
                )
                logger.info("Removed route for %s (service: %s)", subject, service_name)

            remove_updates = {subject: None for subject, _ in subjects_to_remove}
            await self._registry.batch_update(remove_updates) # type: ignore
