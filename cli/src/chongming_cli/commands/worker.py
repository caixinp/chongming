"""
chongming worker 命令 - 启动 worker 服务
"""

import argparse
import os
import subprocess
import sys
import signal


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
WORKERS_DIR = os.path.join(PROJECT_ROOT, "workers")


def _list_workers():
    """列出可用的 worker 名称"""
    workers = []
    if os.path.isdir(WORKERS_DIR):
        for name in sorted(os.listdir(WORKERS_DIR)):
            worker_dir = os.path.join(WORKERS_DIR, name)
            main_py = os.path.join(worker_dir, "main.py")
            if os.path.isdir(worker_dir) and not name.startswith(".") and os.path.isfile(main_py):
                workers.append(name)
    return workers


def _ensure_worker_exists(name: str):
    """验证 worker 目录和 main.py 存在"""
    worker_dir = os.path.join(WORKERS_DIR, name)
    main_py = os.path.join(worker_dir, "main.py")

    if not os.path.isdir(worker_dir):
        print(f"错误：找不到 worker '{name}'，目录不存在：{worker_dir}")
        workers = _list_workers()
        if workers:
            print("可用的 worker：")
            for w in workers:
                print(f"  - {w}")
        sys.exit(1)

    if not os.path.isfile(main_py):
        print(f"错误：worker '{name}' 缺少 main.py 入口文件：{main_py}")
        sys.exit(1)


def _start_worker(name: str, background: bool = False):
    """启动单个 worker"""
    worker_dir = os.path.join(WORKERS_DIR, name)

    cmd = ["uv", "run", "--directory", f"workers/{name}", "python", "main.py"]

    if background:
        print(f"  正在启动 worker [{name}]（后台）...")
        process = subprocess.Popen(
            cmd,
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"  PID: {process.pid}")
        return process
    else:
        print(f"  正在启动 worker [{name}] ...")
        print(f"  命令: {' '.join(cmd)}")
        print()

        result = subprocess.run(cmd, cwd=PROJECT_ROOT)

        if result.returncode != 0:
            print(f"\n错误：worker '{name}' 启动失败（退出码: {result.returncode}）")
            sys.exit(result.returncode)


def _start_all_workers():
    """启动所有 worker（每个 worker 在后台运行）"""
    workers = _list_workers()
    if not workers:
        print("没有找到可用的 worker")
        return

    print(f"正在启动所有 worker（共 {len(workers)} 个）...")
    print()

    processes = {}
    for name in workers:
        proc = _start_worker(name, background=True)
        processes[name] = proc

    print()
    print("所有 worker 已启动：")
    for name, proc in processes.items():
        print(f"  [{name}] PID {proc.pid}")

    print()
    print("按 Ctrl+C 停止所有 worker。")

    # 捕获 SIGINT/SIGTERM 以优雅关闭所有子进程
    def _shutdown(signum, frame):
        print()
        print("正在停止所有 worker ...")
        for name, proc in processes.items():
            if proc.poll() is None:
                proc.terminate()
                print(f"  [{name}] 已发送终止信号")
        for name, proc in processes.items():
            try:
                proc.wait(timeout=10)
                print(f"  [{name}] 已停止")
            except subprocess.TimeoutExpired:
                proc.kill()
                print(f"  [{name}] 已强制停止")
        print("所有 worker 已停止。")
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # 等待所有子进程结束
    try:
        for proc in processes.values():
            proc.wait()
    except KeyboardInterrupt:
        _shutdown(None, None)


def add_worker_parser(subparsers):
    parser = subparsers.add_parser(
        "worker",
        help="启动 worker 服务",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 启动指定 worker
  chongming worker example

  # 启动所有 worker
  chongming worker --all

  # 查看可用的 worker
  chongming worker --list
        """,
    )
    parser.add_argument(
        "name",
        type=str,
        nargs="?",
        default=None,
        help="worker 名称（对应 workers/ 下的子目录名）",
    )
    parser.add_argument(
        "--all",
        "-a",
        action="store_true",
        help="启动所有 worker",
    )
    parser.add_argument(
        "--list",
        "-l",
        action="store_true",
        help="列出所有可用的 worker",
    )


def handle_worker(args):
    """处理 worker 启动"""
    # 列出可用的 worker
    if args.list:
        workers = _list_workers()
        if workers:
            print("可用的 worker：")
            for name in workers:
                print(f"  - {name}")
        else:
            print("没有找到可用的 worker")
        return

    # 启动所有 worker
    if args.all:
        _start_all_workers()
        return

    # 启动指定 worker
    if args.name:
        _ensure_worker_exists(args.name)
        _start_worker(args.name)
        return

    # 未指定任何参数
    print("请指定要启动的 worker 名称，或使用 --all 启动所有 worker")
    print()
    workers = _list_workers()
    if workers:
        print("可用的 worker：")
        for name in workers:
            print(f"  - {name}")
    print()
    print("使用 chongming worker --help 查看更多信息")
    sys.exit(1)
