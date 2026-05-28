"""
chongming new 命令 - 从模板初始化新 worker
"""

import argparse
import os
import shutil

_EXAMPLE_WORKER_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "workers", "example")


def add_new_parser(subparsers):
    parser = subparsers.add_parser("new", help="创建一个新的 worker")
    parser.add_argument(
        "name",
        type=str,
        help="worker 名称（目录名）",
    )
    parser.add_argument(
        "--no-venv",
        action="store_true",
        help="不创建虚拟环境",
    )


def handle_new(args):
    workers_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "workers")
    target_dir = os.path.join(workers_dir, args.name)

    if not os.path.exists(_EXAMPLE_WORKER_PATH):
        print(f"错误：找不到示例 worker 模板：{_EXAMPLE_WORKER_PATH}")
        exit(1)

    if os.path.exists(target_dir):
        print(f"错误：目标目录已存在：{target_dir}")
        exit(1)

    # 1. 复制 example 目录作为模板
    print(f"正在从 example 模板创建 worker '{args.name}'...")
    shutil.copytree(_EXAMPLE_WORKER_PATH, target_dir, ignore=shutil.ignore_patterns(".venv", "__pycache__", ".git", "uv.lock", "*.pyc"))

    # 2. 重命名 config.toml 中的 worker name
    config_path = os.path.join(target_dir, "config.toml")
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            content = f.read()
        content = content.replace('name = "example"', f'name = "{args.name}"')
        with open(config_path, "w") as f:
            f.write(content)

    # 3. 重命名 pyproject.toml 中的 project name
    pyproject_path = os.path.join(target_dir, "pyproject.toml")
    if os.path.exists(pyproject_path):
        with open(pyproject_path, "r") as f:
            content = f.read()
        content = content.replace('name = "example"', f'name = "{args.name}"')
        with open(pyproject_path, "w") as f:
            f.write(content)

    # 4. 重写 main.py 中的 app 实例化和 handler 注册
    main_path = os.path.join(target_dir, "main.py")
    if os.path.exists(main_path):
        _rewrite_main(main_path, args.name)

    print(f"✓ Worker '{args.name}' 已创建在 {target_dir}")
    print()
    print("下一步：")
    print(f"  cd workers/{args.name}")

    if not args.no_venv:
        print("  uv sync")
    print("  python main.py")


def _rewrite_main(main_path: str, name: str):
    """根据 name 重写 main.py 中的占位内容"""
    with open(main_path, "r") as f:
        lines = f.readlines()

    new_lines = []
    for line in lines:
        # 替换 docstring 中的应用描述
        if "Example Worker" in line:
            line = line.replace("Example Worker", f"{name} Worker")
        # 替换 logger 名称
        line = line.replace("chongming.worker.example", f"chongming.worker.{name}")
        new_lines.append(line)

    with open(main_path, "w") as f:
        f.writelines(new_lines)
