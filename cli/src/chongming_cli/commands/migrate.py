"""
Database Migration 命令
=======================

通过 Alembic 管理数据库迁移，支持：

- ``chongming db init``       — 创建基线迁移（基于当前 SQLModel 模型自动生成）
- ``chongming db migrate``    — 生成新的迁移脚本（自动检测模型变化）
- ``chongming db upgrade``    — 应用所有待执行的迁移
- ``chongming db downgrade``  — 回滚到上一个版本
- ``chongming db history``    — 查看迁移历史
- ``chongming db current``    — 查看当前数据库版本
- ``chongming db sql``        — 离线生成 SQL 脚本（不连接数据库）
"""

import argparse
import os
import sys
from pathlib import Path

# Alembic 的目录（位于项目根目录 utils/python/database 下）
# 从 cli/src/chongming_cli/commands/migrate.py 到项目根需要 4 层
_ALEMBIC_DIR = Path(__file__).resolve().parents[4] / "utils" / "python" / "database"
_ALEMBIC_INI = _ALEMBIC_DIR / "alembic.ini"


def _run_alembic(args_list: list[str], db_url: str | None = None) -> None:
    """在 Alembic 目录下执行 alembic 命令

    Parameters
    ----------
    args_list : list[str]
        Alembic 命令参数（如 ["revision", "--autogenerate", "-m", "msg"]）
    db_url : str or None
        数据库连接 URL。当需要连接数据库（如 autogenerate）时必须提供。
        如果为 None 且命令需要连接数据库，将尝试从 ``alembic.ini`` 读取或报错。
    """
    if not _ALEMBIC_INI.exists():
        print(f"错误: 未找到 Alembic 配置文件 ({_ALEMBIC_INI})")
        print("请确保 utils/python/database/ 目录下包含 alembic.ini")
        sys.exit(1)

    from alembic.config import Config
    from alembic import command
    from alembic.script import ScriptDirectory


    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR / "migrations"))

    # 如果传入了 db_url，覆盖配置中的 URL
    if db_url is not None:
        cfg.set_main_option("sqlalchemy.url", db_url)

    # 根据命令行参数调用对应 Alembic 命令
    action = args_list[0]
    kwargs = _parse_alembic_kwargs(args_list[1:])

    if action == "revision":
        command.revision(cfg, **kwargs)
    elif action == "upgrade":
        command.upgrade(cfg, kwargs.get("revision", "head"))
    elif action == "downgrade":
        command.downgrade(cfg, kwargs.get("revision", "-1"))
    elif action == "history":
        command.history(cfg)
    elif action == "current":
        command.current(cfg)
    elif action == "stamp":
        command.stamp(cfg, kwargs.get("revision", "head"))


def _parse_alembic_kwargs(raw_args: list[str]) -> dict:
    """将 alembic 参数列表解析为关键字参数字典"""
    kwargs: dict = {}
    i = 0
    while i < len(raw_args):
        arg = raw_args[i]
        if arg == "--autogenerate":
            kwargs["autogenerate"] = True
        elif arg == "--sql":
            kwargs["sql"] = True
        elif arg in ("-m", "--message"):
            i += 1
            if i < len(raw_args):
                kwargs["message"] = raw_args[i]
        elif not arg.startswith("-"):
            # 位置参数：revision
            kwargs["revision"] = arg
        i += 1
    return kwargs


# ── Parser 注册 ────────────────────────────────────────────────────


