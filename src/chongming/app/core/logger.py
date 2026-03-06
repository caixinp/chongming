import logging
from pathlib import Path
from .config import Logging
from logging.handlers import RotatingFileHandler


class ExcludeWatchFilesFilter(logging.Filter):
    def filter(self, record):
        # 如果日志记录来自 watchfiles 模块，则不记录（返回 False）
        return not record.name.startswith("watchfiles")


def setup_logging(log_config: Logging):
    log_level = getattr(logging, log_config["level"], logging.INFO)
    log_format = log_config["format"]
    # 创建文件夹
    log_file_path = Path(log_config["file"])
    log_file_dir = log_file_path.parent
    if log_file_dir != Path("."):
        log_file_dir.mkdir(parents=True, exist_ok=True)

    # 设置特定日志级别的过滤
    logging.getLogger("watchfiles").setLevel(logging.WARNING)

    # 配置根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # 创建格式化器
    formatter = logging.Formatter(log_format)

    # 创建轮转文件处理器 - 限制文件大小为 10MB，保留 5 个备份文件
    max_bytes = log_config.get("max_size", 10 * 1024 * 1024)  # 默认 10MB
    backup_count = log_config.get("backup_count", 5)  # 默认保留 5 个备份

    file_handler = RotatingFileHandler(
        log_config["file"],
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
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    print(
        f"日志系统已配置 - 级别: {logging.getLevelName(log_level)}, 文件: {log_config['file']} "
        f"(最大：{max_bytes / 1024 / 1024:.1f}MB, 备份：{backup_count})"
    )


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    # 为每个logger添加过滤器
    logger.addFilter(ExcludeWatchFilesFilter())
    return logger
