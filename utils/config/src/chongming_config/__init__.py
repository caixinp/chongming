import logging
import tomli
from typing import TypedDict, Any

logger = logging.getLogger("chongming.config")

class RegistrationItemConfig(TypedDict):
    subject: str
    method: str
    path: str
    summary: str
    docstring: str
    params: list[str]
    ttl: int
    timeout: float
    response_model: Any  # 可以是 dict、list 或 None，根据实际需求定义

class CleanupConfig(TypedDict):
    interval: int  # 过期路由清理检查间隔（秒），默认 10

class RegistrationConfig(TypedDict):
    type: str
    service: str
    router_prefix: str
    tags: list[str]
    items: list[RegistrationItemConfig]
    heartbeat_interval: int  # 心跳间隔（秒），默认 15

class NATSConfig(TypedDict):
    urls: list[str]

class WorkerConfig(TypedDict):
    name: str
    version: str
    description: str

class MinioLoggingConfig(TypedDict):
    endpoint: str
    bucket: str
    retention_days: int
    level: int

class LoggingConfig(TypedDict):
    minio: MinioLoggingConfig

class Config(TypedDict):
    worker: WorkerConfig
    nats: NATSConfig
    registration: RegistrationConfig
    logging: LoggingConfig

class DefaultConfig(TypedDict):
    debug: bool
    description: str
    name: str
    version: str
    env: str
    prefix: str

class DataBaseConfig(TypedDict):
    type: str

class GatewayConfig(TypedDict):
    default: DefaultConfig
    nats: NATSConfig
    databse: DataBaseConfig
    cleanup: CleanupConfig
    logging: LoggingConfig

def load_config(config_path: str) -> Config:
    """从 TOML 文件加载配置"""
    with open(config_path, "rb") as f:
        config = tomli.load(f)
    return config # type: ignore

def load_gateway_config(config_path: str) -> GatewayConfig:
    """从 TOML 文件加载配置"""
    with open(config_path, "rb") as f:
        config = tomli.load(f)
    return config # type: ignore

if __name__ == "__main__":
    config = load_config("config.toml")
    logger.info("Loaded config: %s", config)
