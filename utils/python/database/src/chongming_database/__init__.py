"""
Database 初始化工具（读写分离版本）
====================================

提供数据库连接的初始化、会话管理及建表逻辑。
封装了从网关配置中读取数据库连接信息、创建数据库、
建立主库（写）和从库（读）异步引擎、创建表等全流程，
供 worker 中的 modules（如 listeners、handlers）调用。

支持主从读写分离：
- ``get_db_session_master()`` → 写操作（INSERT/UPDATE/DELETE）
- ``get_db_session_slave()``  → 读操作（SELECT）
- ``get_db_session()``        → 默认返回主库（向后兼容）

高级用法：通过装饰器 + 上下文变量实现自动路由
    @read_only
    async def my_handler(input):
        async for session in get_db_session():  # 自动使用从库
            ...
"""

import json
import logging
from contextvars import ContextVar
from functools import wraps
from typing import AsyncGenerator, Optional, Callable, Any

from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncEngine
from sqlalchemy import inspect as sa_inspect, text
import asyncpg

from chongming_cache import ChongmingCache
from chongming_config import load_config

logger = logging.getLogger(__name__)
_worker_config = load_config("config.toml")

# ── 全局状态 ──────────────────────────────────────────────────────
_db_engine_master: Optional[AsyncEngine] = None
_db_engine_slave: Optional[AsyncEngine] = None
_sessionmaker_master: Optional[async_sessionmaker] = None
_sessionmaker_slave: Optional[async_sessionmaker] = None

# ── 自动路由上下文变量 ──────────────────────────────────────────
_readonly_mode: ContextVar[bool] = ContextVar("readonly_mode", default=False)


def set_readonly_mode(val: bool) -> None:
    """设置只读模式标志（用于自动路由装饰器）"""
    _readonly_mode.set(val)


async def _ensure_db_exists(
    cfg: dict,
    db_name: str,
    host: str,
    port: str,
    username: str,
    password: str,
) -> None:
    """确保目标数据库存在，不存在则创建"""
    try:
        conn = await asyncpg.connect(
            user=username,
            password=password,
            host=host,
            port=port,
            database="postgres",
        )
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1",
            db_name,
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{db_name}"')
            logger.info("Created database: %s", db_name)
        else:
            logger.info("Database already exists: %s", db_name)
        await conn.close()
    except Exception as e:
        logger.warning("Failed to create database (may already exist): %s", e)


def _build_async_engine(
    url: str,
    pool_config: dict,
) -> AsyncEngine:
    """根据池配置创建异步引擎"""
    if len(pool_config) == 0:
        return create_async_engine(url, echo=False, future=True)
    return create_async_engine(
        url,
        echo=pool_config.get("echo", False),
        future=True,
        pool_size=pool_config.get("pool_size", 10),
        max_overflow=pool_config.get("max_overflow", 20),
        pool_timeout=pool_config.get("pool_timeout", 30),
        pool_recycle=pool_config.get("pool_recycle", -1),
        pool_pre_ping=pool_config.get("pool_pre_ping", True),
    )


async def _create_engine_and_tables(
    cfg: dict,
    db_name: str,
    pool_config: dict,
    is_master: bool,
) -> tuple[AsyncEngine, async_sessionmaker]:
    """创建引擎、会话工厂，并建表（仅主库执行建表）"""
    url = (
        f"postgresql+asyncpg://{cfg['username']}"
        f":{cfg['password']}@{cfg['host']}:"
        f"{cfg['port']}/{db_name}"
    )
    engine = _build_async_engine(url, pool_config)
    sessionmaker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # 仅主库执行建表 + 自动迁移操作
    if is_master:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(
                    lambda sync_conn: SQLModel.metadata.create_all(
                        bind=sync_conn,
                        checkfirst=True,
                    )
                )
            logger.info("Database tables created or verified (master)")

            # ── 自动迁移：检查并修正列类型不匹配 ────────────
            await _auto_migrate_columns(engine, db_name)

        except Exception as e:
            logger.warning("Failed to create tables (will be created on first use): %s", e)

    return engine, sessionmaker


