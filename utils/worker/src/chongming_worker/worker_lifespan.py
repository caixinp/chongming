"""
Worker Lifespan Framework
=========================

自动处理 worker 生命周期管理，包括：
- NATS 连接与重连
- 服务注册与心跳
- 消息分发与参数解析
- 优雅关闭

开发者只需专注于业务逻辑函数的实现。
"""

import asyncio
import json
import inspect
import logging
import signal
from typing import Any, Callable, Optional
from dataclasses import dataclass
from functools import wraps

import nats
from nats.aio.msg import Msg

from chongming_config import load_config, Config
from chongming_logging import setup_worker_logging, set_request_id

# 模块加载时自动配置 worker 日志
setup_worker_logging()

logger = logging.getLogger("chongming.worker")


@dataclass
class HandlerInfo:
    """注册的处理函数信息"""
    func: Callable
    subject: str
    params_names: list[str]
    params_types: dict[str, type]


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
    """

    def __init__(self, config_path: str = "config.toml"):
        self.config: Config = load_config(config_path)
        # 从配置读取心跳间隔，默认 15 秒
        self._heartbeat_interval = self.config.get("registration", {}).get("heartbeat_interval", 15)
        self._validate_ttl_config()
        self.nc: Optional[nats.NATS] = None # type: ignore
        self._handlers: dict[str, HandlerInfo] = {}
        self._subscriptions: list[Any] = []
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._running = False
        self._shutdown_event = asyncio.Event()

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

        示例::

            @app.handler("calc.add")
            async def add(a: float, b: float) -> dict:
                result = a + b
                return {"result": result, "operation": "add", "timestamp": time.time()}
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

            self._handlers[subject] = HandlerInfo(
                func=func,
                subject=subject,
                params_names=param_names,
                params_types=params_types,
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
    # 内部：消息处理分发
    # ----------------------------------------------------------------
    async def _dispatch_message(self, msg: Msg) -> None:
        """接收 NATS 消息，解析参数并调用对应的处理函数

        分布式追踪说明：
        - 从 msg.headers 中提取 Gateway 生成的 request_id
        - 写入当前协程的 contextvars，使日志自动带上 [request_id]
        - 在 msg.respond() 响应头中回传 request_id，Gateway 端可验证一致性
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
                # 标准情况：gateway 传过来的 {"a": "1", "b": "2"} 格式
                # 根据函数类型注解自动转换参数类型（如 "10" -> 10.0）
                kwargs = {
                    k: self._convert_param(
                        parsed.get(k),
                        handler_info.params_types.get(k, str),
                    )
                    for k in params_names
                }
            else:
                # 非 dict 的 JSON 值（如裸字符串、数字）- 作为唯一参数传入
                kwargs = {params_names[0]: parsed} if params_names else {}

            # 调用处理函数
            result = await handler_info.func(**kwargs)

            # 序列化结果，并通过响应 Header 回传 request_id
            response = json.dumps(result, default=str).encode()
            # 设置 msg.headers 让 respond() 自动带上这些响应头
            if request_id:
                msg.headers = msg.headers or {}
                msg.headers["request_id"] = request_id
            await msg.respond(response)

            logger.info("Handled %s: %s -> %s", subject, kwargs, result)

        except Exception as e:
            logger.error("Error handling %s: %s", subject, e)
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
        """定期发送心跳到网关，同时批量续期所有路由以确保 gateway 重启后路由快速恢复

        心跳机制说明：
        - 每次循环：逐个发送每个 subject 的心跳消息（type=heartbeat），续期单个路由
        - 每 reregister_cycles 次循环：发送批量续期心跳（type=heartbeat, subjects=[...]），
          一次性续期所有路由，替代原先发送 type=register 导致路由删除重建的不稳定方式
        - NATS 重连时（_on_reconnected）：发送完整注册（type=register），因为此时
          gateway 可能已清空所有路由，需要重建
        """
        heartbeat_per_subject = {
            "type": "heartbeat",
            "service": self.config["registration"]["service"],
        }
        # 批量心跳携带完整的注册信息 items，以便网关在路由丢失时自动重建路由
        # 这样既能避免定期 type=register 触发路由删除重建的窗口期，
        # 又能应对 gateway 重启后 routes_registry 清空、路由需要恢复的场景
        heartbeat_batch = dict(self.config["registration"])
        heartbeat_batch["type"] = "heartbeat"
        heartbeat_batch["subjects"] = [item["subject"] for item in self.config["registration"]["items"]]
        heartbeat_count = 0
        # 批量续期周期：每 N 次心跳后批量续期一次，确保 gateway 重启后路由能快速恢复
        # 相比于原来发送 type=register 触发路由删除重建，这种方式更稳定
        reregister_cycles = 3
        while self._running:
            # 使用可配置的心跳间隔
            await asyncio.sleep(self._heartbeat_interval)
            try:
                heartbeat_count += 1

                if heartbeat_count % reregister_cycles == 0:
                    # 批量续期：一次性续期所有路由，避免逐个发送
                    # 替代原先发送 type=register 导致路由删除重建的不稳定方式
                    await self.nc.publish( # type: ignore
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
