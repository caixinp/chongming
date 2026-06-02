import json
import logging
import asyncio
from typing import Any, Optional

from chongming_cache import ChongmingCache

# 导入数据库模型
from ..database_models import *

# 导入 jwt_auth 模块中的函数和变量
from .jwt_auth import (
    jwt_auth,
    get_jwt_auth,
    _init_jwt_auth,
)

# 导入数据库模块中的函数和变量
from chongming_database import (
    _sessionmaker_master,
    _sessionmaker_slave,
    init_database,
    get_db_session,
    get_db_session_master,
    get_db_session_slave,
    set_readonly_mode,
    read_only,
)

# 监听器资源（on_start 创建，on_stop 释放）
_listener_cache: Optional[ChongmingCache] = None
_listener_task: Optional[asyncio.Task] = None

# 配置变更的并发锁，防止多个配置变更事件同时更新全局变量
_config_lock: asyncio.Lock = asyncio.Lock()

logger = logging.getLogger("chongming.worker.user_auth")

async def listen_gateway_config_changes():
    """启动对 gateway_config 键的监听，实时更新 JWT 配置

    在 Worker 启动后自动调用（通过 ``@app.on_start`` 注册）。
    订阅 ``_gw_config_`` KV 桶中的 ``gateway_config`` 键变更，
    当网关配置（如 JWT 密钥）更新时，实时更新本 worker 的
    ``JWTAuth`` 实例，无需重启进程。
    """
    global _listener_task, _listener_cache

    _listener_cache = ChongmingCache(logger, bucket="_gw_config_")
    await _listener_cache.connect()

    await _init_jwt_auth(_listener_cache)  # 初始化 jwt_auth 实例
    await init_database(_listener_cache)        # 初始化数据库连接

    # 订阅后续的配置变更
    _listener_task = await _listener_cache.subscribe(
        "gateway_config",
        _on_gateway_config_change,
    )
    logger.info(
        "Listening for gateway config changes on _gw_config_/gateway_config..."
    )

async def stop_listener():
    """停止监听，释放 NATS 连接资源

    在 Worker 关闭前自动调用（通过 ``@app.on_stop`` 注册）。
    """
    global _listener_task, _listener_cache

    if _listener_task is not None:
        _listener_task.cancel()
        try:
            await _listener_task
        except asyncio.CancelledError:
            pass
        _listener_task = None

    if _listener_cache is not None:
        await _listener_cache.close()
        _listener_cache = None

    logger.info("Gateway config listener stopped")

async def _on_gateway_config_change(entry: Any):
    """网关配置变更回调，实时更新 JWTAuth 和数据库配置

    利用 ``entry`` 参数中的最新配置值更新全局实例，避免重新读取 KV 存储。
    在 ``_config_lock`` 保护下执行，防止并发配置变更导致状态不一致。
    """
    global jwt_auth, _sessionmaker_master, _sessionmaker_slave

    async with _config_lock:
        try:
            # 从 entry 中解析配置，避免重新请求 KV 存储
            if entry is None or entry.value is None:
                logger.warning("Gateway config change entry is empty, skipping")
                return

            gateway_config = json.loads(entry.value.decode())

            # 使用已解析的配置更新 jwt_auth 和数据库会话工厂
            # 注意：_init_jwt_auth 和 init_database 已修改为可接收预解析的配置
            await _init_jwt_auth(listener_cache=None, gateway_config=gateway_config)
            await init_database(listener_cache=None, gateway_config=gateway_config)

            logger.info("Gateway config updated (revision=%d)", entry.revision)
        except json.JSONDecodeError as e:
            logger.error("Failed to decode gateway config: %s", e)
        except Exception as e:
            logger.error("Failed to update gateway config: %s", e, exc_info=True)


__all__ = [
    "get_jwt_auth",
    "get_db_session",
    "get_db_session_master",
    "get_db_session_slave",
    "set_readonly_mode",
    "read_only",
    "listen_gateway_config_changes",
    "stop_listener",
]
