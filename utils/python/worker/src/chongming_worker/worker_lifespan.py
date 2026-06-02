"""
Worker Lifespan Framework
=========================

自动处理 worker 生命周期管理，包括：
- NATS 连接与重连
- 服务注册与心跳
- 消息分发与参数解析
- 优雅关闭
- **Worker 间通讯支持（publish / request）**
- **生命周期钩子（on_start / on_stop）** — 允许 handler 模块注册启动/停止回调

开发者只需专注于业务逻辑函数的实现。
"""

import asyncio
import json
import inspect
import logging
import signal
from contextvars import ContextVar
from typing import Any, Callable, Optional, Dict, List
from dataclasses import dataclass
from functools import wraps

import nats
from nats.aio.msg import Msg
from nats.aio.client import Client

from chongming_config import load_config, Config
from chongming_logging import setup_worker_logging, set_request_id

# 尝试导入 Pydantic，用于检测 BaseModel 子类参数
try:
    from pydantic import BaseModel as PydanticBaseModel
except ImportError:
    PydanticBaseModel = None  # type: ignore

# 模块加载时自动配置 worker 日志
setup_worker_logging()

logger = logging.getLogger("chongming.worker")

# 保留参数列表：框架可以自动注入这些参数到 handler 函数中
# 如果 handler 的某个参数名在此列表中，框架会自动填充对应值
_RESERVED_PARAMS = {
    "_app": "app",          # WorkerLifespan 实例
    "_nc": "nc",            # NATS 连接对象
    "_user": "user",        # 用户身份信息（由 Gateway 通过 JWT 注入）
}


def _serialize_result(result: Any) -> Any:
    """递归序列化 handler 返回结果为 JSON 可序列化格式

    如果结果中包含 Pydantic BaseModel 对象（如 handler 返回了模型实例），
    自动调用 .model_dump() 转换为 dict。
    """
    if PydanticBaseModel is not None and isinstance(result, PydanticBaseModel):
        return result.model_dump()
    if isinstance(result, dict):
        return {k: _serialize_result(v) for k, v in result.items()}
    if isinstance(result, (list, tuple)):
        return [_serialize_result(v) for v in result]
    return result


@dataclass
class HandlerInfo:
    """注册的处理函数信息"""
    func: Callable
    subject: str
    params_names: list[str]
    params_types: dict[str, type]
    needs_app: bool = False          # 是否需要注入 WorkerLifespan 实例
    needs_nc: bool = False           # 是否需要注入 NATS 连接
    needs_user: bool = False         # 是否需要注入用户身份信息
    auth_required: bool = True       # 是否要求认证（默认 True 保持安全）



# ContextVar: 用户身份上下文，用于在 Worker 间调用链中自动传递用户信息
_user_context: ContextVar[Optional[Dict[str, Any]]] = ContextVar("worker_user_context", default=None)


