"""
chongming docker 命令 - Docker Compose 环境管理
"""

import argparse
import os
import subprocess
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
DOCKER_ENV_DIR = os.path.join(PROJECT_ROOT, "docker-env")
COMPOSE_FILE = os.path.join(DOCKER_ENV_DIR, "docker-compose.yml")
COMPOSE_PROD_FILE = os.path.join(DOCKER_ENV_DIR, "docker-compose.prod.yml")


def _ensure_docker_available():
    """检查 docker 和 docker compose 是否可用"""
    try:
        subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        try:
            subprocess.run(
                ["docker-compose", "--version"],
                capture_output=True,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("错误：未找到 docker compose 命令，请先安装 Docker")
            print("  参考：https://docs.docker.com/engine/install/")
            sys.exit(1)


def _ensure_compose_file_exists():
    """验证 docker-compose.yml 存在"""
    if not os.path.isfile(COMPOSE_FILE):
        print(f"错误：找不到 docker-compose.yml：{COMPOSE_FILE}")
        sys.exit(1)


def _build_compose_cmd(production: bool = False):
    """构建 docker compose 命令前缀"""
    cmd = ["docker", "compose"]

    if production:
        cmd.extend(["-f", COMPOSE_FILE, "-f", COMPOSE_PROD_FILE])
    else:
        cmd.extend(["-f", COMPOSE_FILE])

    return cmd


def _run_compose(args: list, production: bool = False, output: bool = True):
    """运行 docker compose 命令"""
    _ensure_docker_available()
    _ensure_compose_file_exists()

    cmd = _build_compose_cmd(production)
    cmd.extend(args)

    if output:
        print(f"执行: {' '.join(cmd)}")
        print()

    result = subprocess.run(cmd, cwd=DOCKER_ENV_DIR)

    if result.returncode != 0:
        print(f"\n错误：命令失败（退出码: {result.returncode}）")
        sys.exit(result.returncode)


def add_docker_parser(subparsers):
    parser = subparsers.add_parser(
        "docker",
        help="Docker Compose 环境管理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
子命令：
  up        启动开发环境（基础设施: NATS, PostgreSQL, MinIO）
  down      停止并清理环境
  ps        查看运行状态
  logs      查看服务日志
  restart   重启服务
  build     构建服务镜像

示例：
  # 启动开发环境（基础设施）
  chongming docker up

  # 启动生产环境（含 Nginx、多个 Gateway 实例、Workers）
  chongming docker up --production

  # 停止环境
  chongming docker down

  # 查看运行状态
  chongming docker ps

  # 查看指定服务的日志
  chongming docker logs nats-1
  chongming docker logs api-gateway-1 --tail 50 --follow

  # 重启服务
  chongming docker restart nats-1
        """,
    )
    subparsers_docker = parser.add_subparsers(dest="docker_command", help="docker 子命令")

    # docker up
    up_parser = subparsers_docker.add_parser("up", help="启动开发/生产环境")
    up_parser.add_argument(
        "--production",
        action="store_true",
        help="使用生产模式（叠加 docker-compose.prod.yml）",
    )
    up_parser.add_argument(
        "--build",
        action="store_true",
        help="启动前重新构建镜像",
    )
    up_parser.add_argument(
        "--detach",
        "-d",
        action="store_true",
        default=True,
        help="后台运行（默认启用）",
    )

    # docker down
    down_parser = subparsers_docker.add_parser("down", help="停止并清理环境")
    down_parser.add_argument(
        "--volumes",
        "-v",
        action="store_true",
        help="同时删除持久化数据卷",
    )
    down_parser.add_argument(
        "--production",
        action="store_true",
        help="使用生产模式",
    )

    # docker ps
    ps_parser = subparsers_docker.add_parser("ps", help="查看运行状态")
    ps_parser.add_argument(
        "--production",
        action="store_true",
        help="使用生产模式",
    )

    # docker logs
    logs_parser = subparsers_docker.add_parser("logs", help="查看服务日志")
    logs_parser.add_argument(
        "service",
        type=str,
        nargs="?",
        default=None,
        help="服务名称（如 nats-1、api-gateway-1），不指定则查看所有",
    )
    logs_parser.add_argument(
        "--tail",
        type=int,
        default=None,
        help="仅显示最后 N 行",
    )
    logs_parser.add_argument(
        "--follow",
        "-f",
        action="store_true",
        help="持续跟踪日志输出",
    )
    logs_parser.add_argument(
        "--production",
        action="store_true",
        help="使用生产模式",
    )

    # docker restart
    restart_parser = subparsers_docker.add_parser("restart", help="重启服务")
    restart_parser.add_argument(
        "service",
        type=str,
        nargs="?",
        default=None,
        help="服务名称（如 nats-1），不指定则重启所有",
    )
    restart_parser.add_argument(
        "--production",
        action="store_true",
        help="使用生产模式",
    )

    # docker build
    build_parser = subparsers_docker.add_parser("build", help="构建服务镜像")
    build_parser.add_argument(
        "service",
        type=str,
        nargs="?",
        default=None,
        help="服务名称（如 example-worker），不指定则构建所有",
    )
    build_parser.add_argument(
        "--no-cache",
        action="store_true",
        help="构建时不使用缓存",
    )
    build_parser.add_argument(
        "--production",
        action="store_true",
        help="使用生产模式",
    )


def handle_docker(args):
    """处理 docker 子命令"""
    if args.docker_command == "up":
        cmd_args = ["up", "-d"]

        if args.build:
            cmd_args.append("--build")

        # 显示启动提示
        print("正在启动 Docker Compose 环境 ...")
        print(f"  配置文件: {COMPOSE_FILE}")
        if args.production:
            print(f"  叠加配置: {COMPOSE_PROD_FILE}")
            print("  模式: 生产环境")
        else:
            print("  模式: 开发环境")
            print()
            print("将启动以下基础设施服务：")
            print("  - NATS 集群（3 节点，端口 4222/4223/4224）")
            print("  - PostgreSQL 主备（端口 5432/5433）")
            print("  - MinIO 分布式存储（端口 9000/9001）")
        print()

        _run_compose(cmd_args, production=args.production)
        print()
        print("环境已启动！运行以下命令查看状态：")
        print("  chongming docker ps           # 查看运行状态")
        print("  chongming docker logs <svc>   # 查看日志")

    elif args.docker_command == "down":
        cmd_args = ["down"]

        if args.volumes:
            cmd_args.append("-v")

        print("正在停止 Docker Compose 环境 ...")
        _run_compose(cmd_args, production=args.production)
        print("环境已停止。")

    elif args.docker_command == "ps":
        print("Docker Compose 运行状态：")
        print()
        _run_compose(["ps"], production=args.production)

    elif args.docker_command == "logs":
        cmd_args = ["logs"]

        if args.tail:
            cmd_args.extend(["--tail", str(args.tail)])
        if args.follow:
            cmd_args.append("--follow")
        if args.service:
            cmd_args.append(args.service)

        _run_compose(cmd_args, production=args.production)

    elif args.docker_command == "restart":
        cmd_args = ["restart"]

        if args.service:
            cmd_args.append(args.service)
            print(f"正在重启服务: {args.service} ...")
        else:
            print("正在重启所有服务 ...")

        _run_compose(cmd_args, production=args.production)
        print("重启完成。")

    elif args.docker_command == "build":
        cmd_args = ["build"]

        if args.no_cache:
            cmd_args.append("--no-cache")
        if args.service:
            cmd_args.append(args.service)
            print(f"正在构建服务镜像: {args.service} ...")
        else:
            print("正在构建所有服务镜像 ...")

        _run_compose(cmd_args, production=args.production)
        print("构建完成。")

    else:
        print("请指定 docker 子命令：up | down | ps | logs | restart | build")
        print("使用 chongming docker --help 查看更多信息")
        sys.exit(1)