async def init_database(
    listener_cache: Optional[ChongmingCache],
    gateway_config: Optional[dict] = None,
) -> None:
    """从网关配置初始化主库和从库数据库连接

    如果传入了 ``gateway_config`` 则直接使用，否则从 KV 存储中获取。
    每次初始化时会先 dispose 旧引擎，防止连接池泄漏。

    Parameters
    ----------
    listener_cache : ChongmingCache or None
        KV 存储连接实例，用于在未提供 ``gateway_config`` 时拉取配置。
        如果为 ``None`` 且未提供 ``gateway_config``，则无法初始化。
    gateway_config : dict or None
        预解析的网关配置。如果提供，则直接使用，不再读取 KV 存储。
    """
    global _db_engine_master, _db_engine_slave
    global _sessionmaker_master, _sessionmaker_slave
    try:
        # ── 解析配置 ──────────────────────────────────────────
        if gateway_config is None:
            if listener_cache is None:
                logger.error("Cannot initialize DB: no config provided and no cache connection")
                _sessionmaker_master = None
                _sessionmaker_slave = None
                return
            raw_entry = await listener_cache.get("gateway_config")
            if raw_entry is not None and raw_entry.value is not None:
                gateway_config = json.loads(raw_entry.value.decode())
            else:
                gateway_config = None

        if gateway_config is None:
            logger.warning("No gateway config found, database not initialized")
            _sessionmaker_master = None
            _sessionmaker_slave = None
            return

        db_config = gateway_config.get("database", {})
        db_type = db_config.get("type")
        if db_type != "pgsql":
            logger.warning("Unsupported database type: %s", db_type)
            _sessionmaker_master = None
            _sessionmaker_slave = None
            return

        db_name = _worker_config.get("worker", {}).get("name", "default")
        pool_config = _worker_config.get("database", {}).get("pool", {})

        # ── 主库配置（写） ────────────────────────────────────
        master_cfg = db_config.get("master")
        if master_cfg is None:
            logger.error("No master database configuration found")
            _sessionmaker_master = None
            _sessionmaker_slave = None
            return

        # 确保数据库存在（用主库创建）
        await _ensure_db_exists(
            master_cfg, db_name,
            master_cfg["host"], master_cfg["port"],
            master_cfg["username"], master_cfg["password"],
        )

        # Dispose previous engines before creating new ones
        if _db_engine_master is not None:
            await _db_engine_master.dispose()
            _db_engine_master = None
        if _db_engine_slave is not None:
            await _db_engine_slave.dispose()
            _db_engine_slave = None

        # 创建主库引擎
        _db_engine_master, _sessionmaker_master = await _create_engine_and_tables(
            master_cfg, db_name, pool_config, is_master=True,
        )
        logger.info(
            "Master database configured (host=%s:%s, db=%s)",
            master_cfg["host"], master_cfg["port"], db_name,
        )

        # ── 从库配置（读） ────────────────────────────────────
        slave_cfg = db_config.get("slave")
        if slave_cfg is not None:
            _db_engine_slave, _sessionmaker_slave = await _create_engine_and_tables(
                slave_cfg, db_name, pool_config, is_master=False,
            )
            logger.info(
                "Slave database configured (host=%s:%s, db=%s)",
                slave_cfg["host"], slave_cfg["port"], db_name,
            )
        else:
            logger.warning("No slave database configuration found, using master for all operations")
            _db_engine_slave = _db_engine_master
            _sessionmaker_slave = _sessionmaker_master

    except Exception as e:
        logger.error("Failed to initialize database: %s", e, exc_info=True)
        # Don't leave sessionmaker in a broken state
        _sessionmaker_master = None
        _sessionmaker_slave = None
        _db_engine_master = None
        _db_engine_slave = None


# ── 会话获取函数 ──────────────────────────────────────────────────


async def get_db_session_master() -> AsyncGenerator[AsyncSession, None]:
    """获取主库数据库会话（用于写操作：INSERT/UPDATE/DELETE）

    如果 ``_sessionmaker_master`` 尚未初始化，会自动调用
    :func:`init_database` 进行初始化。初始化失败时抛出
    ``RuntimeError``。

    Yields
    ------
    AsyncSession
        主库数据库异步会话，退出上下文时自动关闭。
    """
    global _sessionmaker_master
    if _sessionmaker_master is None:
        async with ChongmingCache(logger, bucket="_gw_config_") as cache:
            await init_database(cache)
    if _sessionmaker_master is None:
        raise RuntimeError("Database (master) not initialized")
    async with _sessionmaker_master() as session:
        yield session