class WorkerLifespan:
    """
    Worker 生命周期管理器

    用法::

        from utils.worker_lifespan import WorkerLifespan

        app = WorkerLifespan("config.toml")

        @app.handler("calc.add")
        async def add(a: float, b: float) -> dict:
            result = a + b
            return {"result": result, "operation": "add", "timestamp": time.time()}

        @app.handler("calc.multiply")
        async def multiply(a: float, b: float) -> dict:
            result = a * b
            return {"result": result, "operation": "multiply", "timestamp": time.time()}

        if __name__ == "__main__":
            app.run()

    Worker 间通讯示例::

        app = WorkerLifespan("config.toml")

        @app.handler("order.create")
        async def create_order(user_id: str, amount: float, _app: WorkerLifespan) -> dict:
            # 同步调用另一个 worker 的服务
            user_info = await _app.request("user.query", {"user_id": user_id}, timeout=3.0)

            # 或者异步通知（发布-订阅模式）
            await _app.publish("notification.order_created", {
                "user_id": user_id,
                "amount": amount,
            })

            return {"order_id": "ord_123", "user": user_info}

        @app.handler("user.query")
        async def query_user(user_id: str) -> dict:
            return {"user_id": user_id, "name": "Alice", "balance": 100.0}

    ==========
    生命周期钩子
    ==========

    handler 模块可以通过 ``on_start`` / ``on_stop`` 注册回调，
    让 WorkerLifespan 在合适的时机自动调用它们：:

        # 在 handler 模块中（如 app/handlers/auth.py）
        from app.bootstrap import app

        @app.on_start
        async def my_startup():
            # NATS 已就绪，可安全连接外部服务、启动监听等
            pass

        @app.on_stop
        async def my_cleanup():
            # 优雅关闭：释放连接、取消任务等
            pass

    回调注册发生在模块导入时（同步），而回调执行是在 ``app.run()``
    的事件循环中（异步）。
    """

    def __init__(self, config_path: str = "config.toml"):
        self.config: Config = load_config(config_path)
        # 从配置读取心跳间隔，默认 15 秒
        self._heartbeat_interval = self.config.get("registration", {}).get("heartbeat_interval", 15)
        self._validate_ttl_config()
        self.nc: Optional[Client] = None
        self._handlers: dict[str, HandlerInfo] = {}
        self._subscriptions: list[Any] = []
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._running = False
        self._shutdown_event = asyncio.Event()
        # ── 生命周期钩子 ──────────────────────────────────────
        self._startup_hooks: List[Callable[[], Any]] = []
        self._shutdown_hooks: List[Callable[[], Any]] = []

    # ----------------------------------------------------------------
    # 生命周期钩子 API
    # ----------------------------------------------------------------
    @property
    def on_start(self):
        """装饰器/方法：注册 worker 启动后的回调

        用法（装饰器风格，推荐）::

            @app.on_start
            async def setup_db_pool():
                global db
                db = await create_pool()

        用法（方法调用风格）::

            async def setup_db_pool():
                global db
                db = await create_pool()

            app.on_start(setup_db_pool)

        多个钩子按注册顺序依次执行。某个钩子失败时仅记录日志，
        不会阻止后续钩子或 worker 启动。
        """
        def _wrapper(func: Callable) -> Callable:
            self._startup_hooks.append(func)
            return func
        return _wrapper

    @on_start.setter
    def on_start(self, func: Callable) -> None:
        self._startup_hooks.append(func)

    @property
    def on_stop(self):
        """装饰器/方法：注册 worker 关闭前的清理回调

        用法（装饰器风格，推荐）::

            @app.on_stop
            async def close_db_pool():
                global db
                await db.close()

        用法（方法调用风格）::

            async def close_db_pool():
                global db
                await db.close()

            app.on_stop(close_db_pool)

        多个钩子按**相反顺序**执行（后注册的先执行），
        确保资源释放的顺序与创建顺序相反。
        """
        def _wrapper(func: Callable) -> Callable:
            self._shutdown_hooks.append(func)
            return func
        return _wrapper

    @on_stop.setter
    def on_stop(self, func: Callable) -> None:
        self._shutdown_hooks.append(func)

    # ----------------------------------------------------------------
    # 属性：暴露 NATS 连接供 worker 间通讯
    # ----------------------------------------------------------------
    @property
    def nats_connection(self) -> Client:
        """获取 NATS 连接对象，用于自定义 NATS 操作"""
        if self.nc is None:
            raise RuntimeError("NATS connection is not established. Call start() first.")
        return self.nc

    # ----------------------------------------------------------------
    # 主动通讯 API
    # ----------------------------------------------------------------
    @staticmethod
    def _serialize_data(data: Any) -> Any:
        """将数据序列化为 JSON 可序列化格式

        如果数据中包含 Pydantic BaseModel 对象，自动调用 .model_dump() 转换为 dict。
        """
        if PydanticBaseModel is not None and isinstance(data, PydanticBaseModel):
            return data.model_dump()
        if isinstance(data, dict):
            return {k: WorkerLifespan._serialize_data(v) for k, v in data.items()}
        if isinstance(data, (list, tuple)):
            return [WorkerLifespan._serialize_data(v) for v in data]
        return data

    async def publish(self, subject: str, data: Any) -> None:
        """
        主动向指定 subject 发布消息（发布-订阅模式）

        :param subject: NATS subject
        :param data: 要发布的数据（会被序列化为 JSON）
                     支持 Pydantic BaseModel 实例，自动转换为 dict
        """
        if self.nc is None:
            raise RuntimeError("NATS connection is not established. Call start() first.")
        serialized = self._serialize_data(data)
        payload = json.dumps(serialized, default=str).encode()
        await self.nc.publish(subject, payload)
        logger.debug("Published to '%s': %s", subject, data)

    async def request(
        self,
        subject: str,
        data: Any,
        timeout: float = 5.0,
        user_info: Optional[Dict[str, Any]] = None,
    ) -> dict:
        """
        向指定 subject 发送请求并等待响应（请求-回复模式）
        用于 worker 之间同步调用：A worker 请求 B worker 的服务。

        :param subject: 目标 handler 的 subject
        :param data: 请求数据（会被序列化为 JSON）
                     支持 Pydantic BaseModel 实例，自动转换为 dict
        :param timeout: 超时时间（秒），默认 5 秒
        :param user_info: 用户身份信息（可选）。如果未指定，自动从当前
                          调用链的上下文（_user_context）中继承。
                          当 worker 收到来自 Gateway 的请求（已携带用户信息）
                          时，该 worker 在处理过程中发起的 _app.request()
                          会自动继承这个用户信息。
        :return: 响应数据（JSON dict）
        :raises ValueError: 目标 worker 返回的业务错误
        :raises asyncio.TimeoutError: 超时未收到响应
        :raises RuntimeError: NATS 未连接
        """
        if self.nc is None:
            raise RuntimeError("NATS connection is not established. Call start() first.")

        # 如果未显式传递 user_info，自动从 ContextVar 继承调用链中的用户身份
        if user_info is None:
            user_info = _user_context.get()

        serialized = self._serialize_data(data)
        payload = json.dumps(serialized, default=str).encode()

        # 构建 NATS headers，传递用户身份信息
        headers = {}
        if user_info:
            headers["x-user-id"] = user_info.get("user_id", "")
            headers["x-user-roles"] = ",".join(user_info.get("roles", []))
            headers = {k: v for k, v in headers.items() if v}  # 移除空值

        response = await self.nc.request(subject, payload, timeout=timeout, headers=headers or None)
        result = json.loads(response.data.decode())
        logger.debug("Request to '%s': %s -> %s", subject, data, result)
        # ── 目标 worker 返回的业务错误 → 提升为异常 ─────────────┐
        # 其他 worker 的 handler 抛出的异常会被 _dispatch_message
        # 捕获并返回 {"error": "错误信息"} 格式的响应。
        # request() 应将其转为 ValueError 抛出，使调用方可以通过
        # try/except 捕获并得体地处理（如降级、重试）。
        if isinstance(result, dict) and "error" in result:
            raise ValueError(result["error"])
        return result

    # ----------------------------------------------------------------
    # 内部：保留参数自动注入
    # ----------------------------------------------------------------
    def _build_reserved_kwargs(self, handler_info: HandlerInfo, user_info: Optional[dict] = None) -> dict:
        """为 handler 构建框架自动注入的保留参数"""
        kwargs = {}
        if handler_info.needs_app:
            kwargs["_app"] = self
        if handler_info.needs_nc:
            kwargs["_nc"] = self.nc
        if handler_info.needs_user and user_info:
            kwargs["_user"] = user_info
        return kwargs

    def _validate_ttl_config(self):
        """校验 TTL 配置的合理性：TTL 必须至少大于心跳间隔，否则路由会在心跳到来前被清理"""
        registration = self.config.get("registration", {})
        items = registration.get("items", [])
        for item in items:
            ttl = item.get("ttl", 30)
            if ttl <= self._heartbeat_interval:
                raise ValueError(
                    f"Item '{item.get('subject', 'unknown')}' has ttl={ttl}s, "
                    f"but heartbeat_interval={self._heartbeat_interval}s. "
                    f"TTL must be greater than heartbeat_interval to avoid premature route removal. "
                    f"Recommended: ttl >= {self._heartbeat_interval * 3}s"
                )
            if ttl < self._heartbeat_interval * 3:
                subject = item.get("subject", "unknown")
                logger.warning(
                    "'%s' ttl=%ds is low (heartbeat_interval=%ds). "
                    "A single missed heartbeat may cause route expiration. "
                    "Recommended: ttl >= %ds",
                    subject, ttl, self._heartbeat_interval, self._heartbeat_interval * 3,
                )

    # ----------------------------------------------------------------
    # 装饰器：注册消息处理函数
    # ----------------------------------------------------------------
    def handler(self, subject: str = "") -> Callable:
        """
        装饰器：将 async 函数注册为指定 subject 的消息处理器。

        :param subject: 要订阅的 NATS subject。如果未指定，尝试从配置中推断。

        处理器函数签名要求：
        - 参数名与配置中 registration.items[].params 一一对应
        - 返回 dict，按 response_model 结构返回数据
        - **支持保留参数注入**：如果参数名为 ``_app``，自动注入 ``WorkerLifespan`` 实例；
          如果参数名为 ``_nc``，自动注入 NATS 连接对象。

        Worker 间通讯示例::

            @app.handler("order.create")
            async def create_order(user_id: str, amount: float, _app: WorkerLifespan) -> dict:
                # 调用其他 worker 的服务
                user_info = await _app.request("user.query", {"user_id": user_id})
                await _app.publish("notification.order_created", {"user_id": user_id})
                return {"order_id": "ord_123", "user": user_info}
        """
        def decorator(func: Callable) -> Callable:
            nonlocal subject

            # 如果没有显式指定 subject，尝试从函数名或配置中匹配
            if not subject:
                sig = inspect.signature(func)
                func_params = list(sig.parameters.keys())
                # 尝试查找配置中参数匹配的路由
                for item in self.config["registration"]["items"]: # type: ignore
                    if item["params"] == func_params: # type: ignore
                        subject = item["subject"] # type: ignore
                        break
                if not subject:
                    # 回退：使用函数名作为 subject
                    subject = f"{self.config['registration']['service']}.{func.__name__}" # type: ignore

            sig = inspect.signature(func)
            param_names = list(sig.parameters.keys())
            # 提取参数类型标注
            annotations = func.__annotations__ if hasattr(func, '__annotations__') else {}
            params_types = {}
            for name in param_names:
                if name in annotations and annotations[name] is not inspect.Parameter.empty:
                    params_types[name] = annotations[name]

            # 检查是否使用了保留参数（_app, _nc, _user）
            needs_app = "_app" in param_names
            needs_nc = "_nc" in param_names
            needs_user = "_user" in param_names

            # 从配置中查找该 subject 对应的 auth_required 值
            auth_required = True  # 默认要求认证
            registration = self.config.get("registration", {})
            items = registration.get("items", [])
            for item in items:
                if item.get("subject") == subject:
                    auth_required = item.get("auth_required", True)
                    break
            logger.debug(
                "Handler '%s': auth_required=%s, needs_user=%s",
                subject, auth_required, needs_user,
            )

            self._handlers[subject] = HandlerInfo(
                func=func,
                subject=subject,
                params_names=param_names,
                params_types=params_types,
                needs_app=needs_app,
                needs_nc=needs_nc,
                needs_user=needs_user,
                auth_required=auth_required,
            )

            @wraps(func)
            async def wrapper(*args, **kwargs):
                return await func(*args, **kwargs)

            return wrapper
        return decorator

    @staticmethod
    def _convert_param(value: Any, target_type: type) -> Any:
        """将参数值转换为目标类型

        支持常见类型：int, float, bool, str 以及可接受单个参数的构造器类型。
        对于 Union 类型（如 Optional[int]），尝试每个子类型。
        """
        import typing

        if value is None:
            return None

        # 处理 Union/Optional 类型（如 Optional[int], Union[str, int]）
        origin = getattr(target_type, '__origin__', None)
        if origin is typing.Union:
            # 尝试每个子类型，NoneType 跳过
            for arg in target_type.__args__:
                if arg is type(None):
                    continue
                try:
                    return WorkerLifespan._convert_param(value, arg)
                except (ValueError, TypeError):
                    continue
            # 所有类型都失败，先尝试用 str 转换
            return str(value)

        # 基础类型：用类型构造器直接转换
        if target_type in (int, float, bool, str):
            if target_type == bool:
                if isinstance(value, str):
                    return value.lower() in ('true', '1', 'yes')
                return bool(value)
            return target_type(value)

        # 其他类型（如 Decimal, datetime 等）尝试用构造器
        try:
            return target_type(value)
        except (TypeError, ValueError):
            return value

    # ----------------------------------------------------------------
    # Pydantic 模型验证（可选）
    # ----------------------------------------------------------------
    async def _validate_with_pydantic(self, subject: str, parsed: dict) -> dict:
        """尝试用自动生成的 Pydantic 模型验证输入参数

        如果存在 models/__init__.py，导入对应 subject 的 Input 模型进行验证。
        验证通过后返回转换后的参数 dict，失败则抛出异常。

        这是可选的增强功能：没有 models/__init__.py 时降级为普通 dict。
        """
        try:
            # 尝试从 models 包导入输入模型
            from models import __all__ as model_names  # type: ignore

            # 构建模型类名：subject 的 PascalCase 版本 + "Input"
            subject_parts = subject.replace("-", "_").replace(".", "_").split("_")
            model_class_name = "".join(p.capitalize() for p in subject_parts if p) + "Input"

            # 查找对应的  Input 模型
            if model_class_name not in dir(models):  # type: ignore
                return parsed

            input_model_class = getattr(models, model_class_name)  # type: ignore

            # 用 pydantic 验证并转换
            validated = input_model_class(**parsed)
            return validated.model_dump()
        except ImportError:
            # 没有 models 包 → 降级
            return parsed
        except Exception as e:
            logger.warning("Pydantic validation failed for %s (fallback to raw): %s", subject, e)
            return parsed

    # ----------------------------------------------------------------
    # 内部：消息处理分发
    # ----------------------------------------------------------------
    async def _dispatch_message(self, msg: Msg) -> None:
        """接收 NATS 消息，解析参数并调用对应的处理函数

        分布式追踪说明：
        - 从 msg.headers 中提取 Gateway 生成的 request_id
        - 写入当前协程的 contextvars，使日志自动带上 [request_id]
        - 在 msg.respond() 响应头中回传 request_id，Gateway 端可验证一致性

        Worker 间通讯支持：
        - 如果 handler 声明了 ``_app`` 参数，自动注入 ``WorkerLifespan`` 实例
          供 handler 内调用 ``_app.publish()`` 或 ``_app.request()`` 与其他 worker 通讯
        - 如果 handler 声明了 ``_nc`` 参数，自动注入 NATS 连接对象

        Pydantic 模型验证：
        - 如果 worker 目录下存在 models/__init__.py（由 ``chongming gen-models`` 生成），
          框架自动使用对应的 Input 模型验证请求参数
        - 验证通过后参数自动按类型转换（如字符串 "10" → int 10）
        - 没有 models 包时降级为普通 dict 处理，兼容现有代码
        """
        subject = msg.subject

        # ── 提取分布式追踪上下文 ────────────────────────────
        request_id = msg.headers.get("request_id", "") if msg.headers else ""
        if request_id:
            set_request_id(request_id)

        # ── 提取用户身份信息（由 Gateway 通过 JWT 注入） ────
        user_info = None
        if msg.headers:
            user_id = msg.headers.get("x-user-id", "")
            roles_str = msg.headers.get("x-user-roles", "")
            if user_id:
                roles = roles_str.split(",") if roles_str else []
                user_info = {"user_id": user_id, "roles": roles}

        handler_info = self._handlers.get(subject)
        if handler_info is None:
            logger.warning("No handler for subject: %s", subject)
            error_response = json.dumps({"error": f"handler not found for subject: {subject}"}).encode()
            try:
                await msg.respond(error_response)
            except Exception:
                pass
            return

        # ── 认证检查：如果 handler 要求认证但缺少用户信息，拒绝请求 ──
        if handler_info.auth_required and not user_info:
            logger.warning(
                "Authentication required for subject '%s' but no user info found in headers",
                subject,
            )
            error_response = json.dumps({"error": "Authentication required"}).encode()
            if msg.reply:
                await msg.respond(error_response)
            return

        # ── 将用户信息存入 contextvar，使调用链中的 _app.request() 能自动继承 ──
        if user_info:
            _user_context.set(user_info)

        try:
            # 解析消息数据为 JSON dict（gateway 端以 JSON dict 格式传递参数）
            data = msg.data.decode()
            parsed = json.loads(data)
            params_names = handler_info.params_names

            if isinstance(parsed, dict):
                # ── Pydantic 模型验证（如果存在 models 包） ────
                # 自动生成的 models 存在时，用 Input 模型做类型校验和转换
                validated = await self._validate_with_pydantic(subject, parsed)
                if validated != parsed:
                    logger.debug("Pydantic validated & transformed input: %s -> %s", parsed, validated)
                    parsed = validated

                # ── 构建 handler 参数 ──────────────────────────────
                # 支持多种 handler 风格：
                #   风格 A：async def add(a: float, b: float)          — 独立参数，自动类型转换
                #   风格 B：async def add(input: CalcAddInput)          — Pydantic 模型参数
                #   风格 C：async def add(data: dict)                   — 原始 dict 参数
                #   风格 D：async def add(data: Any)                    — 不限制类型，保留 JSON 原始类型
                # 框架自动识别参数类型并选择合适的方式构造：
                #   - 如果参数是 Pydantic BaseModel 子类 → 自动构造模型实例
                #   - 如果参数是 dict → 直接传递整个 parsed dict
                #   - 如果参数是 Any/object → 直接传递原始值，不做类型转换
                #   - 否则 → 按参数名从 parsed 中提取对应值，并做类型转换
                kwargs = {}
                for k in params_names:
                    if k in _RESERVED_PARAMS:
                        continue  # 保留参数不来自请求数据
                    target_type = handler_info.params_types.get(k)
                    if target_type is not None and PydanticBaseModel is not None and inspect.isclass(target_type) and issubclass(target_type, PydanticBaseModel):
                        # 风格 B：参数类型是 Pydantic BaseModel 子类
                        # 用整个请求 dict 构造模型实例（自动校验和类型转换）
                        kwargs[k] = target_type(**parsed)
                    elif target_type is dict:
                        # 风格 C：参数类型是 dict → 直接传递整个 parsed dict
                        kwargs[k] = parsed
                    elif target_type is Any or target_type is object:
                        # 风格 D：参数类型是 Any/object → 不限制类型，直接传递原始值
                        # 不做任何类型转换，保留 JSON 原始类型（dict/list/str/int/float/bool/None）
                        # 直接传递整个 parsed dict，与风格 C (dict) 行为一致
                        kwargs[k] = parsed
                    else:
                        # 风格 A：按参数名从 parsed 中提取值，并做类型转换
                        kwargs[k] = self._convert_param(
                            parsed.get(k),
                            target_type or str,
                        )

                # ── 注入框架保留参数 ────────────────────────────
                kwargs.update(self._build_reserved_kwargs(handler_info))

            else:
                # 非 dict 的 JSON 值（如裸字符串、数字）- 作为唯一参数传入
                kwargs = {params_names[0]: parsed} if params_names else {}

            # 调用处理函数
            result = await handler_info.func(**kwargs)

            # ── 序列化结果为 JSON 可序列化格式 ──────────────────
            # 如果 handler 返回了 Pydantic BaseModel 对象（或嵌套了 BaseModel），
            # 自动转换为 dict，确保 json.dumps 能正常序列化
            serializable = _serialize_result(result)

            # ── 有 reply subject 时才响应 ────────────────────────
            # publish 模式触发的消息没有 reply subject，直接跳过响应
            if msg.reply:
                response = json.dumps(serializable, default=str).encode()
                if request_id:
                    msg.headers = msg.headers or {}
                    msg.headers["request_id"] = request_id
                await msg.respond(response)

            logger.info("Handled %s: %s -> %s", subject, kwargs, result)

        except Exception as e:
            logger.error("Error handling %s: %s", subject, e)
            # ── 有 reply subject 时才响应错误 ──────────────────
            if msg.reply:
                error_response = json.dumps({"error": str(e)}).encode()
                try:
                    if request_id:
                        msg.headers = msg.headers or {}
                        msg.headers["request_id"] = request_id
                    await msg.respond(error_response)
                except Exception:
                    pass

    # ----------------------------------------------------------------
    # 内部：心跳
    # ----------------------------------------------------------------
    async def _heartbeat_loop(self) -> None:
        """定期发送心跳到网关，同时批量续期所有路由以确保 gateway 重启后路由快速恢复"""
        heartbeat_per_subject = {
            "type": "heartbeat",
            "service": self.config["registration"]["service"], # type: ignore
        }
        # 批量心跳携带完整的注册信息 items，以便网关在路由丢失时自动重建路由
        heartbeat_batch = dict(self.config["registration"]) # type: ignore
        heartbeat_batch["type"] = "heartbeat"
        heartbeat_batch["subjects"] = [item["subject"] for item in self.config["registration"]["items"]] # type: ignore
        heartbeat_count = 0
        # 批量续期周期：每 N 次心跳后批量续期一次，确保 gateway 重启后路由能快速恢复
        reregister_cycles = 3
        while self._running:
            # 使用可配置的心跳间隔
            await asyncio.sleep(self._heartbeat_interval)
            try:
                heartbeat_count += 1

                if heartbeat_count % reregister_cycles == 0:
                    # 批量续期：一次性续期所有路由，避免逐个发送
                    await self.nc.publish(  # type: ignore
                        "service.registry",
                        json.dumps(heartbeat_batch).encode()
                    )
                    logger.info("Batch heartbeat sent (renews all routes, every %ds)", reregister_cycles * self._heartbeat_interval)
                else:
                    # 逐个发送每个 subject 的心跳
                    for item in self.config["registration"]["items"]: # type: ignore
                        heartbeat_per_subject["subject"] = item["subject"] # type: ignore
                        await self.nc.publish( # type: ignore
                            "service.registry",
                            json.dumps(heartbeat_per_subject).encode()
                        )
                logger.debug("Heartbeat sent (interval=%ds)", self._heartbeat_interval)
            except Exception as e:
                logger.error("Heartbeat failed: %s", e)

    # ----------------------------------------------------------------
    # 生命周期：启动
    # ----------------------------------------------------------------
    async def start(self) -> None:
        """启动 worker：连接 NATS、执行启动钩子、注册、订阅、开始心跳"""
        if self._running:
            return
        self._running = True

        # 1. 连接 NATS
        urls = self.config["nats"]["urls"] # type: ignore
        logger.info("Connecting to NATS: %s", urls)
        self.nc = await nats.connect(
            urls,
            error_cb=self._on_error,
            disconnected_cb=self._on_disconnected,
            reconnected_cb=self._on_reconnected,
            closed_cb=self._on_closed,
        )
        logger.info("Connected to NATS")

        # 2. 执行启动钩子（NATS 已就绪，可以安全使用网络连接）
        for hook in self._startup_hooks:
            try:
                result = hook()
                if hasattr(result, '__await__'):
                    await result
            except Exception as e:
                logger.error("Startup hook '%s' failed: %s", getattr(hook, '__name__', hook), e)

        # 3. 注册到网关（携带 config_version 用于版本兼容性检查）
        registration = dict(self.config["registration"]) # type: ignore
        # 将 worker 级别的 config_version 合并到 registration 消息中
        worker_cfg = self.config.get("worker", {})
        if "config_version" not in registration:
            registration["config_version"] = worker_cfg.get("config_version", "")
        # 同时传递 worker name 辅助诊断
        registration["name"] = worker_cfg.get("name", registration.get("service", "unknown"))

        await self.nc.publish(
            "service.registry",
            json.dumps(registration).encode()
        )
        logger.info(
            "Registered with gateway: %s (config_version=%s)",
            registration['service'], registration.get("config_version", "none"),
        )

        # 4. 订阅处理的主题（使用 Queue Group 实现负载均衡）
        queue_group = self.config["registration"].get("queue_group", self.config["registration"]["service"]) # type: ignore
        for subject in self._handlers:
            sub = await self.nc.subscribe(subject, queue=queue_group, cb=self._dispatch_message)
            self._subscriptions.append(sub)
            logger.info("Subscribed to: %s (queue_group=%s)", subject, queue_group)

        # 如果没有任何 handler 注册，从配置自动注册
        if not self._handlers:
            for item in self.config["registration"]["items"]: # type: ignore
                sub = await self.nc.subscribe(
                    item["subject"], # type: ignore
                    queue=queue_group,
                    cb=self._dispatch_auto_from_config
                )
                self._subscriptions.append(sub)
                logger.info("Auto-subscribed to: %s (queue_group=%s)", item['subject'], queue_group) # type: ignore
                logger.warning("No handler registered for '%s'", item['subject']) # type: ignore

        # 5. 开始心跳
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        logger.info("Worker '%s' is running...", self.config['worker']['name']) # type: ignore
        logger.info("Heartbeat interval: %ds", self._heartbeat_interval)
        logger.info("Registered subjects: %s", list(self._handlers.keys()) or [i['subject'] for i in self.config['registration']['items']]) # type: ignore

    async def _dispatch_auto_from_config(self, msg: Msg) -> None:
        """兜底：当没有注册 handler 时，打印警告并返回错误"""
        logger.warning("Received message on '%s' but no handler registered", msg.subject)
        error_response = json.dumps({"error": f"handler not found for subject: {msg.subject}"}).encode()
        try:
            await msg.respond(error_response)
        except Exception:
            pass

    # ----------------------------------------------------------------
    # 生命周期：优雅关闭
    # ----------------------------------------------------------------
    async def shutdown(self) -> None:
        """优雅关闭 worker

        关闭顺序（保证 NATS 连接在 shutdown hooks 执行完之前保持可用）：
          1. 取消心跳
          2. 取消 NATS 订阅（不再接收新消息）
          3. 发送注销消息到 gateway
          4. 执行关闭钩子（如取消缓存监听、关闭数据库连接等）
             → 此时 NATS 连接仍然活跃，shutdown hooks 可安全使用
          5. 关闭 NATS 连接
        """
        if not self._running:
            return
        self._running = False
        logger.info("Shutting down...")

        # 取消心跳任务
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        # 取消订阅（不再接收新消息）
        for sub in self._subscriptions:
            try:
                await sub.unsubscribe()
            except Exception:
                pass
        self._subscriptions.clear()

        # 发送注销消息
        try:
            deregister_msg = {
                "type": "deregister",
                "service": self.config["registration"]["service"], # type: ignore
            }
            await self.nc.publish( # type: ignore
                "service.registry",
                json.dumps(deregister_msg).encode()
            )
            logger.info("Deregistered from gateway")
        except Exception as e:
            logger.error("Deregistration failed: %s", e)

        # 执行关闭钩子（后注册的先执行）
        # NATS 连接此时仍然活跃，shutdown hooks 可以安全地取消其依赖 NATS 的任务
        for hook in reversed(self._shutdown_hooks):
            try:
                result = hook()
                if hasattr(result, '__await__'):
                    await result
            except Exception as e:
                logger.error("Shutdown hook '%s' failed: %s", getattr(hook, '__name__', hook), e)

        # 最后关闭 NATS 连接
        if self.nc and self.nc.is_connected:
            await self.nc.drain()
            logger.info("NATS connection drained")

        logger.info("Shutdown complete")
        self._shutdown_event.set()

    # ----------------------------------------------------------------
    # 生命周期回调
    # ----------------------------------------------------------------
    async def _on_error(self, e: Exception) -> None:
        logger.error("NATS error: %s", e)

    async def _on_disconnected(self) -> None:
        logger.warning("Disconnected from NATS")

    async def _on_reconnected(self) -> None:
        logger.info("Reconnected to NATS")
        # 重新注册
        registration = self.config["registration"] # type: ignore
        await self.nc.publish( # type: ignore
            "service.registry",
            json.dumps(registration).encode()
        )
        logger.info("Re-registered with gateway after reconnection")

    async def _on_closed(self) -> None:
        logger.info("NATS connection closed")

    # ----------------------------------------------------------------
    # 入口：run
    # ----------------------------------------------------------------
    def run(self) -> None:
        """同步入口：启动事件循环并运行 worker"""
        async def _run():
            # 注册信号处理
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(
                    sig,
                    lambda s=sig: asyncio.create_task(self._signal_handler(s))
                )

            await self.start()
            # 等待关闭信号
            await self._shutdown_event.wait()

        try:
            asyncio.run(_run())
        except KeyboardInterrupt:
            pass

    async def _signal_handler(self, sig: signal.Signals) -> None:
        logger.info("Received signal: %s", sig.name)
        await self.shutdown()
