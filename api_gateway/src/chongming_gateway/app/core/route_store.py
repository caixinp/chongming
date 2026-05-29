"""NATS KV 持久化的路由注册表存储

将 routes_registry 的数据持久化到 NATS JetStream KV 桶中，
使得网关重启后能快速从 KV 恢复所有路由，无需等待 worker 下一次心跳。
"""

import json
import time
import logging
from typing import Dict, Any, Optional, List

from chongming_cache import ChongmingCache

logger = logging.getLogger("chongming.gateway.route_store")

_ROUTES_BUCKET = "_gw_routes_"


class RouteKVStore:
    """基于 NATS KV 的路由注册表持久化存储

    每个 key 对应一个 subject，value 是 route_info 的 JSON 序列化。
    提供原子化的读写操作，支持分布式多网关实例共享。
    """

    def __init__(self, cache: ChongmingCache):
        self._cache = cache

    async def load_all(self) -> Dict[str, Dict[str, Any]]:
        """从 KV 桶加载所有未过期的路由，返回 {subject: route_info} 字典

        自动过滤掉已过期（last_heartbeat + ttl < now）的路由。
        """
        registry: Dict[str, Dict[str, Any]] = {}
        now = time.time()
        try:
            keys = await self._cache.keys()
        except Exception as e:
            logger.error("Failed to list keys from KV bucket '%s': %s", _ROUTES_BUCKET, e)
            return registry

        for key in keys:
            try:
                entry = await self._cache.get(key)
                if entry is None:
                    continue
                info = json.loads(entry.value.decode()) # type: ignore
                # 检查是否过期
                last_hb = info.get("last_heartbeat", 0)
                ttl = info.get("ttl", 30)
                if now - last_hb > ttl:
                    logger.info("Skipping expired route from KV: %s (last_hb=%d, ttl=%d)", key, last_hb, ttl)
                    await self.delete(key)
                    continue
                registry[key] = info
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("Skipping corrupted route entry in KV: %s (%s)", key, e)
                continue

        logger.info("Loaded %d routes from KV bucket '%s'", len(registry), _ROUTES_BUCKET)
        return registry

    async def save(self, subject: str, info: Dict[str, Any]) -> None:
        """保存单个路由信息到 KV"""
        try:
            data = json.dumps(info, default=str).encode()
            await self._cache.put(subject, data)
            logger.debug("Saved route to KV: %s", subject)
        except Exception as e:
            logger.error("Failed to save route to KV: %s (%s)", subject, e)

    async def save_batch(self, updates: Dict[str, Optional[Dict[str, Any]]]) -> None:
        """批量保存/删除路由信息到 KV

        - 如果 value 不为 None，则保存
        - 如果 value 为 None，则删除
        """
        for subject, info in updates.items():
            if info is not None:
                await self.save(subject, info)
            else:
                await self.delete(subject)

    async def delete(self, subject: str) -> None:
        """从 KV 中删除单个路由"""
        try:
            await self._cache.delete(subject)
            logger.debug("Deleted route from KV: %s", subject)
        except Exception as e:
            logger.error("Failed to delete route from KV: %s (%s)", subject, e)

    async def delete_batch(self, subjects: List[str]) -> None:
        """批量从 KV 中删除路由"""
        for subject in subjects:
            await self.delete(subject)