async def get_db_session_slave() -> AsyncGenerator[AsyncSession, None]:
    """获取从库数据库会话（用于读操作：SELECT）

    如果 ``_sessionmaker_slave`` 尚未初始化，会自动调用
    :func:`init_database` 进行初始化。初始化失败时抛出
    ``RuntimeError``。

    当从库不可用时，会自动回退到主库。

    Yields
    ------
    AsyncSession
        从库数据库异步会话，退出上下文时自动关闭。
    """
    global _sessionmaker_slave
    if _sessionmaker_slave is None:
        async with ChongmingCache(logger, bucket="_gw_config_") as cache:
            await init_database(cache)
    if _sessionmaker_slave is None:
        raise RuntimeError("Database (slave) not initialized")
    async with _sessionmaker_slave() as session:
        yield session


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话（自动路由版本）

    如果设置了只读模式（通过 :func:`set_readonly_mode` 或
    :func:`read_only` 装饰器），则返回从库会话，否则返回主库会话。

    如果会话工厂尚未初始化，会自动调用
    :func:`init_database` 进行初始化。初始化失败时抛出
    ``RuntimeError``。

    此函数保持向后兼容 —— 已有代码调用 ``get_db_session()``
    默认使用主库（写）会话。

    Yields
    ------
    AsyncSession
        数据库异步会话，退出上下文时自动关闭。
    """
    if _readonly_mode.get():
        async for session in get_db_session_slave():
            yield session
    else:
        async for session in get_db_session_master():
            yield session


# ── 自动迁移：ORM 级别的列类型检查 ──────────────────────────────


# ── 自动迁移配置 ──────────────────────────────────────────────
# key: SQLModel 列类型类名, value: 目标 SQL 类型名
# 当模型列类型定义为此 key 时，将数据库实际类型对齐到 value
_TYPE_MAP = {
    "BigInteger": "BIGINT",
}


async def _auto_migrate_columns(engine: AsyncEngine, db_name: str) -> None:
    """自动迁移：检查 SQLModel 列类型与数据库是否匹配，不匹配则 ALTER

    对比 ``SQLModel.metadata`` 中定义的表列类型与数据库中实际列类型，
    如果发现不匹配，自动执行 ``ALTER TABLE ... ALTER COLUMN ... TYPE ...``
    来修正，保证原数据完整无损。

    支持的迁移：
    - ``BigInteger → BIGINT``（用于 Snowflake 64 位 ID 的场景）
    """
    async with engine.begin() as conn:
        # 遍历所有 SQLModel 表
        for table_name, table in SQLModel.metadata.tables.items():
            for column in table.columns:
                # 获取 SQLModel 定义的 SQL 类型类名
                model_type_name = column.type.__class__.__name__

                # 如果模型定义的类型不在迁移映射中，跳过
                if model_type_name not in _TYPE_MAP:
                    continue

                target_type = _TYPE_MAP[model_type_name]

                # 用 inspector 获取数据库实际列信息
                def _get_column_info(sync_conn):
                    inspector = sa_inspect(sync_conn)
                    columns_info = inspector.get_columns(table_name)
                    for col in columns_info:
                        if col["name"] == column.name:
                            return col
                    return None

                db_col = await conn.run_sync(_get_column_info)
                if db_col is None:
                    continue

                # 获取数据库实际类型（标准化为大写）
                db_type = str(db_col["type"]).upper()

                if db_type != target_type:
                    logger.warning(
                        "自动迁移: %s.%s 类型不匹配 (当前: %s, 目标: %s)",
                        table_name, column.name, db_type, target_type,
                    )
                    await conn.execute(text(
                        f'ALTER TABLE "{table_name}" ALTER COLUMN "{column.name}" TYPE {target_type}'
                    ))
                    logger.info(
                        "自动迁移成功: %s.%s → %s",
                        table_name, column.name, target_type,
                    )


# ── 自动路由装饰器 ──────────────────────────────────────────────


def read_only(func: Callable[..., Any]) -> Callable[..., Any]:
    """装饰器：标记 handler 为只读操作

    被装饰的函数中调用 ``get_db_session()`` 将自动使用从库会话。

    用法::

        @app.handler("user.list")
        @read_only
        async def list_users(input):
            async for session in get_db_session():
                # 自动使用从库
                ...
    """
    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        set_readonly_mode(True)
        try:
            return await func(*args, **kwargs)
        finally:
            set_readonly_mode(False)
    return wrapper


# ── 导出符号 ──────────────────────────────────────────────────────

__all__ = [
    "init_database",
    "get_db_session",
    "get_db_session_master",
    "get_db_session_slave",
    "set_readonly_mode",
    "read_only",
    "_sessionmaker_master",
    "_sessionmaker_slave",
]
