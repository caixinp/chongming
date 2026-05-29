"""
Pydantic Models - 自动生成

生成自: config.toml
指令: chongming gen-models
"""

from datetime import datetime
from typing import Any, Optional, List, Dict

from pydantic import BaseModel, Field


# ── 内嵌对象模型 ────────────────────────────────────

class User(BaseModel):
    """User"""
    user_id: str
    name: str
    balance: float = 0.0
    level: str = 'normal'
    queried_at: float = 0.0
class CalcAddInput(BaseModel):
    """CALC.ADD 请求参数模型"""
    a: float
    b: float


class CalcAddOutput(BaseModel):
    """CALC.ADD 响应结果模型"""
    result: float
    operation: str = 'add'
    timestamp: float = 0.0


class CalcSubtractInput(BaseModel):
    """CALC.SUBTRACT 请求参数模型"""
    a: float
    b: float


class CalcSubtractOutput(BaseModel):
    """CALC.SUBTRACT 响应结果模型"""
    result: float
    operation: str = 'subtract'
    timestamp: float = 0.0


class CalcMultiplyInput(BaseModel):
    """CALC.MULTIPLY 请求参数模型"""
    a: float
    b: float


class CalcMultiplyOutput(BaseModel):
    """CALC.MULTIPLY 响应结果模型"""
    result: float
    operation: str = 'multiply'
    timestamp: float = 0.0


class CalcDivideInput(BaseModel):
    """CALC.DIVIDE 请求参数模型"""
    a: float
    b: float


class CalcDivideOutput(BaseModel):
    """CALC.DIVIDE 响应结果模型"""
    result: float
    operation: str = 'divide'
    timestamp: float = 0.0


class UserQueryInput(BaseModel):
    """USER.QUERY 请求参数模型"""
    user_id: str


class UserQueryOutput(BaseModel):
    """USER.QUERY 响应结果模型"""
    user_id: str
    name: str
    balance: float = 0.0
    level: str = 'normal'
    queried_at: float = 0.0


class OrderCreateInput(BaseModel):
    """ORDER.CREATE 请求参数模型"""
    user_id: str
    amount: float
    item: str


class OrderCreateOutput(BaseModel):
    """ORDER.CREATE 响应结果模型"""
    order_id: str
    user: User
    item: str
    amount: float
    status: str = 'created'
    timestamp: float = 0.0


class NotificationOrderCreatedInput(BaseModel):
    """NOTIFICATION.ORDER_CREATED 请求参数模型"""
    order_id: str
    user_id: str
    user_name: str
    item: str
    amount: float
    timestamp: float


class NotificationOrderCreatedOutput(BaseModel):
    """NOTIFICATION.ORDER_CREATED 响应结果模型"""
    status: str = 'notified'
    message: str
    order_id: str
    notified_at: float = 0.0


class UserHealthCheckInput(BaseModel):
    """USER.HEALTH_CHECK 请求参数模型"""


class UserHealthCheckOutput(BaseModel):
    """USER.HEALTH_CHECK 响应结果模型"""
    status: str
    nats_server: str
    timestamp: float = 0.0


class SystemInfoInput(BaseModel):
    """SYSTEM.INFO 请求参数模型"""


class SystemInfoOutput(BaseModel):
    """SYSTEM.INFO 响应结果模型"""
    status: str
    nats_server: str
    worker_name: str
    registered_subjects: list = []
    heartbeat_interval: float = 15.0
    timestamp: float = 0.0

