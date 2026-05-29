"""
系统管理 Handler
=================

演示 _nc 和 _app.nats_connection 两种方式访问底层 NATS 连接。

依赖注入说明：
  - ``_nc`` 参数由框架自动注入原始的 NATS 连接对象
  - ``_app`` 参数由框架自动注入 WorkerLifespan 实例
  - 两者都不需要客户端传入
"""

import logging
import time

from app.bootstrap import app

logger = logging.getLogger("chongming.worker.example")


@app.handler("user.health_check")
async def health_check(_nc) -> dict:
    """
    健康检查 — 通过 _nc 直接访问原始 NATS 连接。

    ``_nc`` 参数由框架自动注入，可直接调用 NATS 客户端 API。
    """
    is_connected = _nc.is_connected if hasattr(_nc, 'is_connected') else False
    server_info = str(_nc.connected_url) if hasattr(_nc, 'connected_url') else "unknown"

    return {
        "status": "healthy" if is_connected else "unhealthy",
        "nats_server": server_info,
        "timestamp": time.time(),
    }


@app.handler("system.info")
async def system_info(_app) -> dict:
    """
    系统信息 — 通过 _app.nats_connection 访问底层 NATS 连接。

    ``_app.nats_connection`` 是访问 NATS 连接的另一种方式。
    同时展示如何通过 _app._handlers 获取注册信息（反射）。
    """
    nc = _app.nats_connection
    is_connected = nc.is_connected if hasattr(nc, 'is_connected') else False
    server_info = str(nc.connected_url) if hasattr(nc, 'connected_url') else "unknown"

    # 获取所有注册的 subjects（框架内部属性，用于调试）
    handler_subjects = list(_app._handlers.keys()) if hasattr(_app, '_handlers') else []

    return {
        "status": "healthy" if is_connected else "unhealthy",
        "nats_server": server_info,
        "worker_name": "example",
        "registered_subjects": handler_subjects,
        "heartbeat_interval": getattr(_app, '_heartbeat_interval', 15),
        "timestamp": time.time(),
    }
