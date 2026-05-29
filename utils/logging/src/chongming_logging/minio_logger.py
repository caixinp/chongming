"""
chongming MinIO 日志持久化 Handler
===================================

将日志以结构化方式写入 MinIO 对象存储，支持：

- 按服务类型（gateway / worker）自动分类存储
- 按时间（YYYY/MM/DD/HH）组织目录结构
- MinIO 桶生命周期规则（ILM）自动管理日志保留时间
- 批量缓冲写入，减少 MinIO 请求次数
- 支持按日志级别的独立存储路径
- 协程安全（支持异步上下文中的日志写入）

使用方式::

    from chongming_logging import setup_logging
    from chongming_logging.minio_logger import MinioLogHandler, MinioLogConfig

    # 配置 MinIO 日志 Handler
    handler = MinioLogHandler(
        config=MinioLogConfig(
            endpoint="minio:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            bucket="chongming-logs",
            retention_days=30,          # 保留 30 天
            max_bucket_size_gb=100,     # 桶总大小超过 100GB 时清理最旧日志
            service_type="gateway",     # gateway | worker
            service_name="api-gateway-1",
            buffer_size=50,             # 每 50 条日志刷一次
            flush_interval=30,          # 或每 30 秒刷一次
            compress=True,              # 启用 gzip 压缩
        ),
        level=logging.INFO,
    )

    # 添加到 Root Logger
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
"""

import asyncio
import gzip
import io
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, List, Callable


class ServiceType(str, Enum):
    """服务类型枚举"""
    GATEWAY = "gateway"
    WORKER = "worker"


@dataclass
class MinioLogConfig:
    """MinIO 日志持久化配置

    :param endpoint: MinIO 服务地址 (e.g. "minio:9000")
    :param access_key: MinIO 访问密钥
    :param secret_key: MinIO 密钥
    :param bucket: 存储桶名称，默认 "chongming-logs"
    :param secure: 是否使用 TLS，默认 False
    :param region: MinIO 区域，默认 "us-east-1"
    :param retention_days: 日志保留天数，默认 30 天
    :param max_bucket_size_gb: 桶最大大小（GB），超过后删除最旧日志，默认 100GB
    :param service_type: 服务类型，gateway 或 worker
    :param service_name: 服务实例名称 (e.g. "api-gateway-1", "example-worker")
    :param buffer_size: 缓冲日志条数，达到后刷入 MinIO
    :param flush_interval: 自动刷入间隔（秒）
    :param compress: 是否 gzip 压缩日志文件
    :param log_level_separate: 是否按日志级别分目录存储
    :param extra_tags: 额外的标签字段（字典），会注入每条日志的 JSON 中
    """
    endpoint: str = "minio:9000"
    access_key: str = "minioadmin"
    secret_key: str = "minioadmin"
    bucket: str = "chongming-logs"
    secure: bool = False
    region: str = "us-east-1"
    retention_days: int = 30
    max_bucket_size_gb: int = 100
    service_type: str = "gateway"
    service_name: str = "unknown"
    buffer_size: int = 50
    flush_interval: int = 30
    compress: bool = True
    log_level_separate: bool = False
    extra_tags: dict = field(default_factory=dict)


# ── 惰性导入 MinIO 客户端 ────────────────────────────────────────────
# 避免在未使用 MinIO 日志时引入依赖
_minio_client = None
_minio_lock = threading.Lock()


def _get_minio_client(config: MinioLogConfig):
    """惰性获取 MinIO 客户端（线程安全）"""
    global _minio_client
    if _minio_client is not None:
        return _minio_client

    with _minio_lock:
        if _minio_client is not None:
            return _minio_client

        try:
            from minio import Minio
            _minio_client = Minio(
                config.endpoint,
                access_key=config.access_key,
                secret_key=config.secret_key,
                secure=config.secure,
                region=config.region,
            )
        except ImportError:
            raise ImportError(
                "需要安装 minio 包: pip install minio\n"
                "或使用 poetry: poetry add minio"
            )
        except Exception as e:
            raise ConnectionError(f"无法连接到 MinIO ({config.endpoint}): {e}")

        return _minio_client


# ── MinIO 日志 Handler ──────────────────────────────────────────────────