def add_db_parser(subparsers) -> None:
    """注册 ``db`` 子命令及其子命令"""
    parser = subparsers.add_parser(
        "db",
        help="数据库迁移管理（基于 Alembic）",
        description="数据库迁移管理：自动检测模型变化，生成并执行迁移脚本",
    )
    db_sub = parser.add_subparsers(dest="db_command", help="db 子命令")

    # init — 创建基线迁移
    p_init = db_sub.add_parser(
        "init",
        help="创建基线迁移（首次迁移，标记当前表结构）",
        description="基于当前 SQLModel 模型创建初始迁移。首次使用或重建迁移时执行。",
    )
    p_init.add_argument(
        "-m", "--message",
        default="initial migration",
        help="迁移描述信息（默认: initial migration）",
    )
    p_init.add_argument(
        "--db-url",
        required=True,
        help="数据库连接 URL，例如 postgresql://user:pass@host:port/dbname",
    )

    # migrate — 生成新的迁移脚本
    p_migrate = db_sub.add_parser(
        "migrate",
        help="生成新的迁移脚本（自动检测模型变化）",
        description="对比当前 SQLModel 模型与数据库实际结构，自动生成迁移脚本。",
    )
    p_migrate.add_argument(
        "-m", "--message",
        default="auto migration",
        help="迁移描述信息（默认: auto migration）",
    )
    p_migrate.add_argument(
        "--db-url",
        required=True,
        help="数据库连接 URL，例如 postgresql://user:pass@host:port/dbname",
    )

    # upgrade — 应用迁移
    p_upgrade = db_sub.add_parser(
        "upgrade",
        help="应用迁移到指定版本",
        description="执行迁移，将数据库更新到目标版本。",
    )
    p_upgrade.add_argument(
        "revision",
        nargs="?",
        default="head",
        help="目标版本号，默认为 head（最新版本）",
    )
    p_upgrade.add_argument(
        "--sql", action="store_true",
        help="仅输出 SQL 脚本，不实际执行",
    )

    # downgrade — 回滚迁移
    p_downgrade = db_sub.add_parser(
        "downgrade",
        help="回滚迁移（降级数据库）",
        description="回滚到指定版本，用于撤销迁移。",
    )
    p_downgrade.add_argument(
        "revision",
        nargs="?",
        default="-1",
        help="目标版本号，默认为 -1（回滚一步）",
    )
    p_downgrade.add_argument(
        "--sql", action="store_true",
        help="仅输出 SQL 脚本，不实际执行",
    )

    # history — 查看迁移历史
    db_sub.add_parser(
        "history",
        help="查看迁移历史记录",
        description="显示所有迁移脚本及其依赖关系。",
    )

    # current — 查看当前版本
    p_current = db_sub.add_parser(
        "current",
        help="查看数据库当前的迁移版本",
        description="显示数据库当前处于哪个迁移版本。",
    )
    p_current.add_argument(
        "--db-url",
        required=True,
        help="数据库连接 URL",
    )

    # stamp — 标记版本
    p_stamp = db_sub.add_parser(
        "stamp",
        help="将数据库标记为指定迁移版本（不实际执行迁移）",
        description="将数据库的 alembic_version 表设置为指定版本。适用于初始化已存在的数据库。",
    )
    p_stamp.add_argument(
        "revision",
        nargs="?",
        default="head",
        help="目标版本号，默认为 head（最新版本）",
    )
    p_stamp.add_argument(
        "--db-url",
        required=True,
        help="数据库连接 URL",
    )

    # sql — 离线生成 SQL（等价于 upgrade --sql）
    p_sql = db_sub.add_parser(
        "sql",
        help="离线生成 SQL 脚本",
        description="在不连接数据库的情况下，生成从当前版本到目标版本的 SQL 脚本。",
    )
    p_sql.add_argument(
        "revision",
        nargs="?",
        default="head",
        help="目标版本号，默认为 head",
    )


# ── Handler ────────────────────────────────────────────────────────


def handle_db(args) -> None:
    """处理 ``db`` 子命令"""
    db_cmd = args.db_command

    if db_cmd == "init":
        _handle_init(args)
    elif db_cmd == "migrate":
        _handle_migrate(args)
    elif db_cmd == "upgrade":
        _handle_upgrade(args)
    elif db_cmd == "downgrade":
        _handle_downgrade(args)
    elif db_cmd == "history":
        _run_alembic(["history"])
    elif db_cmd == "current":
        _run_alembic(["current"], db_url=args.db_url)
    elif db_cmd == "stamp":
        _handle_stamp(args)
    elif db_cmd == "sql":
        _handle_sql(args)
    else:
        print("请指定 db 子命令（init/migrate/upgrade/downgrade/history/current/sql）")


def _handle_init(args) -> None:
    """初始化 Alembic + 创建基线迁移"""
    print("正在创建基线迁移...")

    alembic_args = [
        "revision",
        "--autogenerate",
        "-m", args.message,
    ]

    _run_alembic(alembic_args, db_url=args.db_url)


def _handle_migrate(args) -> None:
    """检测模型变化并生成迁移脚本"""
    print("正在检测模型变化并生成迁移脚本...")

    alembic_args = [
        "revision",
        "--autogenerate",
        "-m", args.message,
    ]

    _run_alembic(alembic_args, db_url=args.db_url)


def _handle_upgrade(args) -> None:
    """应用迁移"""
    print(f"正在应用迁移到版本: {args.revision}...")

    alembic_args = [
        "upgrade",
        args.revision,
    ]
    if args.sql:
        alembic_args.append("--sql")

    _run_alembic(alembic_args)


def _handle_downgrade(args) -> None:
    """回滚迁移"""
    print(f"正在回滚迁移到版本: {args.revision}...")

    alembic_args = [
        "downgrade",
        args.revision,
    ]
    if args.sql:
        alembic_args.append("--sql")

    _run_alembic(alembic_args)


def _handle_stamp(args) -> None:
    """标记数据库版本"""
    print(f"正在标记数据库为版本: {args.revision}...")

    alembic_args = [
        "stamp",
        args.revision,
    ]

    _run_alembic(alembic_args, db_url=args.db_url)


def _handle_sql(args) -> None:
    """离线生成 SQL 脚本"""
    print(f"正在生成 SQL 脚本（到版本: {args.revision}）...")

    alembic_args = [
        "upgrade",
        args.revision,
        "--sql",
    ]

    _run_alembic(alembic_args)
