
import json
import logging
from typing import Optional

from chongming_cache import ChongmingCache
from chongming_jwt import JWTAuth


logger = logging.getLogger("chongming.worker.user_auth")

jwt_auth: Optional[JWTAuth] = None

async def _init_jwt_auth(
    listener_cache: Optional[ChongmingCache],
    gateway_config: Optional[dict] = None,
):
    """初始化 JWTAuth 实例

    如果传入了 ``gateway_config`` 则直接使用，否则从 KV 存储中获取。
    这样可以在回调中复用已解析的配置，避免不必要的 I/O。
    """
    global jwt_auth
    try:
        if gateway_config is None:
            if listener_cache is None:
                logger.error("Cannot initialize JWTAuth: no config provided and no cache connection")
                jwt_auth = JWTAuth({})
                return
            raw_entry = await listener_cache.get("gateway_config")
            if raw_entry is not None and raw_entry.value is not None:
                gateway_config = json.loads(raw_entry.value.decode())
            else:
                gateway_config = None

        if gateway_config is not None:
            jwt_config = gateway_config.get("jwt", {})
            jwt_auth = JWTAuth(jwt_config)
        else:
            jwt_auth = JWTAuth({})
            logger.warning(
                "No gateway config found, initialized JWTAuth with empty config"
            )
    except Exception as e:
        logger.error("Failed to initialize JWTAuth: %s", e, exc_info=True)
        jwt_auth = JWTAuth({})


async def get_jwt_auth() -> JWTAuth:
    """获取 JWTAuth 实例（惰性初始化）

    如果 ``listen_gateway_config_changes`` 尚未完成初始化，
    则通过 ``_gw_config_`` KV 桶中的 ``gateway_config`` 键
    惰性创建 JWTAuth 实例。
    """
    global jwt_auth
    if jwt_auth is None:
        async with ChongmingCache(logger, bucket="_gw_config_") as cache:
            await _init_jwt_auth(cache)
    return jwt_auth  # type: ignore
