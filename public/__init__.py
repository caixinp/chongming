"""
Pydantic Models - 自动生成

生成自: config.toml
指令: chongming gen-models
"""

from datetime import datetime
from typing import Any, Optional, List, Dict

from pydantic import BaseModel, Field

class CalcAddInput(BaseModel):
    """CALC.ADD 请求参数模型"""
    a: float
    b: float


class CalcAddOutput(BaseModel):
    """CALC.ADD 响应结果模型"""
    result: float
    operation: str = 'add'
    timestamp: float = 0.0

