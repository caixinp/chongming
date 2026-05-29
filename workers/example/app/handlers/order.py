"""
订单 Handler — Worker 间通讯演示
==================================

演示 _app.request() 和 _app.publish() 两大 Worker 间通讯模式。

依赖注入说明：
  - ``_app`` 参数由框架自动注入（类型注解 WorkerLifespan）
  - 客户端只需传入 user_id, amount, item 等业务参数
  - 框架自动识别 _app 为保留参数，不要求客户端传入
"""

import logging
import time

from app.bootstrap import app
from chongming_worker.worker_lifespan import WorkerLifespan

from models import (
    OrderCreateInput,
    OrderCreateOutput,
    NotificationOrderCreatedInput,
    NotificationOrderCreatedOutput,
    UserQueryInput,
    User,
)

logger = logging.getLogger("chongming.worker.example")


@app.handler("order.create")
async def create_order(input: OrderCreateInput, _app: WorkerLifespan) -> OrderCreateOutput:
    """
    创建订单（主动调用方）。

    演示 Worker 间通讯：
      1. ``_app.request("user.query", ...)`` → 同步调用 user.query
      2. ``_app.publish("notification.order_created", ...)`` → 异步广播
    """
    logger.info("创建订单: user=%s, item=%s, amount=%s", input.user_id, input.item, input.amount)

    # ── 1. request 模式：调用 user.query 获取用户信息 ────────────────
    logger.info("→ 调用 user.query...")
    try:
        user_info = await _app.request("user.query", UserQueryInput(user_id="u001"), timeout=3.0)
        logger.info("← 用户信息: %s", user_info)
    except Exception as e:
        logger.error("查询用户失败: %s", e)
        user_info = {"user_id": input.user_id, "name": "Unknown",
                     "balance": 0.0, "level": "normal"}

    if input.amount > user_info.get("balance", 0):
        raise ValueError(f"余额不足: 需要 {input.amount}, 可用 {user_info.get('balance', 0)}")  
    # ── 2. publish 模式：异步广播通知 ────────────────────────────────
    order_id = f"ord_{int(time.time())}_{input.user_id}"
    await _app.publish("notification.order_created", NotificationOrderCreatedInput(
        order_id=order_id,
        user_id=input.user_id,
        user_name=user_info["name"],
        item=input.item,
        amount=input.amount,
        timestamp=time.time()
    ))
    logger.info("→ 已广播通知 notification.order_created")

    return OrderCreateOutput(
        order_id=order_id,
        user=User(**user_info),
        item=input.item,
        amount=input.amount
    )


@app.handler("notification.order_created")
async def order_created_notification(input: NotificationOrderCreatedInput) -> NotificationOrderCreatedOutput:
    """
    订单创建通知（publish 接收方）。

    通过 publish() 异步触发的 handler，独立于触发方执行，
    属于消息系统的"扇出"（fan-out）模式。
    """
    logger.info("收到订单通知: order=%s, user=%s(%s), item=%s, amount=%s",
                input.order_id, input.user_name, input.user_id, input.item, input.amount)

    return NotificationOrderCreatedOutput(
        status="notified",
        message=f"订单 {input.order_id} 已创建，用户 {input.user_name} 已通知",
        order_id=input.order_id,
    )
