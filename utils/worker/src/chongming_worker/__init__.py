"""
chongming_worker - Worker 生命周期框架
========================================

提供 WorkerLifespan 类用于管理 worker 生命周期，
以及 model_gen 模块用于从 config.toml 自动生成 Pydantic 模型。
"""

from chongming_worker.worker_lifespan import WorkerLifespan
from chongming_worker.model_gen import generate_models, write_models_to_disk, get_worker_names

__all__ = [
    "WorkerLifespan",
    "generate_models",
    "write_models_to_disk",
    "get_worker_names",
]
