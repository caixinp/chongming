"""路由注册表管理器

封装 routes_registry 的所有操作，包括：
- CRUD（增删改查）
- 分布式锁保护（多网关实例并发安全）
- NATS KV 持久化同步
- 过期路由清理
- 网关重启时从 KV 恢复路由
"""

import time
import logging
from typing import Dict, Any, Optional, List, Tuple
from collections import defaultdict

from fastapi import FastAPI

from .dynamic_route import DynamicRoute
from .route_store import RouteKVStore
from chongming_lock import MutexLock, LockFactory

logger = logging.getLogger("chongming.gateway.registry")

# 分布式互斥锁的默认配置
_LOCK_TTL = 10          # 锁持有时间（秒）
_LOCK_TIMEOUT = 5.0     # 获取锁的超时时间（秒）
_CLEANUP_LOCK_TTL_MULTIPLIER = 2  # 清理锁 TTL = 清理间隔 * 此值


class RouteRegistry:
    """路由注册表管理器（单例模式，由 lifespan 创建后注入到 app.state）

    职责：
    - 管理内存中的 routes_registry 字典
    - 所有修改操作都通过分布式锁保护
    - 内存修改同步写入 NATS KV 持久化存储
    - 定期清理过期路由（心跳超时的路由）
    - 网关重启时从 KV 恢复路由
    """

    def __init__(
        self,
        dynamic_route_manager: DynamicRoute,
        lock_factory: LockFactory,
        route_kv_store: RouteKVStore,
        cleanup_interval: int = 10,
    ):
        self._routes: Dict[str, Dict[str, Any]] = {}
        self._dynamic_route_manager = dynamic_route_manager
        self._lock_factory = lock_factory
        self._kv_store = route_kv_store
        self._cleanup_interval = cleanup_interval

    # ──────────────────────────────────────────────
    # 公开属性
    # ──────────────────────────────────────────────

    @property
    def all(self) -> Dict[str, Dict[str, Any]]:
        """返回 routes_registry 的只读快照"""
        return dict(self._routes)

    @property
    def count(self) -> int:
        return len(self._routes)

    def get(self, subject: str) -> Optional[Dict[str, Any]]:
        return self._routes.get(subject)

    def __contains__(self, subject: str) -> bool:
        return subject in self._routes

    # ──────────────────────────────────────────────
    # 单条更新（带分布式锁 + KV 同步）
    # ──────────────────────────────────────────────

    async def update(
        self, subject: str, info: Optional[Dict[str, Any]]
    ) -> None:
        """更新或删除单条路由记录

        - info 不为 None：更新/新增
        - info 为 None：删除
        """
        async with MutexLock(
            self._lock_factory._cache,  # type: ignore
            "__gw_routes_registry__",
            ttl=_LOCK_TTL,
        )(timeout=_LOCK_TIMEOUT):
            if info is not None:
                self._routes[subject] = info
            else:
                self._routes.pop(subject, None)

        # 同步到 KV
        if info is not None:
            await self._kv_store.save(subject, info)
        else:
            await self._kv_store.delete(subject)

    # ──────────────────────────────────────────────
    # 批量更新（带分布式锁 + KV 同步）
    # ──────────────────────────────────────────────

    async def batch_update(
        self, updates: Dict[str, Optional[Dict[str, Any]]]
    ) -> None:
        """批量更新/删除路由记录

        updates: {subject: info_or_None, ...}
        """
        async with MutexLock(
            self._lock_factory._cache,  # type: ignore
            "__gw_routes_registry__",
            ttl=_LOCK_TTL,
        )(timeout=_LOCK_TIMEOUT):
            for subject, info in updates.items():
                if info is not None:
                    self._routes[subject] = info
                else:
                    self._routes.pop(subject, None)

        # 同步到 KV
        await self._kv_store.save_batch(updates)

    # ──────────────────────────────────────────────
    # 按前缀查询
    # ──────────────────────────────────────────────

    def find_by_prefix(self, router_prefix: str) -> List[Tuple[str, Dict[str, Any]]]:
        """根据 router_prefix 查找所有匹配的路由"""
        return [
            (subject, info)
            for subject, info in self._routes.items()
            if info.get("router_prefix") == router_prefix
        ]

    # ──────────────────────────────────────────────
    # 过期清理
    # ──────────────────────────────────────────────

    async def cleanup_expired(self) -> List[str]:
        """清理所有心跳超时的路由，返回被清理的 subject 列表

        使用分布式锁确保多网关实例间只有一个执行清理。
        """
        now = time.time()
        expired: List[Tuple[str, Dict[str, Any]]] = []

        # ⚠️ 不加锁读取快照用于识别过期项（避免长时间持有锁）
        for subject, info in list(self._routes.items()):
            if now - info.get("last_heartbeat", 0) > info.get("ttl", 30):
                expired.append((subject, info))

        if not expired:
            return []

        lock_name = "__gw_route_cleanup__"
        try:
            async with MutexLock(
                self._lock_factory._cache,  # type: ignore
                lock_name,
                ttl=self._cleanup_interval * _CLEANUP_LOCK_TTL_MULTIPLIER,
            )(timeout=self._cleanup_interval):
                # 二次确认（在持有锁的时候重新检查，防止竞态）
                still_expired: List[str] = []
                for subject, info in expired:
                    current = self._routes.get(subject)
                    if current and now - current.get("last_heartbeat", 0) > current.get("ttl", 30):
                        still_expired.append(subject)
                        self._routes.pop(subject, None)

                        # 内部主题没有 HTTP 路由，只需从 registry 和 KV 中删除
                        is_internal = info.get("internal", False)
                        if not is_internal:
                            await self._dynamic_route_manager.remove_dynamic_route(
                                router_prefix=info["router_prefix"],
                                path=info["path"],
                                method=info["method"],
                            )

                        logger.info(
                            "Route expired: %s (no heartbeat within %ds)%s",
                            subject, info["ttl"],
                            " [internal]" if is_internal else "",
                        )

                        # 从 KV 中删除
                        await self._kv_store.delete(subject)

                if still_expired:
                    logger.info(
                        "Cleanup cycle: removed %d expired routes",
                        len(still_expired),
                    )
                return still_expired

        except Exception as e:
            logger.debug(
                "Cleanup lock not acquired (another gateway may be handling it): %s", e
            )
            return []

    # ──────────────────────────────────────────────
    # KV 恢复（网关启动时调用）
    # ──────────────────────────────────────────────

    async def restore_from_kv(self) -> int:
        """从 NATS KV 恢复路由到内存和 app.routes

        返回成功恢复的路由数量。
        如果某个 prefix 下有部分路由恢复失败，则将该 prefix 下所有已恢复
        的路由整体回滚，避免 routes_registry 和 app.routes 不一致。
        """
        saved_routes = await self._kv_store.load_all()
        if not saved_routes:
            return 0

        logger.info("Restoring %d routes from KV...", len(saved_routes))
        restored_count = 0

        # 按 router_prefix 分组
        prefix_groups: Dict[str, list] = defaultdict(list)
        for subject, info in saved_routes.items():
            prefix = info.get("router_prefix", "/default")
            prefix_groups[prefix].append((subject, info))

        for prefix, group in prefix_groups.items():
            batch_success = True
            failed_subjects: List[str] = []

            for subject, info in group:
                is_internal = info.get("internal", False)
                if is_internal:
                    # 内联主题没有 HTTP 路由，只需恢复 routes_registry 记录
                    self._routes[subject] = info
                    restored_count += 1
                    logger.debug(
                        "KV restore: internal subject '%s' (registry only, no HTTP route)",
                        subject,
                    )
                    continue

                try:
                    await self._dynamic_route_manager.add_dynamic_route(
                        subject=subject,
                        method=info.get("method", "GET"),
                        path=info.get("path", "/"),
                        params=info.get("params", []),
                        summary=info.get("summary", f"Handler for {subject}"),
                        docstring=info.get("docstring", f"Handler for {subject}"),
                        router_prefix=info.get("router_prefix"),
                        tags=info.get("tags"),
                        timeout=info.get("timeout", 2.0),
                        response_model=info.get("response_model"),
                    )
                    self._routes[subject] = info
                    restored_count += 1
                except Exception as e:
                    logger.error("Failed to restore route %s: %s", subject, e)
                    batch_success = False
                    failed_subjects.append(subject)

            # 部分失败 → 整体回滚该 prefix
            if not batch_success and failed_subjects:
                logger.warning(
                    "KV restore: prefix '%s' had %d/%d routes fail. "
                    "Cleaning up all restored routes for this prefix. "
                    "Worker will re-register them on next heartbeat.",
                    prefix, len(failed_subjects), len(group),
                )
                for subject, info in group:
                    if subject not in failed_subjects:
                        await self._dynamic_route_manager.remove_dynamic_route(
                            router_prefix=info.get("router_prefix", prefix),
                            path=info.get("path", "/"),
                            method=info.get("method", "GET"),
                        )
                        self._routes.pop(subject, None)
                        restored_count -= 1
                        await self._kv_store.delete(subject)
                        logger.info(
                            "Rolled back route %s to maintain consistency", subject
                        )

        logger.info("Restored %d/%d routes from KV", restored_count, len(saved_routes))
        return restored_count

    # ──────────────────────────────────────────────
    # 工具方法
    # ──────────────────────────────────────────────

    def create_lock(self, name: str, ttl: int = 30) -> MutexLock:
        """创建一个关联此 Registry 锁工厂的 MutexLock 实例

        用于外部操作（如 deregister）需要独立锁时的便捷方法。
        """
        return MutexLock(self._lock_factory._cache, name, ttl=ttl)  # type: ignore

    def route_exists_in_app(self, app: FastAPI, subject: str) -> bool:
        """检查路由是否确实存在于 FastAPI 的 app.routes 中"""
        info = self._routes.get(subject)
        if not info:
            return False

        route_path = info.get("path", "/")
        route_method = info.get("method", "GET").upper()
        route_prefix = info.get("router_prefix", "")
        full_path = (
            route_prefix.rstrip("/") + "/" + route_path.lstrip("/")
        ) if route_path.startswith("/") else route_path

        for r in app.routes:
            r_path = getattr(r, "path", None)
            r_methods = getattr(r, "methods", set())
            if r_path == full_path and route_method in r_methods:
                return True
        return False
