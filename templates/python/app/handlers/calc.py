"""
计算器 Handler
===============

纯业务逻辑 handler，无需依赖注入，框架自动完成：
NATS 订阅 → JSON 解析 → 类型转换 → 参数映射 → 响应。
"""

import logging
import time

from app.bootstrap import app

logger = logging.getLogger("chongming.worker.example")


@app.handler("calc.add")
async def add(a: float, b: float) -> dict:
    """加法运算"""
    result = a + b
    logger.info("add: %s + %s = %s", a, b, result)
    return {"result": result, "operation": "add", "timestamp": time.time()}


@app.handler("calc.subtract")
async def subtract(a: float, b: float) -> dict:
    """减法运算"""
    result = a - b
    logger.info("subtract: %s - %s = %s", a, b, result)
    return {"result": result, "operation": "subtract", "timestamp": time.time()}


@app.handler("calc.multiply")
async def multiply(a: float, b: float) -> dict:
    """乘法运算"""
    result = a * b
    logger.info("multiply: %s * %s = %s", a, b, result)
    return {"result": result, "operation": "multiply", "timestamp": time.time()}


@app.handler("calc.divide")
async def divide(a: float, b: float) -> dict:
    """除法运算"""
    if b == 0:
        raise ValueError("除数不能为 0")
    result = a / b
    logger.info("divide: %s / %s = %s", a, b, result)
    return {"result": result, "operation": "divide", "timestamp": time.time()}
