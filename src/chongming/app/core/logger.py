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
    """为 status_code 添加颜色的日志格式化器"""

    COLORS = {
        "2": "\033[32m",  # 绿色 2xx
        "3": "\033[36m",  # 青色 3xx
        "4": "\033[33m",  # 黄色 4xx
        "5": "\033[31m",  # 红色 5xx
    }
    RESET = "\033[0m"

    def format(self, record):
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
    def __init__(self):
        super().__init__()
        self._filter_starts_with_tulpe = (
            "watchfiles",
            "aiosqlite",
            "apscheduler",
            "sqlalchemy",
            "sqlitedict",
            "sqlalchemy.engine.Engine",
        )

    # 重写过滤方法
    def filter(self, record):
        return not record.name.startswith(self._filter_starts_with_tulpe)


_configured_loggers = set()


def setup_logging(logger: logging.Logger, log_name: str = "app"):
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
    logger = logging.getLogger(name)
    setup_logging(logger, name)
    return logger
