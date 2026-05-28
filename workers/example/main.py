"""
Example Worker - 使用 WorkerLifespan 框架
============================================

开发者只需关注业务逻辑函数的实现，框架自动处理：
- NATS 连接与重连
- 服务注册与心跳
- 消息分发与参数解析
- 优雅关闭
"""

import logging
import time
from chongming_worker.worker_lifespan import WorkerLifespan

logger = logging.getLogger("chongming.worker.example")

# 1. 创建应用实例（只需指定配置文件路径）
app = WorkerLifespan("config.toml")


# =============================================
# 业务逻辑：只用写纯函数，关注功能实现
# =============================================

@app.handler("calc.add")
async def add(a: float, b: float) -> dict:
    """加法运算"""
    result = a + b
    logger.info("add: %s + %s = %s", a, b, result)
    return {
        "result": result,
        "operation": "add",
        "timestamp": time.time()
    }


@app.handler("calc.subtract")
async def subtract(a: float, b: float) -> dict:
    """减法运算"""
    result = a - b
    logger.info("subtract: %s - %s = %s", a, b, result)
    return {
        "result": result,
        "operation": "subtract",
        "timestamp": time.time()
    }


@app.handler("calc.multiply")
async def multiply(a: float, b: float) -> dict:
    """乘法运算"""
    result = a * b
    logger.info("multiply: %s * %s = %s", a, b, result)
    return {
        "result": result,
        "operation": "multiply",
        "timestamp": time.time()
    }


@app.handler("calc.divide")
async def divide(a: float, b: float) -> dict:
    """除法运算"""
    if b == 0:
        raise ValueError("除数不能为 0")
    result = a / b
    logger.info("divide: %s / %s = %s", a, b, result)
    return {
        "result": result,
        "operation": "divide",
        "timestamp": time.time()
    }


# =============================================
# 入口：一行启动
# =============================================
if __name__ == "__main__":
    app.run()
