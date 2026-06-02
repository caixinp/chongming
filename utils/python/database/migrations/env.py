"""Alembic migrations environment — 自动发现所有 Worker 的 SQLModel 模型"""

import sys
from pathlib import Path
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

from alembic import context

# Alembic Config object
config = context.config

# 日志配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── 将项目根目录加入 sys.path ──
_project_root = Path(__file__).resolve().parents[4]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# ── 自动发现并导入所有 Worker 的数据库模型 ──
# 遍历 workers/ 下所有子目录，汇总每个 Worker 的 database_models 模块
# 各 Worker 在其 app/database_models/__init__.py 中定义 SQLModel 子类，
# 导入即会自动注册到 SQLModel.metadata
_workers_dir = _project_root / "workers"
if _workers_dir.exists():
    for worker_dir in sorted(_workers_dir.iterdir()):
        if not worker_dir.is_dir() or worker_dir.name.startswith("_"):
            continue
        # 尝试导入 workers.<name>.app.database_models
        module_name = f"workers.{worker_dir.name}.app.database_models"
        try:
            __import__(module_name)
        except ImportError:
            # 可能没有 database_models 模块，跳过
            pass

# 供 autogenerate 使用的 target_metadata
target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """离线模式：仅生成 SQL 脚本，不连接数据库"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连接数据库执行迁移"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
