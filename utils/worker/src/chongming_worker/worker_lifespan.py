"""
Worker Lifespan Framework
=========================

自动处理 worker 生命周期管理，包括：
- NATS 连接与重连
- 服务注册与心跳
- 消息分发与参数解析
- 优雅关闭
- **Worker 间通讯支持（publish / request）**

开发者只需专注于业务逻辑函数的实现。
"""

import asyncio
import json
import inspect
import logging
import signal
from typing import Any, Callable, Optional, Union
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
    ) -> dict:
        """
        向指定 subject 发送请求并等待响应（请求-回复模式）
        用于 worker 之间同步调用：A worker 请求 B worker 的服务。

        :param subject: 目标 handler 的 subject
        :param data: 请求数据（会被序列化为 JSON）
                     支持 Pydantic BaseModel 实例，自动转换为 dict
        :param timeout: 超时时间（秒），默认 5 秒
        :return: 响应数据（JSON dict）
        :raises ValueError: 目标 worker 返回的业务错误
        :raises asyncio.TimeoutError: 超时未收到响应
        :raises RuntimeError: NATS 未连接
        """
        if self.nc is None:
            raise RuntimeError("NATS connection is not established. Call start() first.")
        serialized = self._serialize_data(data)
        payload = json.dumps(serialized, default=str).encode()
        response = await self.nc.request(subject, payload, timeout=timeout)
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
    def _build_reserved_kwargs(self, handler_info: HandlerInfo) -> dict:
        """为 handler 构建框架自动注入的保留参数"""
        kwargs = {}
        if handler_info.needs_app:
            kwargs["_app"] = self
        if handler_info.needs_nc:
            kwargs["_nc"] = self.nc
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
                for item in self.config["registration"]["items"]:
                    if item["params"] == func_params:
                        subject = item["subject"]
                        break
                if not subject:
                    # 回退：使用函数名作为 subject
                    subject = f"{self.config['registration']['service']}.{func.__name__}"

            sig = inspect.signature(func)
            param_names = list(sig.parameters.keys())
            # 提取参数类型标注
            annotations = func.__annotations__ if hasattr(func, '__annotations__') else {}
            params_types = {}
            for name in param_names:
                if name in annotations and annotations[name] is not inspect.Parameter.empty:
                    params_types[name] = annotations[name]

            # 检查是否使用了保留参数（_app, _nc）
            needs_app = "_app" in param_names
            needs_nc = "_nc" in param_names

            self._handlers[subject] = HandlerInfo(
                func=func,
                subject=subject,
                params_names=param_names,
                params_types=params_types,
                needs_app=needs_app,
                needs_nc=needs_nc,
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

        handler_info = self._handlers.get(subject)
        if handler_info is None:
            logger.warning("No handler for subject: %s", subject)
            error_response = json.dumps({"error": f"handler not found for subject: {subject}"}).encode()
            try:
                await msg.respond(error_response)
            except Exception:
                pass
            return

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
                # 支持两种 handler 风格：
                #   风格 A：async def add(a: float, b: float)          — 独立参数
                #   风格 B：async def add(input: CalcAddInput)          — Pydantic 模型参数
                #   风格 C：async def add(data: dict)                   — 原始 dict 参数
                # 框架自动识别参数类型并选择合适的方式构造：
                #   - 如果参数是 Pydantic BaseModel 子类 → 自动构造模型实例
                #   - 如果参数是 dict → 直接传递整个 parsed dict
                #   - 否则 → 按参数名从 parsed 中提取对应值
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
            "service": self.config["registration"]["service"],
        }
        # 批量心跳携带完整的注册信息 items，以便网关在路由丢失时自动重建路由
        heartbeat_batch = dict(self.config["registration"])
        heartbeat_batch["type"] = "heartbeat"
        heartbeat_batch["subjects"] = [item["subject"] for item in self.config["registration"]["items"]]
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
                    for item in self.config["registration"]["items"]:
                        heartbeat_per_subject["subject"] = item["subject"]
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
        """启动 worker：连接 NATS、注册、订阅、开始心跳"""
        if self._running:
            return
        self._running = True

        # 1. 连接 NATS
        urls = self.config["nats"]["urls"]
        logger.info("Connecting to NATS: %s", urls)
        self.nc = await nats.connect(
            urls,
            error_cb=self._on_error,
            disconnected_cb=self._on_disconnected,
            reconnected_cb=self._on_reconnected,
            closed_cb=self._on_closed,
        )
        logger.info("Connected to NATS")

        # 2. 注册到网关
        registration = self.config["registration"]
        await self.nc.publish(
            "service.registry",
            json.dumps(registration).encode()
        )
        logger.info("Registered with gateway: %s", registration['service'])

        # 3. 订阅处理的主题（使用 Queue Group 实现负载均衡）
        queue_group = self.config["registration"].get("queue_group", self.config["registration"]["service"])
        for subject in self._handlers:
            sub = await self.nc.subscribe(subject, queue=queue_group, cb=self._dispatch_message)
            self._subscriptions.append(sub)
            logger.info("Subscribed to: %s (queue_group=%s)", subject, queue_group)

        # 如果没有任何 handler 注册，从配置自动注册
        if not self._handlers:
            for item in self.config["registration"]["items"]:
                sub = await self.nc.subscribe(
                    item["subject"],
                    queue=queue_group,
                    cb=self._dispatch_auto_from_config
                )
                self._subscriptions.append(sub)
                logger.info("Auto-subscribed to: %s (queue_group=%s)", item['subject'], queue_group)
                logger.warning("No handler registered for '%s'", item['subject'])

        # 4. 开始心跳
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        logger.info("Worker '%s' is running...", self.config['worker']['name'])
        logger.info("Heartbeat interval: %ds", self._heartbeat_interval)
        logger.info("Registered subjects: %s", list(self._handlers.keys()) or [i['subject'] for i in self.config['registration']['items']])

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
        """优雅关闭 worker"""
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

        # 取消订阅
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
                "service": self.config["registration"]["service"],
            }
            await self.nc.publish( # type: ignore
                "service.registry",
                json.dumps(deregister_msg).encode()
            )
            logger.info("Deregistered from gateway")
        except Exception as e:
            logger.error("Deregistration failed: %s", e)

        # 关闭 NATS 连接
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
        registration = self.config["registration"]
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
