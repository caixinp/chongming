"""
chongming new 命令 - 从模板初始化新 worker（支持 Python 和 Rust）
"""

import argparse
import os
import shutil

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
_TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "templates")
_PYTHON_TEMPLATE = os.path.join(_TEMPLATES_DIR, "python")
_RUST_TEMPLATE = os.path.join(_TEMPLATES_DIR, "rust")
_WORKERS_DIR = os.path.join(PROJECT_ROOT, "workers")


def add_new_parser(subparsers):
    parser = subparsers.add_parser(
        "new",
        help="从模板创建一个新的 worker（支持 Python 和 Rust）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 创建 Python worker（默认，包含全部 WorkerLifespan 特性）
  chongming new myworker

  # 创建 Rust worker
  chongming new myworker --lang rust

  # 创建 Rust worker，不初始化虚拟环境
  chongming new myworker --lang rust --no-venv
        """,
    )
    parser.add_argument(
        "name",
        type=str,
        help="worker 名称（目录名）",
    )
    parser.add_argument(
        "--lang",
        type=str,
        default="python",
        choices=["python", "rust"],
        help="worker 语言类型（默认: python）",
    )
    parser.add_argument(
        "--no-venv",
        action="store_true",
        help="不创建虚拟环境（仅 Python worker 有效）",
    )


def _copy_python_worker(args, target_dir):
    """从 templates/python 模板创建 Python worker"""
    if not os.path.exists(_PYTHON_TEMPLATE):
        print(f"错误：找不到 Python worker 模板：{_PYTHON_TEMPLATE}")
        exit(1)

    print(f"正在从 Python 模板创建 worker '{args.name}'...")
    shutil.copytree(
        _PYTHON_TEMPLATE,
        target_dir,
        ignore=shutil.ignore_patterns(".venv", "__pycache__", ".git", "uv.lock", "*.pyc"),
    )

    # 重命名 config.toml 中的 worker name
    config_path = os.path.join(target_dir, "config.toml")
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            content = f.read()
        content = content.replace('name = "example"', f'name = "{args.name}"')
        content = content.replace('service = "calc"', f'service = "{args.name}"')
        with open(config_path, "w") as f:
            f.write(content)

    # 重命名 public/config.toml（生产配置）
    public_config_path = os.path.join(target_dir, "public", "config.toml")
    if os.path.exists(public_config_path):
        with open(public_config_path, "r") as f:
            content = f.read()
        content = content.replace('name = "example"', f'name = "{args.name}"')
        with open(public_config_path, "w") as f:
            f.write(content)

    # 重命名 pyproject.toml 中的 project name
    pyproject_path = os.path.join(target_dir, "pyproject.toml")
    if os.path.exists(pyproject_path):
        with open(pyproject_path, "r") as f:
            content = f.read()
        content = content.replace('name = "example"', f'name = "{args.name}"')
        with open(pyproject_path, "w") as f:
            f.write(content)

    # 重写所有 Python 文件中的占位内容
    _rewrite_python_main(target_dir, args.name)

    print(f"✓ Python Worker '{args.name}' 已创建在 {target_dir}")
    print()
    print("该 worker 基于 example 模板，演示了 WorkerLifespan 框架的全部特性：")
    print("  · 基本 handler 注册（calc.add, calc.subtract 等）")
    print("  · Worker 间通讯：_app.request() 同步调用其他 worker")
    print("  · Worker 间通讯：_app.publish() 异步广播通知")
    print("  · NATS 连接注入：_nc 参数自动注入")
    print("  · WorkerLifespan 实例注入：_app.nats_connection")
    print("  · 容错处理：request 超时/失败时优雅降级")
    print()
    print("下一步：")
    print(f"  cd workers/{args.name}")

    if not args.no_venv:
        print("  uv sync")
    print("  python main.py")
    print()
    print("打包部署：")
    print(f"  chongming docker-build {args.name}")


def _copy_rust_worker(args, target_dir):
    """从 templates/rust 模板创建 Rust worker"""
    if not os.path.exists(_RUST_TEMPLATE):
        print(f"错误：找不到 Rust worker 模板：{_RUST_TEMPLATE}")
        exit(1)

    print(f"正在从 Rust 模板创建 worker '{args.name}'...")
    shutil.copytree(
        _RUST_TEMPLATE,
        target_dir,
        ignore=shutil.ignore_patterns("target", ".git", "Cargo.lock"),
    )

    # 重命名 Cargo.toml 中的 package name
    cargo_path = os.path.join(target_dir, "Cargo.toml")
    if os.path.exists(cargo_path):
        with open(cargo_path, "r") as f:
            content = f.read()
        content = content.replace('name = "example_rs"', f'name = "{args.name}"')
        with open(cargo_path, "w") as f:
            f.write(content)

    # 重命名 config.toml 中的 worker name
    config_path = os.path.join(target_dir, "config.toml")
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            content = f.read()
        content = content.replace('name = "example_rs"', f'name = "{args.name}"')
        with open(config_path, "w") as f:
            f.write(content)

    # 重命名 public/config.toml（生产配置）
    public_config_path = os.path.join(target_dir, "public", "config.toml")
    if os.path.exists(public_config_path):
        with open(public_config_path, "r") as f:
            content = f.read()
        content = content.replace('name = "example_rs"', f'name = "{args.name}"')
        with open(public_config_path, "w") as f:
            f.write(content)

    # 重写 main.rs 中的 handler 模板
    main_rs_path = os.path.join(target_dir, "src", "main.rs")
    if os.path.exists(main_rs_path):
        _rewrite_rust_main(main_rs_path, args.name)

    print(f"✓ Rust Worker '{args.name}' 已创建在 {target_dir}")
    print()
    print("下一步：")
    print(f"  cd workers/{args.name}")
    print("  编辑 main.rs 和 config.toml 添加业务逻辑")
    print("  cargo build           # 编译")
    print("  cargo run             # 运行")
    print()
    print("打包部署：")
    print(f"  chongming docker-build {args.name}   # Rust 自动检测并使用 Dockerfile 编译")
    print(f"  chongming binary-build {args.name}    # 推荐：编译为原生二进制")


def _rewrite_python_main(target_dir: str, name: str):
    """根据 name 重写 Python 模板中所有文件的占位内容"""
    _replace_in_file(os.path.join(target_dir, "main.py"), name)
    _replace_in_file(os.path.join(target_dir, "app", "bootstrap.py"), name)
    for handler_file in ["calc.py", "user.py", "order.py", "system.py"]:
        _replace_in_file(os.path.join(target_dir, "app", "handlers", handler_file), name)


def _replace_in_file(filepath: str, name: str):
    """替换单个文件中的占位内容"""
    if not os.path.exists(filepath):
        return
    with open(filepath, "r") as f:
        content = f.read()
    content = content.replace("Example Worker", f"{name} Worker")
    content = content.replace("chongming.worker.example", f"chongming.worker.{name}")
    with open(filepath, "w") as f:
        f.write(content)


def _rewrite_rust_main(main_rs_path: str, name: str):
    """根据 name 重写 Rust main.rs 中的占位内容"""
    with open(main_rs_path, "r") as f:
        content = f.read()

    # 将 example_rs 替换为新名称
    content = content.replace("example_rs", name)
    content = content.replace("Example", name.capitalize())

    with open(main_rs_path, "w") as f:
        f.write(content)


def handle_new(args):
    target_dir = os.path.join(_WORKERS_DIR, args.name)

    if os.path.exists(target_dir):
        print(f"错误：目标目录已存在：{target_dir}")
        exit(1)

    if args.lang == "rust":
        _copy_rust_worker(args, target_dir)
    else:
        _copy_python_worker(args, target_dir)