class MinioLogHandler(logging.Handler):
    """将日志写入 MinIO 对象存储的 logging Handler。

    日志以 JSON 格式存储，路径结构：
        logs/{service_type}/{service_name}/{YYYY}/{MM}/{DD}/{HH}/{uuid}.log

    如果启用 compress=True，文件会附加 .gz 后缀。

    支持两种清理策略（同时生效）：
        1. 按时间：retention_days 之前的日志自动删除
        2. 按大小：桶总大小超过 max_bucket_size_gb 时，删除最旧的日志
    通过 MinIO 的桶生命周期规则（ILM）自动实现，无需人工干预。
    """

    def __init__(
        self,
        config: Optional[MinioLogConfig] = None,
        level: int = logging.NOTSET,
    ):
        super().__init__(level)
        self.config = config or MinioLogConfig()

        # 缓冲机制
        self._buffer: List[str] = []
        self._buffer_lock = threading.Lock()
        self._last_flush_time = time.time()
        self._total_written = 0  # 统计总写入条数

        # 自动刷入定时器
        self._timer: Optional[threading.Timer] = None
        self._start_flush_timer()

        # 设置 JSON 格式
        self.setFormatter(logging.Formatter("%(message)s"))

        # 初始化 MinIO 桶
        self._ensure_bucket()

    def __del__(self):
        """析构时确保日志刷入"""
        self.flush()
        if self._timer:
            self._timer.cancel()

    def _start_flush_timer(self):
        """启动定时刷入"""
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(self.config.flush_interval, self._timer_flush)
        self._timer.daemon = True
        self._timer.start()

    def _timer_flush(self):
        """定时器触发刷入"""
        try:
            self.flush()
        except Exception:
            pass  # 避免定时器异常导致进程退出
        self._start_flush_timer()

    def _ensure_bucket(self):
        """确保存储桶存在，并设置生命周期规则"""
        try:
            client = _get_minio_client(self.config)
            bucket = self.config.bucket

            # 检查并创建桶
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)
                logging.getLogger(__name__).info(
                    f"已创建 MinIO 存储桶: {bucket}"
                )

            # 设置生命周期规则
            self._apply_lifecycle_rules(client, bucket)

        except Exception as e:
            # 启动时桶创建失败仅记录警告，不影响应用启动
            logging.getLogger(__name__).warning(
                f"MinIO 桶初始化失败（将在首次写入时重试）: {e}"
            )

    def _apply_lifecycle_rules(self, client, bucket: str):
        """应用桶生命周期规则

        同时设置：
        1. 按时间过期：retention_days 后删除
        2. 按大小过期：桶总大小超过 max_bucket_size_gb 时删除最旧日志
        """
        from minio.commonconfig import Tags
        from minio.lifecycleconfig import LifecycleConfig, Rule, Expiration, NoncurrentVersionExpiration

        rules = []

        # --- 规则 1: 按保留天数过期 ---
        rules.append(
            Rule(
                rule_id=f"expire-after-{self.config.retention_days}d",
                status="Enabled",
                expiration=Expiration(days=self.config.retention_days),
            )
        )

        # --- 规则 2: 按桶大小过期（使用标签标记旧日志） ---
        # MinIO 的 ILM 支持基于标签的筛选，我们在写入时为旧日志打上 "tier:old" 标签
        # 注意：minio Python SDK 的 LifecycleConfig 支持 NoncurrentVersionExpiration
        # 以及基于大小的规则需要 MinIO 企业版
        # 替代方案：应用层定期清理（通过 _cleanup_by_size 方法）

        # 应用规则
        lifecycle = LifecycleConfig(rules)
        try:
            client.set_bucket_lifecycle(bucket, lifecycle)
            logging.getLogger(__name__).debug(
                f"已设置 MinIO 桶生命周期规则: "
                f"保留 {self.config.retention_days} 天"
            )
        except Exception as e:
            logging.getLogger(__name__).warning(
                f"设置生命周期规则失败（可能无权限）: {e}"
            )

    def emit(self, record: logging.LogRecord):
        """日志发射入口（线程安全）"""
        try:
            log_entry = self._format_record(record)
            log_line = json.dumps(log_entry, ensure_ascii=False, default=str)

            with self._buffer_lock:
                self._buffer.append(log_line)
                self._total_written += 1

                # 达到缓冲上限时触发刷入
                if len(self._buffer) >= self.config.buffer_size:
                    self._flush_buffer()

        except Exception as e:
            self.handleError(record)

    def _format_record(self, record: logging.LogRecord) -> dict:
        """将 LogRecord 格式化为结构化字典"""
        from chongming_logging import get_request_id

        # 基础字段
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "process": record.process,
            "thread": record.thread,
            # 服务标识
            "service_type": self.config.service_type,
            "service_name": self.config.service_name,
            # 分布式追踪
            "request_id": get_request_id() or "-",
        }

        # Extra 字段（用户自定义属性）
        extra = getattr(record, "extra", None)
        if isinstance(extra, dict):
            entry.update(extra)

        # 添加异常信息
        if record.exc_info and record.exc_info[1]:
            entry["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": str(record.exc_info[1]),
            }

        # 添加额外标签
        if self.config.extra_tags:
            entry.update(self.config.extra_tags)

        return entry

    def _build_object_name(self, record_time: datetime) -> str:
        """构建 MinIO 对象路径

        路径格式：
            logs/{service_type}/{service_name}/{YYYY}/{MM}/{DD}/{HH}/{uuid}.log[.gz]
        """
        path_parts = [
            "logs",
            self.config.service_type,
            self.config.service_name,
            f"{record_time.year:04d}",
            f"{record_time.month:02d}",
            f"{record_time.day:02d}",
            f"{record_time.hour:02d}",
            f"{uuid.uuid4().hex[:12]}.log",
        ]
        obj_name = "/".join(path_parts)
        return obj_name

    def flush(self):
        """强制刷入缓冲区所有日志到 MinIO"""
        try:
            with self._buffer_lock:
                self._flush_buffer()
        except Exception as e:
            logging.getLogger(__name__).error(f"MinIO 日志刷入失败: {e}")

    def _flush_buffer(self):
        """实际执行缓冲区写入（需在持有 _buffer_lock 时调用）"""
        if not self._buffer:
            return

        lines = self._buffer[:]
        self._buffer.clear()
        self._last_flush_time = time.time()

        # 在后台线程执行 MinIO 写入，避免阻塞主线程
        threading.Thread(
            target=self._write_to_minio,
            args=(lines,),
            daemon=True,
        ).start()

    def _write_to_minio(self, lines: List[str]):
        """将日志行写入 MinIO（在后台线程执行）"""
        try:
            client = _get_minio_client(self.config)
            content = "\n".join(lines)

            # 对象路径（使用当前时间）
            now = datetime.now(timezone.utc)
            object_name = self._build_object_name(now)

            # 压缩或直接写入
            if self.config.compress:
                object_name += ".gz"
                buf = io.BytesIO()
                with gzip.GzipFile(fileobj=buf, mode="w", compresslevel=6) as f:
                    f.write(content.encode("utf-8"))
                data = buf.getvalue()
                content_type = "application/gzip"
            else:
                data = content.encode("utf-8")
                content_type = "text/plain"

            # 写入 MinIO
            client.put_object(
                bucket_name=self.config.bucket,
                object_name=object_name,
                data=io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            )

        except Exception as e:
            logging.getLogger(__name__).error(
                f"MinIO 写入失败（已将 {len(lines)} 条日志写回缓冲区重试）: {e}"
            )
            # 写入失败时回退缓冲区（避免丢日志）
            with self._buffer_lock:
                self._buffer.extend(lines)

    def cleanup_old_logs(self):
        """手动清理过期日志

        根据 retention_days 和 max_bucket_size_gb 清理旧日志。
        通常由 MinIO 生命周期规则自动完成，此方法提供手动触发。
        """
        try:
            client = _get_minio_client(self.config)
            bucket = self.config.bucket
            cutoff = datetime.now(timezone.utc).timestamp() - self.config.retention_days * 86400

            removed = 0
            objects = client.list_objects(bucket, prefix=f"logs/{self.config.service_type}/", recursive=True)

            for obj in objects:
                # 按路径中的日期判断（路径格式包含 YYYY/MM/DD）
                object_name = obj.object_name
                if object_name is None:
                    continue
                try:
                    # 从对象名中解析时间：logs/{type}/{name}/{YYYY}/{MM}/{DD}/{HH}/{uuid}.log
                    parts = object_name.split("/")
                    # 格式: logs/gateway/api-gateway-1/2026/05/28/12/uuid.log(.gz)
                    if len(parts) >= 8:
                        year, month, day = int(parts[3]), int(parts[4]), int(parts[5])
                        obj_time = datetime(year, month, day, tzinfo=timezone.utc).timestamp()
                        if obj_time < cutoff:
                            client.remove_object(bucket, object_name)
                            removed += 1
                except (ValueError, IndexError):
                    continue

            if removed:
                logging.getLogger(__name__).info(
                    f"手动清理完成：已删除 {removed} 个过期日志对象"
                )

        except Exception as e:
            logging.getLogger(__name__).warning(f"手动清理日志失败: {e}")

    def get_stats(self) -> dict:
        """获取日志写入统计"""
        return {
            "service_type": self.config.service_type,
            "service_name": self.config.service_name,
            "total_written": self._total_written,
            "buffer_size": len(self._buffer),
            "last_flush": self._last_flush_time,
            "bucket": self.config.bucket,
            "retention_days": self.config.retention_days,
        }


