import logging
import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler

from ..core.config import get_config


config = get_config()
env = config["default"]["env"]
server_config = config[env]["server"]
log_config = config[env]["logging"]


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


def setup_logging(logger: logging.Logger, log_name: str = "app"):
    log_level = getattr(logging, log_config["level"], logging.INFO)
    log_format = log_config["format"]
    # 创建文件夹
    log_file_path = Path(log_config["file"])
    if log_file_path != Path("."):
        log_file_path.mkdir(parents=True, exist_ok=True)

    # 配置根日志记录器
    logger.setLevel(log_level)

    # 创建格式化器
    formatter = logging.Formatter(log_format)

    # 创建轮转文件处理器 - 限制文件大小为 10MB，保留 5 个备份文件
    max_bytes = log_config.get("max_size", 10 * 1024 * 1024)  # 默认 10MB
    backup_count = log_config.get("backup_count", 5)  # 默认保留 5 个备份

    file_handler = RotatingFileHandler(
        f"{log_config['file']}/{log_name}-{datetime.date.today()}.log",
        encoding="utf-8",
        maxBytes=max_bytes,
        backupCount=backup_count,
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(ExcludeWatchFilesFilter())

    # 创建控制台处理器并添加过滤器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
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
