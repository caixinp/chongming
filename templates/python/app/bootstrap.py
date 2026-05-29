"""
Worker 初始化与日志配置
========================

集中管理 WorkerLifespan 实例化、MinIO 日志持久化等全局初始化逻辑。
"""

import logging

from chongming_worker.worker_lifespan import WorkerLifespan
from chongming_config import load_config

logger = logging.getLogger("chongming.worker.example")

# ── 全局 Worker 应用实例 ──────────────────────────────────────────
# 所有 handler 模块通过 from app.bootstrap import app 引入
app = WorkerLifespan("config.toml")


def setup_minio_logging() -> None:
    """初始化 MinIO 日志持久化（非阻塞，失败不影响 Worker 启动）"""
    try:
        from chongming_logging.minio_logger import setup_worker_minio_logging

        _config = load_config("config.toml")
        _minio_cfg = _config.get("logging", {}).get("minio", {})
        if _minio_cfg.get("enabled", True):
            setup_worker_minio_logging(
                worker_name=_config["worker"]["name"],
                endpoint=_minio_cfg.get("endpoint", "localhost:9000"),
                bucket=_minio_cfg.get("bucket", "chongming-logs"),
                retention_days=int(_minio_cfg.get("retention_days", 30)),
                level=logging.INFO,
            )
            logger.info(
                "MinIO logging initialized: worker/%s -> %s (retention: %sd)",
                _config["worker"]["name"],
                _minio_cfg.get("bucket", "chongming-logs"),
                _minio_cfg.get("retention_days", 30),
            )
    except ImportError:
        logger.debug("minio package not installed, MinIO logging disabled")
    except Exception as e:
        logger.warning("Failed to initialize MinIO logging: %s", e)
