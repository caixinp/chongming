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

# ── 配置版本兼容性定义 ─────────────────────────────────────────────
# 版本格式: "MAJOR.MINOR" (语义化版本)
# - MAJOR 变更：不兼容，拒绝注册
# - MINOR 变更：兼容，仅记录警告
# 当前网关支持的 Worker 配置版本
_SUPPORTED_CONFIG_VERSIONS = {"1.0", "1.1", "2.0"}


def _parse_version(version: str) -> tuple[int, int]:
    """解析版本字符串为 (major, minor) 元组

    "1.0" -> (1, 0)
    "2.3" -> (2, 3)
    """
    try:
        parts = version.strip().split(".")
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        return (major, minor)
    except (ValueError, IndexError):
        return (0, 0)


def _check_config_version_compatibility(
    worker_version: str,
    worker_name: str,
    service_name: str,
) -> bool:
    """检查 Worker 配置版本与 Gateway 的兼容性

    规则：
    - Worker config_version 必须以 "MAJOR.MINOR" 格式定义
    - MAJOR 必须匹配（否则视为不兼容的 Breaking Change）
    - MINOR 差异仅记录警告

    返回：
    - True: 配置版本兼容，可以继续注册
    - False: 配置版本不兼容，应该拒绝注册
    """
    if not worker_version:
        logger.debug(
            "Service '%s' (%s): no config_version specified, assuming compatible",
            service_name, worker_name,
        )
        return True

    worker_major, worker_minor = _parse_version(worker_version)

    # 兼容性检查：至少有一个支持的 major 版本匹配
    for supported_ver in _SUPPORTED_CONFIG_VERSIONS:
        gw_major, gw_minor = _parse_version(supported_ver)
        if worker_major == gw_major:
            if worker_minor > gw_minor:
                logger.warning(
                    "Service '%s' (%s) config_version=%s > gateway supported %s. "
                    "Minor version ahead, registration will proceed but "
                    "some features may not be available.",
                    service_name, worker_name, worker_version, supported_ver,
                )
            return True

    # Major 版本不匹配 → 拒绝注册
    logger.error(
        "CONFIG VERSION MISMATCH: Service '%s' (%s) config_version=%s "
        "is NOT compatible with gateway supported versions=%s. "
        "Registration REJECTED. Worker must update its config_version "
        "to a supported major version.",
        service_name, worker_name, worker_version, _SUPPORTED_CONFIG_VERSIONS,
    )
    return False


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
        worker_name = data.get("name", service_name)
        router_prefix = data.get("router_prefix")
        tags = data.get("tags")
        items = data.get("items", [])
        config_version = data.get("config_version", "")
        # 提取 defaults（Worker 配置的 `defaults = { method = "POST", ... }`）
        defaults = data.get("defaults", {})

        # ── 配置版本兼容性检查 ────────────────────────────
        if not _check_config_version_compatibility(
            config_version, worker_name, service_name,
        ):
            logger.error(
                "REJECTED registration from service '%s' (%s): "
                "config_version=%s is incompatible with gateway. "
                "Worker needs to upgrade config_version.",
                service_name, worker_name, config_version,
            )
            return

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
            # ⚠️ 优先使用 item 自己的 method，否则 fallback 到 defaults，最后才是 "POST"
            method = item.get("method") or defaults.get("method", "POST")
            method = method.upper()
            path = item.get("path")
            summary = item.get("summary", f"Handler for {subject}")
            docstring = item.get("docstring", f"Handler for {subject}")
            params = item.get("params", [])
            ttl = item.get("ttl") or defaults.get("ttl", 30)
            timeout = item.get("timeout") or defaults.get("timeout", 2.0)
            response_model = item.get("response_model", None)
            is_internal = item.get("internal", False)

            auth_required = item.get("auth_required")
            if auth_required is None:
                auth_required = defaults.get("auth_required", False)
            assert isinstance(auth_required, bool)

            # 将 params 统一为字符串格式（兼容 dict/str 混合格式）
            normalized_params = []
            for p in (params or []):
                if isinstance(p, dict):
                    normalized_params.append(f"{p.get('name', 'unknown')}: {p.get('raw_type', 'str')}")
                else:
                    normalized_params.append(str(p))

            if not is_internal:
                try:
                    await self._dynamic_route_manager.add_dynamic_route(
                        subject=subject,
                        method=method,
                        path=path,
                        params=normalized_params,
                        summary=summary,
                        docstring=docstring,
                        router_prefix=router_prefix,
                        tags=tags,
                        timeout=timeout,
                        response_model=response_model,
                        auth_required=auth_required,
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
                "subject": subject,
                "path": path,
                "method": method,
                "ttl": ttl,
                "last_heartbeat": time.time(),
                "params": params,
                "router_prefix": router_prefix or _infer_prefix_from_path(path),
                "tags": tags or [router_prefix.strip("/")] if router_prefix else None,
                "internal": is_internal,
                "auth_required": auth_required,
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
        # 提取 defaults（Worker 配置的 `defaults = { method = "POST", ... }`）
        defaults = data.get("defaults", {})

        registry_updates: Dict[str, Optional[Dict[str, Any]]] = {}
        updated_count = 0
        recovered_count = 0

        for subject in subjects:
            existing_info = self._registry.get(subject)

            if existing_info:
                # 路由已存在 → 续期（并更新 worker 新上报的配置）
                is_internal = existing_info.get("internal", False)

                # 从 items_map 获取最新 item 信息（如果存在）
                latest_item = items_map.get(subject, {})
                if latest_item:
                    # ⚠️ 使用 worker 新上报的值更新 registry 中的配置
                    new_method = latest_item.get("method") or defaults.get("method", "POST")
                    new_method = new_method.upper()
                    new_path = latest_item.get("path", existing_info.get("path"))
                    new_ttl = latest_item.get("ttl") or defaults.get("ttl", 30)
                    new_timeout = latest_item.get("timeout") or defaults.get("timeout", 2.0)
                    new_params = latest_item.get("params", existing_info.get("params", []))
                    new_auth_required = latest_item.get("auth_required")
                    if new_auth_required is None:
                        new_auth_required = defaults.get("auth_required", False)

                    # 如果 method 或 path 发生变化，需要重建 HTTP 路由
                    old_method = existing_info.get("method", "POST").upper()
                    old_path = existing_info.get("path")
                    route_changed = (new_method != old_method) or (new_path != old_path)

                    if route_changed:
                        logger.info(
                            "Route %s changed via heartbeat: %s %s -> %s %s. Updating...",
                            subject, old_method, old_path, new_method, new_path,
                        )
                        # 将 params 统一为字符串格式
                        norm_params = []
                        for p in (new_params or []):
                            if isinstance(p, dict):
                                norm_params.append(f"{p.get('name', 'unknown')}: {p.get('raw_type', 'str')}")
                            else:
                                norm_params.append(str(p))
                        # 先删除旧路由
                        if not is_internal and old_path is not None:
                            old_router_prefix = existing_info.get("router_prefix") or ""
                            await self._dynamic_route_manager.remove_dynamic_route(
                                router_prefix=str(old_router_prefix),
                                path=str(old_path),
                                method=old_method,
                            )
                            # 再添加新路由
                            new_router_prefix = existing_info.get("router_prefix") or ""
                            await self._dynamic_route_manager.add_dynamic_route(
                                subject=subject,
                                method=new_method,
                                path=str(new_path),
                                params=norm_params,
                                summary=latest_item.get("summary", existing_info.get("summary", f"Handler for {subject}")),
                                docstring=latest_item.get("docstring", existing_info.get("docstring", f"Handler for {subject}")),
                                router_prefix=str(new_router_prefix),
                                tags=existing_info.get("tags"),
                                timeout=new_timeout,
                                response_model=latest_item.get("response_model", existing_info.get("response_model")),
                                auth_required=new_auth_required,
                            )

                # 检查路由是否真的在 app.routes 中
                if not is_internal and not self._registry.route_exists_in_app(
                    self._app, subject
                ):
                    logger.warning(
                        "Route %s exists in registry but missing from app.routes! "
                        "Attempting recovery via batch heartbeat...", subject,
                    )
                    # 从 registry 获取 params 并统一为字符串格式
                    recovery_params = existing_info.get("params", [])
                    norm_recovery_params = []
                    for p in (recovery_params or []):
                        if isinstance(p, dict):
                            norm_recovery_params.append(f"{p.get('name', 'unknown')}: {p.get('raw_type', 'str')}")
                        else:
                            norm_recovery_params.append(str(p))
                    await self._dynamic_route_manager.add_dynamic_route(
                        subject=subject,
                        method=existing_info.get("method", defaults.get("method", "POST")),
                        path=existing_info.get("path", "/"),
                        params=norm_recovery_params,
                        summary=existing_info.get("summary", f"Handler for {subject}"),
                        docstring=existing_info.get("docstring", f"Handler for {subject}"),
                        router_prefix=existing_info.get("router_prefix"),
                        tags=existing_info.get("tags"),
                        timeout=existing_info.get("timeout") or defaults.get("timeout", 2.0),
                        response_model=existing_info.get("response_model"),
                    )
                    recovered_count += 1

                # 合并更新（新上报的值覆盖旧的 registry 值）
                updated_info = {
                    **existing_info,
                    "last_heartbeat": time.time(),
                }
                if latest_item:
                    updated_info["method"] = latest_item.get("method") or defaults.get("method", "POST")
                    updated_info["method"] = updated_info["method"].upper()
                    updated_info["ttl"] = latest_item.get("ttl") or defaults.get("ttl", 30)
                    updated_info["timeout"] = latest_item.get("timeout") or defaults.get("timeout", 2.0)
                    if latest_item.get("path"):
                        updated_info["path"] = latest_item["path"]

                registry_updates[subject] = updated_info
                updated_count += 1

            elif subject in items_map:
                # 路由不存在但 items 提供了信息 → 自动重建
                item = items_map[subject]
                method = item.get("method") or defaults.get("method", "POST")
                method = method.upper()
                path = item.get("path")
                raw_params = item.get("params", [])
                # 将 params 统一为字符串格式
                norm_params = []
                for p in (raw_params or []):
                    if isinstance(p, dict):
                        norm_params.append(f"{p.get('name', 'unknown')}: {p.get('raw_type', 'str')}")
                    else:
                        norm_params.append(str(p))
                ttl = item.get("ttl") or defaults.get("ttl", 30)
                timeout = item.get("timeout") or defaults.get("timeout", 2.0)
                response_model = item.get("response_model", None)
                prefix = router_prefix or _infer_prefix_from_path(path) # type: ignore
                is_internal = item.get("internal", False)
                auth_required = item.get("auth_required")
                if auth_required is None:
                    auth_required = defaults.get("auth_required", False)
                assert isinstance(auth_required, bool)

                if not is_internal:
                    await self._dynamic_route_manager.add_dynamic_route(
                        subject=subject,
                        method=method,
                        path=path, # type: ignore
                        params=norm_params,
                        summary=item.get("summary", f"Handler for {subject}"),
                        docstring=item.get("docstring", f"Handler for {subject}"),
                        router_prefix=prefix,
                        tags=tags,
                        timeout=timeout,
                        response_model=response_model,
                        auth_required=auth_required,
                    )
                else:
                    logger.info(
                        "Batch heartbeat: internal subject '%s' (no HTTP route)",
                        subject,
                    )

                registry_updates[subject] = {
                    "subject": subject,
                    "path": path,
                    "method": method,
                    "ttl": ttl,
                    "last_heartbeat": time.time(),
                    "params": raw_params,
                    "router_prefix": prefix,
                    "tags": tags or [prefix.strip("/")] if prefix else None,
                    "internal": is_internal,
                    "auth_required": auth_required,
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
