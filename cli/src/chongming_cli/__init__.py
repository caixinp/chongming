"""
chongming CLI - 项目管理命令行工具
"""

import argparse
import sys
from .commands.new import add_new_parser, handle_new
from .commands.gen_models import add_gen_models_parser, handle_gen_models
from .commands.worker import add_worker_parser, handle_worker
from .commands.gateway import add_gateway_parser, handle_gateway
from .commands.docker_build import add_docker_build_parser, handle_docker_build
from .commands.binary_build import add_binary_build_parser, handle_binary_build
from .commands.docker import add_docker_parser, handle_docker
from .commands.image_export import add_image_export_parser, handle_image_export
from .commands.log_export import add_log_export_parser, handle_log_export
from .commands.migrate import add_db_parser, handle_db


def main():
    parser = argparse.ArgumentParser(
        description="chongming 项目管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # ── 项目脚手架 ──────────────────────────────────────────────
    add_new_parser(subparsers)
    add_gen_models_parser(subparsers)

    # ── 本地开发 ────────────────────────────────────────────────
    add_worker_parser(subparsers)
    add_gateway_parser(subparsers)

    # ── 构建与打包 ──────────────────────────────────────────────
    add_docker_build_parser(subparsers)
    add_binary_build_parser(subparsers)

    # ── 环境与运维 ──────────────────────────────────────────────
    add_docker_parser(subparsers)
    add_image_export_parser(subparsers)
    add_log_export_parser(subparsers)

    # ── 数据库迁移 ─────────────────────────────────────────────
    add_db_parser(subparsers)

    args = parser.parse_args()

    # ── 项目脚手架 ──
    if args.command == "new":
        handle_new(args)
    elif args.command == "gen-models":
        handle_gen_models(args)

    # ── 本地开发 ──
    elif args.command == "worker":
        handle_worker(args)
    elif args.command == "gateway":
        handle_gateway(args)

    # ── 构建与打包 ──
    elif args.command == "docker-build":
        handle_docker_build(args)
    elif args.command == "binary-build":
        handle_binary_build(args)

    # ── 环境与运维 ──
    elif args.command == "docker":
        handle_docker(args)
    elif args.command == "image-export":
        handle_image_export(args)
    elif args.command == "log-export":
        handle_log_export(args)

    # ── 数据库迁移 ──
    elif args.command == "db":
        handle_db(args)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
