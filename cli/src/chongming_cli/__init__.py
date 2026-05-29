"""
chongming CLI - 项目管理命令行工具
"""

import argparse
import sys
from .commands.new import add_new_parser, handle_new
from .commands.docker_build import add_docker_build_parser, handle_docker_build
from .commands.binary_build import add_binary_build_parser, handle_binary_build
from .commands.gateway import add_gateway_parser, handle_gateway
from .commands.worker import add_worker_parser, handle_worker
from .commands.docker import add_docker_parser, handle_docker
from .commands.image_export import add_image_export_parser, handle_image_export
from .commands.log_export import add_log_export_parser, handle_log_export


def main():
    parser = argparse.ArgumentParser(
        description="chongming 项目管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # new 命令
    add_new_parser(subparsers)

    # docker-build 命令（pip + Python 运行时模式，适合开发/CI）
    add_docker_build_parser(subparsers)

    # binary-build 命令（PyInstaller 单二进制模式，适合生产部署）
    add_binary_build_parser(subparsers)

    # gateway 命令（启动 API Gateway 开发服务器）
    add_gateway_parser(subparsers)

    # worker 命令（启动 worker 服务）
    add_worker_parser(subparsers)

    # docker 命令（Docker Compose 环境管理）
    add_docker_parser(subparsers)

    # image-export 命令（导出所有 Docker 镜像为 tar 包用于离线部署）
    add_image_export_parser(subparsers)

    # log-export 命令（从 MinIO 导出指定 worker/gateway 的日志）
    add_log_export_parser(subparsers)

    args = parser.parse_args()

    if args.command == "new":
        handle_new(args)
    elif args.command == "docker-build":
        handle_docker_build(args)
    elif args.command == "binary-build":
        handle_binary_build(args)
    elif args.command == "gateway":
        handle_gateway(args)
    elif args.command == "worker":
        handle_worker(args)
    elif args.command == "docker":
        handle_docker(args)
    elif args.command == "image-export":
        handle_image_export(args)
    elif args.command == "log-export":
        handle_log_export(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
