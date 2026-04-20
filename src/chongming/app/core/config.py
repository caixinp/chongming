import sys
from pathlib import Path
from typing import TypedDict, Literal, Optional, cast, List


if sys.version_info >= (3, 11):
    import tomllib
    from typing import Required
else:
    import tomli as tomllib
    from typing_extensions import Required

# 设置 env 为 development 或 production


class DefaultApp(TypedDict):
    name: str
    version: str
    description: str
    debug: bool


class Default(TypedDict):
    app: DefaultApp
    env: Literal["production", "development"]
    prefix: str
    upload_path: str


class SqliteConnectionArgs(TypedDict, total=False):
    timeout: int
    check_same_thread: bool


class DatabaseSqlite(TypedDict, total=False):
    echo: bool
    pool_size: int
    max_overflow: int
    pool_timeout: int
    pool_recycle: int
    pool_pre_ping: bool
    connect_args: SqliteConnectionArgs


class Database(TypedDict, total=False):
    type: Required[Literal["sqlite", "mysql", "postgresql"]]
    url: Required[str]
    generate_schemas: bool
    sqlite: DatabaseSqlite
    mysql: dict
    postgresql: dict


class Security(TypedDict):
    secret_key: str
    algorithm: Literal["HS256"]
    access_token_expire_minutes: int
    refresh_token_expire_days: int
    max_sessions_per_user: int


class Server(TypedDict, total=False):
    host: Required[str]
    port: Required[int]
    reload: bool
    workers: int


class Logging(TypedDict):
    level: str
    file: str
    format: str
    max_size: int
    backup_count: int


class Cors(TypedDict, total=False):
    allow_origins: List[str]
    allow_credentials: bool
    allow_methods: List[str]
    allow_headers: List[str]


class ModuleSystem(TypedDict, total=False):
    type: str
    path: List[str]


class FileSystem(TypedDict, total=False):
    type: str
    path: str


class Env(TypedDict, total=False):
    debug: Required[bool]
    server: Required[Server]
    logging: Required[Logging]
    cors: Cors
    module_system: ModuleSystem
    file_system: FileSystem


class Scheduler(TypedDict):
    job_store_path: str


class Cache(TypedDict):
    cache_store_path: str


class Config(TypedDict):
    default: Default
    database: Database
    scheduler: Scheduler
    cache: Cache
    security: Security
    development: Env
    production: Env


def load_config(config_path: Path = Path("config.toml")) -> Config:
    """从 TOML 文件加载配置"""
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    with open(config_path, "rb") as f:
        return cast(Config, tomllib.load(f))


_config: Optional[Config] = None


def get_config(config_path: str = "config.toml") -> Config:
    global _config
    if _config is None:
        _config = load_config(Path(config_path))
    return _config
