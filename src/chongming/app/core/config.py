import sys
from pathlib import Path
from typing import TypedDict, Literal, Optional, cast, List


# 根据Python版本选择合适的TOML解析库和Required类型
if sys.version_info >= (3, 11):
    import tomllib
    from typing import Required
else:
    import tomli as tomllib
    from typing_extensions import Required

# 设置 env 为 development 或 production


class DefaultApp(TypedDict):
    """应用默认配置结构"""

    name: str
    version: str
    description: str
    debug: bool


class Default(TypedDict):
    """系统默认配置结构，包含应用信息、环境、路径等基础配置"""

    app: DefaultApp
    env: Literal["production", "development"]
    prefix: str
    upload_path: str


class SqliteConnectionArgs(TypedDict, total=False):
    """SQLite数据库连接参数配置"""

    timeout: int
    check_same_thread: bool


class DatabaseSqlite(TypedDict, total=False):
    """SQLite数据库连接池及行为配置"""

    echo: bool
    pool_size: int
    max_overflow: int
    pool_timeout: int
    pool_recycle: int
    pool_pre_ping: bool
    connect_args: SqliteConnectionArgs


class Database(TypedDict, total=False):
    """数据库配置结构，支持SQLite、MySQL、PostgreSQL三种数据库类型"""

    type: Required[Literal["sqlite", "mysql", "postgresql"]]
    url: Required[str]
    generate_schemas: bool
    sqlite: DatabaseSqlite
    mysql: dict
    postgresql: dict


class Security(TypedDict):
    """安全相关配置，包括JWT令牌和安全策略设置"""

    secret_key: str
    algorithm: Literal["HS256"]
    access_token_expire_minutes: int
    refresh_token_expire_days: int
    max_sessions_per_user: int


class Server(TypedDict, total=False):
    """服务器运行配置，包含主机、端口、工作进程等设置"""

    host: Required[str]
    port: Required[int]
    reload: bool
    workers: int
    access_log: bool


class Logging(TypedDict):
    """日志系统配置，定义日志级别、输出格式和文件管理策略"""

    level: str
    file: str
    format: str
    max_size: int
    backup_count: int


class Cors(TypedDict, total=False):
    """跨域资源共享(CORS)配置"""

    allow_origins: List[str]
    allow_credentials: bool
    allow_methods: List[str]
    allow_headers: List[str]


class ModuleSystem(TypedDict, total=False):
    """模块系统配置，定义模块加载类型和路径"""

    type: str
    path: List[str]


class FileSystem(TypedDict, total=False):
    """文件系统配置，定义存储类型和路径"""

    type: str
    path: str


class Env(TypedDict, total=False):
    """环境特定配置结构，用于开发和生产环境的差异化配置"""

    debug: Required[bool]
    server: Required[Server]
    logging: Required[Logging]
    cors: Cors
    module_system: ModuleSystem
    file_system: FileSystem


class Scheduler(TypedDict):
    """任务调度器配置"""

    job_store_path: str


class Cache(TypedDict):
    """缓存系统配置"""

    cache_store_path: str


class Config(TypedDict):
    """完整配置结构，整合所有配置项，包含默认配置、数据库、调度器、缓存、安全和环境配置"""

    default: Default
    database: Database
    scheduler: Scheduler
    cache: Cache
    security: Security
    development: Env
    production: Env


def load_config(config_path: Path = Path("config.toml")) -> Config:
    """
    从TOML配置文件加载配置数据

    Args:
        config_path: 配置文件路径，默认为当前目录下的config.toml

    Returns:
        Config: 解析后的配置字典对象

    Raises:
        FileNotFoundError: 当配置文件不存在时抛出异常
    """
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    with open(config_path, "rb") as f:
        return cast(Config, tomllib.load(f))


# 全局配置缓存变量，避免重复加载配置文件
_config: Optional[Config] = None


def get_config(config_path: str = "config.toml") -> Config:
    """
    获取应用程序配置（带缓存机制）

    首次调用时加载配置文件并缓存，后续调用直接返回缓存的配置对象

    Args:
        config_path: 配置文件路径，默认为config.toml

    Returns:
        Config: 配置字典对象
    """
    global _config
    if _config is None:
        _config = load_config(Path(config_path))
    return _config
