"""
chongming 日志工具包
====================

为 chongming 体系下的组件提供统一的日志配置功能。
支持一次调用完成日志格式、级别、输出目标的设置。

使用方式::

    from chongming_logging import setup_logging, setup_worker_logging

    # 通用日志配置
    setup_logging()

    # Worker 专用配置（自动设置 chongming.worker 日志器）
    setup_worker_logging()

    # Gateway 专用配置（自动设置 chongming.gateway 日志器）
    setup_gateway_logging()
"""

import logging
import sys
from contextvars import ContextVar

# ── 跨组件追踪 ID (Trace Context) ──────────────────────────────────────
# 使用 contextvars 实现协程安全的 request_id 传递，无需修改函数签名
request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    """获取当前上下文的 request_id（用于日志模板动态注入）"""
    return request_id_var.get()


def set_request_id(request_id: str) -> None:
    """设置当前上下文的 request_id"""
    request_id_var.set(request_id)


# ── 日志 Filter：自动注入 request_id ───────────────────────────────────
class RequestIdFilter(logging.Filter):
    """日志 Filter，自动从 contextvars 中获取 request_id 并注入日志记录。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        return True


# ── 格式化常量 ─────────────────────────────────────────────────────────
_LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(request_id)s] %(name)s: %(message)s"
_logging_configured = False


def _ensure_request_id_filter() -> None:
    """无条件确保 root logger 上挂载了 RequestIdFilter。

    此函数独立于 basicConfig 的缓存逻辑，确保无论日志系统如何配置，
    [request_id] 字段都始终注入到每条日志记录中。
    """
    root_logger = logging.getLogger()
    existing_filters = {type(f).__name__ for f in root_logger.filters}
    if "RequestIdFilter" not in existing_filters:
        root_logger.addFilter(RequestIdFilter())

    # 同时检查所有现有 handler，确保 handler 上层过滤也支持
    for handler in root_logger.handlers:
        handler_filters = {type(f).__name__ for f in handler.filters}
        if "RequestIdFilter" not in handler_filters:
            handler.addFilter(RequestIdFilter())


def setup_logging(
    level: int = logging.INFO,
    fmt: str = _LOG_FORMAT,
    *,
    force: bool = False,
) -> None:
    """配置日志输出格式（仅在首次调用时生效）。

    如果使用者已自行配置过 logging（root logger 已有 handler），则跳过。
    设置 force=True 可强制覆盖已有配置。

    :param level: 日志级别，默认 logging.INFO
    :param fmt: 日志格式字符串，默认包含 [%(request_id)s] 字段
    :param force: 是否强制覆盖已有日志配置
    """
    global _logging_configured
    if _logging_configured and not force:
        _ensure_request_id_filter()  # 即使已配置过，也要确保 filter 存在
        return

    root_logger = logging.getLogger()
    if root_logger.handlers and not force:
        _logging_configured = True
        _ensure_request_id_filter()  # 用户已自行配置，但我们的 filter 仍需挂载
        return

    logging.basicConfig(
        level=level,
        format=fmt,
        stream=sys.stdout,
        force=force,
    )

    # 无条件添加 RequestIdFilter（幂等）
    _ensure_request_id_filter()
    _logging_configured = True


def setup_worker_logging(
    level: int = logging.INFO,
    fmt: str = _LOG_FORMAT,
) -> None:
    """配置 Worker 日志（便捷函数）。

    与 setup_logging() 行为相同，语义上明确用于 Worker 组件。
    """
    setup_logging(level=level, fmt=fmt)


def setup_gateway_logging(
    level: int = logging.INFO,
    fmt: str = _LOG_FORMAT,
) -> None:
    """配置 Gateway 日志（便捷函数）。

    与 setup_logging() 行为相同，语义上明确用于 Gateway 组件。
    """
    setup_logging(level=level, fmt=fmt)


# 模块加载时自动配置日志（确保用户若不手动配置也能看到日志）
_ensure_request_id_filter()
setup_logging()