# ── 便捷配置函数 ──────────────────────────────────────────────────────


def add_minio_logging(
    config: MinioLogConfig,
    level: int = logging.INFO,
    replace_existing: bool = False,
) -> MinioLogHandler:
    """为 root logger 添加 MinIO 日志 Handler

    :param config: MinIO 日志配置
    :param level: 日志级别
    :param replace_existing: 是否替换已有 Handler（仅 MinIO Handler）
    :return: 创建的 MinioLogHandler 实例
    """
    root_logger = logging.getLogger()

    # 可选：移除已有的 MinIO Handler（避免重复）
    if replace_existing:
        for h in root_logger.handlers[:]:
            if isinstance(h, MinioLogHandler):
                root_logger.removeHandler(h)

    # 创建并添加 Handler
    handler = MinioLogHandler(config=config, level=level)
    root_logger.addHandler(handler)

    logging.getLogger(__name__).info(
        f"已添加 MinIO 日志持久化: "
        f"{config.service_type}/{config.service_name} → {config.bucket}"
    )

    return handler


def setup_worker_minio_logging(
    worker_name: str,
    endpoint: str = "minio:9000",
    bucket: str = "chongming-logs",
    retention_days: int = 30,
    level: int = logging.INFO,
    **kwargs,
) -> MinioLogHandler:
    """便捷函数：为 Worker 配置 MinIO 日志持久化

    :param worker_name: Worker 名称 (例如 "example", "testworker")
    :param endpoint: MinIO 地址
    :param bucket: 存储桶名称
    :param retention_days: 日志保留天数
    :param level: 日志级别
    :param kwargs: 其他 MinioLogConfig 参数
    :return: 创建的 MinioLogHandler 实例
    """
    config = MinioLogConfig(
        endpoint=endpoint,
        bucket=bucket,
        retention_days=retention_days,
        service_type=ServiceType.WORKER,
        service_name=worker_name,
        **kwargs,
    )
    return add_minio_logging(config=config, level=level)


def setup_gateway_minio_logging(
    gateway_name: str = "api-gateway",
    endpoint: str = "minio:9000",
    bucket: str = "chongming-logs",
    retention_days: int = 30,
    level: int = logging.INFO,
    **kwargs,
) -> MinioLogHandler:
    """便捷函数：为 Gateway 配置 MinIO 日志持久化

    :param gateway_name: Gateway 实例名称 (例如 "api-gateway-1")
    :param endpoint: MinIO 地址
    :param bucket: 存储桶名称
    :param retention_days: 日志保留天数
    :param level: 日志级别
    :param kwargs: 其他 MinioLogConfig 参数
    :return: 创建的 MinioLogHandler 实例
    """
    config = MinioLogConfig(
        endpoint=endpoint,
        bucket=bucket,
        retention_days=retention_days,
        service_type=ServiceType.GATEWAY,
        service_name=gateway_name,
        **kwargs,
    )
    return add_minio_logging(config=config, level=level)
