import re
import logging
import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler

from ..core.config import get_config


config = get_config()
env = config["default"]["env"]
server_config = config[env]["server"]
log_config = config[env]["logging"]


class ColoredFormatter(logging.Formatter):
    """
    为 HTTP 状态码添加颜色的日志格式化器

    根据 HTTP 状态码的首位数字为日志消息中的状态码添加不同颜色：
    - 2xx: 绿色（成功）
    - 3xx: 青色（重定向）
    - 4xx: 黄色（客户端错误）
    - 5xx: 红色（服务器错误）

    Attributes:
        COLORS: 状态码首位数字到 ANSI 颜色代码的映射字典
        RESET: ANSI 重置颜色代码
    """

    COLORS = {
        "2": "\033[32m",  # 绿色 2xx
        "3": "\033[36m",  # 青色 3xx
        "4": "\033[33m",  # 黄色 4xx
        "5": "\033[31m",  # 红色 5xx
    }
    RESET = "\033[0m"

    def format(self, record):
        """
        格式化日志记录，为状态码添加颜色

        如果日志记录包含 status_code 属性，则查找消息中的 "status=数字" 模式
        并为其添加对应的颜色代码。格式化完成后恢复原始消息以避免影响其他 handler。

        Args:
            record: 日志记录对象，应包含 msg 属性和可选的 status_code 属性

        Returns:
            str: 格式化后的日志消息字符串，状态码部分可能包含 ANSI 颜色代码
        """
        # 保存原始消息
        original_msg = record.msg
        # 如果日志记录包含 status_code 属性，则为其添加颜色
        status_code = getattr(record, "status_code", None)
        if status_code and isinstance(status_code, int):
            first_digit = str(status_code)[0]
            color = self.COLORS.get(first_digit, "")
            colored_status = f"{color}{status_code}{self.RESET}"
            # 替换消息中的 "status=数字" 为带颜色的版本
            record.msg = re.sub(
                rf"status={status_code}\b", f"status={colored_status}", original_msg
            )
        result = super().format(record)
        # 恢复原始消息，避免影响其他 handler
        record.msg = original_msg
        return result


class ExcludeWatchFilesFilter(logging.Filter):
    """
    日志过滤器，用于排除第三方库的日志输出

    过滤掉来自 watchfiles、aiosqlite、apscheduler、sqlalchemy 等库的日志记录，
    避免这些库的详细日志污染应用日志输出。
    """

    def __init__(self):
        """
        初始化过滤器，设置需要过滤的日志名称前缀列表
        """
        super().__init__()
        self._filter_starts_with_tulpe = (
            "watchfiles",
            "aiosqlite",
            "apscheduler",
            "sqlalchemy",
            "sqlitedict",
            "sqlalchemy.engine.Engine",
        )

    def filter(self, record):
        """
        判断是否应该保留该日志记录

        Args:
            record: 日志记录对象，包含 name 属性表示日志来源

        Returns:
            bool: 如果日志名称不以过滤列表中的任何前缀开头则返回 True（保留），
                  否则返回 False（过滤掉）
        """
        return not record.name.startswith(self._filter_starts_with_tulpe)


_configured_loggers = set()


def setup_logging(logger: logging.Logger, log_name: str = "app"):
    """
    配置日志系统，包括文件和控制台输出

    为指定的 logger 配置以下功能：
    1. 设置日志级别和格式
    2. 创建按日期命名的轮转文件处理器（支持文件大小限制和备份数量控制）
    3. 创建带颜色格式化的控制台处理器
    4. 应用过滤器排除第三方库日志

    该函数具有防重复配置机制，同一个 log_name 只会配置一次。

    Args:
        logger: 需要配置的 logging.Logger 实例
        log_name: 日志名称标识，用于区分不同的日志配置和生成日志文件名，默认为 "app"

    Returns:
        None

    Raises:
        无显式抛出异常，但可能因文件系统权限问题导致目录创建或文件写入失败
    """
    if log_name in _configured_loggers:
        return
    _configured_loggers.add(log_name)
    log_level = getattr(logging, log_config["level"], logging.INFO)
    log_format = log_config["format"]
    # 创建文件夹
    log_file_path = Path(log_config["file"])
    if log_file_path != Path("."):
        log_file_path.mkdir(parents=True, exist_ok=True)

    # 配置根日志记录器
    logger.setLevel(log_level)

    # 创建格式化器
    plain_formatter = logging.Formatter(log_format)
    color_formatter = ColoredFormatter(log_format)

    # 创建轮转文件处理器 - 限制文件大小为 10MB，保留 5 个备份文件
    max_bytes = log_config.get("max_size", 10 * 1024 * 1024)  # 默认 10MB
    backup_count = log_config.get("backup_count", 5)  # 默认保留 5 个备份

    file_handler = RotatingFileHandler(
        f"{log_config['file']}/{log_name}-{datetime.date.today()}.log",
        encoding="utf-8",
        maxBytes=max_bytes,
        backupCount=backup_count,
    )
    file_handler.setFormatter(plain_formatter)
    file_handler.addFilter(ExcludeWatchFilesFilter())

    # 创建控制台处理器并添加过滤器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(color_formatter)
    console_handler.addFilter(ExcludeWatchFilesFilter())

    # 添加处理器到根日志记录器
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    print(
        f"日志系统已配置 - 级别: {logging.getLevelName(log_level)}, 文件: {log_config['file']} "
        f"(最大：{max_bytes / 1024 / 1024:.1f}MB, 备份：{backup_count})"
    )


def get_logger(name: str) -> logging.Logger:
    """
    获取配置好的日志记录器实例

    根据名称获取或创建 logger 实例，并自动调用 setup_logging 进行配置。
    如果该名称的 logger 已经配置过，则直接返回已配置的实例。

    Args:
        name: 日志记录器名称，通常使用模块名如 __name__

    Returns:
        logging.Logger: 已配置完成的日志记录器实例，可直接用于记录日志
    """
    logger = logging.getLogger(name)
    setup_logging(logger, name)
    return logger
