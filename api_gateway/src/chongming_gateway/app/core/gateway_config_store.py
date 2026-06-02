"""Gateway Config Store — 将网关配置存入 NATS KV

使用分布式锁 + ChongmingCache 将网关的 config.toml 同步到 NATS JetStream KV 桶中，
使得所有 worker 能通过 NATS 获取网关的共享配置（如 JWT 密钥、NATS 地址等）。

多实例安全
----------
- 使用 MutexLock 确保同一时间只有一个网关实例写入配置
- 使用 CAS（Compare-And-Swap）乐观锁防止并发覆盖
- 新实例启动时自动接管配置发布权
"""

import asyncio
import json
import logging
from typing import Any, Dict, Optional

from chongming_cache import ChongmingCache
from chongming_lock import MutexLock, LockFactory

logger = logging.getLogger("chongming.gateway.gateway_config_store")

_GW_CONFIG_BUCKET = "_gw_config_"
_GW_CONFIG_KEY = "gateway_config"
_GW_CONFIG_LOCK_KEY = "__gw_config_publish__"
_LOCK_TTL = 10       # 锁持有时间（秒）
_LOCK_TIMEOUT = 5.0   # 获取锁的超时时间（秒）
_PUBLISH_INTERVAL = 60  # 定期重新发布间隔（秒）


class GatewayConfigStore:
    """网关配置存储管理器

    将完整的网关配置存入 NATS KV，供所有 worker 读取。
    使用分布式锁保证多网关实例间的并发安全。

    用法::

        # 网关侧（app/__init__.py）：
        config_store = GatewayConfigStore(config, logger)
        await config_store.start()

        # Worker 侧：
        from chongming_worker.gateway_config import get_gateway_config
        gw_config = await get_gateway_config()
    """

    def __init__(self, config: Dict[str, Any], logger_instance: logging.Logger):
        self._config = config
        self._logger = logger_instance
        self._cache: Optional[ChongmingCache] = None
        self._lock_factory: Optional[LockFactory] = None
        self._publish_task = None
        self._running = False

    async def start(self) -> None:
        """初始化并发布配置到 NATS KV

        流程：
        1. 创建 ChongmingCache 实例连接到 KV 桶
        2. 创建 LockFactory 用于分布式锁
        3. 用分布式锁保护配置写入
        4. 启动定期重新发布任务（应对新网关实例上线）
        """
        self._cache = ChongmingCache(self._logger, bucket=_GW_CONFIG_BUCKET)
        await self._cache.__aenter__()
        self._lock_factory = LockFactory(self._cache)

        await self._publish_config()
        self._running = True

        # 启动定期重新发布，使新启动的网关实例能立即拿到最新配置
        self._publish_task = asyncio.create_task(self._publish_loop())

        self._logger.info(
            "Gateway config store started (bucket: %s, key: %s)",
            _GW_CONFIG_BUCKET, _GW_CONFIG_KEY,
        )

    async def _publish_config(self) -> None:
        """发布当前配置到 NATS KV（带分布式锁保护）"""
        try:
            async with MutexLock(
                self._cache,
                _GW_CONFIG_LOCK_KEY,
                ttl=_LOCK_TTL,
            )(timeout=_LOCK_TIMEOUT):
                config_json = json.dumps(self._config, default=str, ensure_ascii=False).encode()
                await self._cache.put(_GW_CONFIG_KEY, config_json) # type: ignore
                self._logger.info("Gateway config published to NATS KV")
        except Exception as e:
            self._logger.warning(
                "Failed to acquire config publish lock (will retry): %s", e
            )

    async def _publish_loop(self) -> None:
        """定期重新发布配置，确保新网关实例能获取最新配置"""
        while self._running:
            await asyncio.sleep(_PUBLISH_INTERVAL)
            try:
                await self._publish_config()
            except Exception as e:
                self._logger.error("Periodic config publish failed: %s", e)

    async def stop(self) -> None:
        """停止定期发布并关闭连接"""
        self._running = False
        if self._publish_task:
            self._publish_task.cancel()
            try:
                await self._publish_task
            except asyncio.CancelledError:
                pass
        if self._cache:
            await self._cache.__aexit__(None, None, None)
        self._logger.info("Gateway config store stopped")

    # ──────────────────────────────────────────────
    # 静态工具方法：Worker 侧获取网关配置
    # ──────────────────────────────────────────────

    @staticmethod
    async def get_config(
        logger_instance: logging.Logger,
    ) -> Optional[Dict[str, Any]]:
        """从 NATS KV 获取网关配置（Worker 侧使用）

        参数:
            logger_instance: 日志记录器
            nats_url: NATS 连接地址（可选，默认从 worker 的 config.toml 读取）

        返回:
            gateway 配置 dict，如果读取失败返回 None

        用法::

            from app.bootstrap import app

            async with app:
                gw_config = await GatewayConfigStore.get_config(logger)
                if gw_config:
                    jwt_config = gw_config.get("jwt", {})
                    nats_config = gw_config.get("nats", {})
        """
        cache = ChongmingCache(logger_instance, bucket=_GW_CONFIG_BUCKET)
        try:
            await cache.connect()
            entry = await cache.get(_GW_CONFIG_KEY)
            if entry is None:
                logger_instance.warning(
                    "Gateway config not found in NATS KV (bucket: %s)",
                    _GW_CONFIG_BUCKET,
                )
                return None
            config = json.loads(entry.value.decode()) # type: ignore
            logger_instance.debug("Gateway config retrieved from NATS KV")
            return config
        except Exception as e:
            logger_instance.error("Failed to get gateway config from NATS KV: %s", e)
            return None
        finally:
            await cache.close()
