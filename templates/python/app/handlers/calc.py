"""
计算器 Handler
===============

纯业务逻辑 handler，无需依赖注入，框架自动完成：
NATS 订阅 → JSON 解析 → 类型转换 → 参数映射 → 响应。

支持两种 handler 参数风格（框架自动识别）：
  风格 A：async def add(a: float, b: float)          — 独立参数，按参数名匹配
  风格 B：async def add(input: CalcAddInput)          — Pydantic 模型参数，自动构造
  风格 C：async def add(data: dict)                   — 原始 dict 参数，直接传递

当前使用风格 B，由 chongming gen-models 生成的 Pydantic 模型自动校验参数。
"""

import logging
import time

from app.bootstrap import app

from models import (
    CalcAddInput,
    CalcAddOutput,
    CalcSubtractInput,
    CalcSubtractOutput,
    CalcMultiplyInput,
    CalcMultiplyOutput,
    CalcDivideInput,
    CalcDivideOutput,
)

logger = logging.getLogger("chongming.worker.example")


@app.handler("calc.add")
async def add(input: CalcAddInput) -> CalcAddOutput:
    """加法运算"""
    result = input.a + input.b
    logger.info("add: %s + %s = %s", input.a, input.b, result)
    return CalcAddOutput(
        result=result,
        operation="add",
        timestamp=time.time()
    )


@app.handler("calc.subtract")
async def subtract(input: CalcSubtractInput) -> CalcSubtractOutput:
    """减法运算"""
    result = input.a - input.b
    logger.info("subtract: %s - %s = %s", input.a, input.b, result)
    return CalcSubtractOutput(
        result=result,
        operation="subtract",
        timestamp=time.time()
    )

@app.handler("calc.multiply")
async def multiply(input: CalcMultiplyInput) -> CalcMultiplyOutput:
    """乘法运算"""
    result = input.a * input.b
    logger.info("multiply: %s * %s = %s", input.a, input.b, result)
    return CalcMultiplyOutput(
        result=result,
        operation="multiply",
        timestamp=time.time()
    )

@app.handler("calc.divide")
async def divide(input: CalcDivideInput) -> CalcDivideOutput:
    """除法运算"""
    if input.b == 0:
        raise ValueError("除数不能为 0")
    result = input.a / input.b
    logger.info("divide: %s / %s = %s", input.a, input.b, result)
    return CalcDivideOutput(
        result=result,
        operation="divide",
        timestamp=time.time()
    )