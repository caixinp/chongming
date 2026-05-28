"""
chongming gateway 命令 - 启动 API Gateway（Uvicorn 开发服务器）
"""

import argparse
import os
import subprocess
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))


def add_gateway_parser(subparsers):
    parser = subparsers.add_parser(
        "gateway",
        help="启动 API Gateway 开发服务器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 启动 API Gateway（默认地址 0.0.0.0:8000，热重载）
  chongming gateway

  # 指定主机和端口启动
  chongming gateway --host 127.0.0.1 --port 8080

  # 生产模式启动（Gunicorn + 多进程）
  chongming gateway --production
        """,
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="监听地址（默认: 0.0.0.0）",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=None,
        help="监听端口（默认: 8000）",
    )
    parser.add_argument(
        "--production",
        action="store_true",
        help="使用 Gunicorn 生产模式启动（多进程，无热重载）",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        default=None,
        help="启用热重载（开发时自动重启）",
    )
    parser.add_argument(
        "--no-reload",
        action="store_true",
        default=None,
        help="禁用热重载",
    )


def handle_gateway(args):
    """启动 API Gateway"""
    gateway_dir = os.path.join(PROJECT_ROOT, "api_gateway")
    if not os.path.isdir(gateway_dir):
        print(f"错误：找不到 api_gateway 目录：{gateway_dir}")
        sys.exit(1)

    # 构建 uv run 命令
    cmd = ["uv", "run", "--directory", "api_gateway"]

    if args.production:
        cmd.append("gunicorn")
    else:
        cmd.append("serve")

    # 添加额外参数
    extra_args = []
    if args.host:
        extra_args.extend(["--host", args.host])
    if args.port:
        extra_args.extend(["--port", str(args.port)])
    if args.reload:
        extra_args.append("--reload")
    if args.no_reload:
        extra_args.append("--no-reload")

    cmd.extend(extra_args)

    print(f"正在启动 API Gateway ...")
    print(f"  工作目录: {PROJECT_ROOT}")
    print(f"  命令: {' '.join(cmd)}")
    print()

    try:
        result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    except KeyboardInterrupt:
        print("\nAPI Gateway 已停止。")
        sys.exit(0)

    if result.returncode != 0:
        print(f"\n错误：API Gateway 启动失败（退出码: {result.returncode}）")
        sys.exit(result.returncode)
