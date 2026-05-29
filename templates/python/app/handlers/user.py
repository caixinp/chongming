"""
用户服务 Handler
=================

演示被动服务 handler，通常被其他服务通过 _app.request() 调用。
这类 handler 不需要知道调用者是谁，只需处理请求并返回响应。
"""

import logging
import time

from app.bootstrap import app

logger = logging.getLogger("chongming.worker.example")

# 模拟用户数据库
_USERS_DB = {
    "u001": {"name": "Alice",   "balance": 100.0, "level": "gold"},
    "u002": {"name": "Bob",     "balance": 50.0,  "level": "silver"},
    "u003": {"name": "Charlie", "balance": 200.0, "level": "platinum"},
}


@app.handler("user.query")
async def query_user(user_id: str) -> dict:
    """
    查询用户信息。

    这是一个**被动服务 handler**，被其他服务（如 order.create）通过
    ``_app.request()`` 调用，不需要知道调用者身份。
    """
    logger.info("查询用户: user_id=%s", user_id)

    user = _USERS_DB.get(user_id)
    if user is None:
        raise ValueError(f"用户不存在: {user_id}")

    return {"user_id": user_id, **user, "queried_at": time.time()}
