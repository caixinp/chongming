"""
chongming gen-models 命令 - 从 config.toml 自动生成 Pydantic 输入/输出模型

根据 Worker 的 config.toml 配置，自动生成符合 handler 签名定义的
Pydantic 请求/响应模型，减少手动编写模型代码的工作量。
"""

import argparse
import os
import sys
from typing import Optional

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
_WORKERS_DIR = os.path.join(PROJECT_ROOT, "workers")


def add_gen_models_parser(subparsers):
    parser = subparsers.add_parser(
        "gen-models",
        help="根据 config.toml 自动生成 Pydantic 输入/输出模型",
        description=(
            "读取 Worker 的 config.toml 配置文件中注册的 handler 签名，"
            "自动生成类型安全、带校验的 Pydantic 请求/响应模型代码。"
            "支持为单个 Worker、所有 Worker 或当前目录生成模型，"
            "也可通过 --dry-run 预览生成结果。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用方式：
  1. 指定 worker 名称       chongming gen-models example    # 生成 workers/example 的模型
  2. 生成所有 worker 模型    chongming gen-models --all      # 遍历 workers/ 下所有目录
  3. 在当前目录运行          chongming gen-models            # 自动检测当前目录是否含 config.toml

示例：
  # 为指定 worker 生成模型
  chongming gen-models example

  # 预览生成的模型（不写文件）
  chongming gen-models example --dry-run

  # 为所有 worker 生成模型
  chongming gen-models --all

  # 为所有 worker 预览模型
  chongming gen-models --all --dry-run

工作原理：
  1. 读取 config.toml 中 [handler.*] 注册的每个 handler 配置
  2. 根据 handler 函数的类型注解生成对应的 Pydantic 模型
  3. 输出到 worker 根目录下的 models/__init__.py 文件
  4. 支持内置类型（int, str, float, bool, list, dict）及嵌套模型
  5. 自动添加字段校验：默认值、可选字段（Optional）、列表类型等

注意：
  - 生成的模型文件位于 workers/<name>/models/__init__.py
  - 若 handler 没有注册或签名中没有类型注解，则不会生成模型
  - 模型生成后建议检查生成的代码是否满足业务需求
  - 修改 config.toml 或 handler 签名后需重新生成

--shared 说明：
  在 config.toml 的 registration.items 中，为需要跨 Worker 共享模型的
  handler 添加 `shared = true` 字段，例如：

      {
          subject = "user.query",
          shared = true,  # <-- 加上此行，--shared 只生成带此标记的模型
          params = ["user_id: str"],
          response_model = {
              user_id = ["str", "__required__"],
              name = ["str", "__required__"]
          }
      }

  然后执行：chongming gen-models example --output public/__init__.py --shared
        """,
    )
    parser.add_argument(
        "name",
        type=str,
        nargs="?",
        default=None,
        help="worker 名称（对应 workers/ 下的子目录名），不传则使用当前目录",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="为所有 worker 生成模型（遍历 workers/ 下所有含 config.toml 的目录）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只预览生成的 Pydantic 模型代码，不写入文件",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="指定输出文件路径（如 public/__init__.py），覆盖默认的 models/__init__.py",
    )
    parser.add_argument(
        "--shared",
        action="store_true",
        help="只生成标记为 shared = true 的 handler 模型（用于跨 Worker 共享模型）",
    )


def _generate_for_worker(
    worker_dir: str,
    dry_run: bool = False,
    target_path: Optional[str] = None,
    shared_only: bool = False,
) -> tuple[bool, str]:
    """为单个 worker 生成模型

    :return: (success, message)
    """
    from chongming_worker.model_gen import write_models_to_disk, generate_models

    config_path = os.path.join(worker_dir, "config.toml")
    if not os.path.exists(config_path):
        return False, f"未找到 config.toml: {config_path}"

    try:
        if dry_run:
            code = generate_models(worker_dir, shared_only=shared_only)
        else:
            code = write_models_to_disk(
                worker_dir,
                dry_run=False,
                target_path=target_path,
                shared_only=shared_only,
            )

        if code.strip().startswith("#"):
            return True, "没有注册的 handler，未生成模型"

        if target_path:
            out_msg = f"✓ 模型已生成: {os.path.abspath(target_path)}"
        else:
            out_msg = f"✓ 模型已生成: {os.path.join(worker_dir, 'models', '__init__.py')}"
        return True, out_msg
    except Exception as e:
        return False, f"✗ 生成失败: {e}"


def handle_gen_models(args):
    dry_run = args.dry_run

    if args.all:
        # 为所有 worker 生成
        if not os.path.exists(_WORKERS_DIR):
            print(f"错误：找不到 workers 目录：{_WORKERS_DIR}")
            sys.exit(1)

        workers = sorted([
            d for d in os.listdir(_WORKERS_DIR)
            if os.path.isdir(os.path.join(_WORKERS_DIR, d))
            and os.path.exists(os.path.join(_WORKERS_DIR, d, "config.toml"))
        ])

        if not workers:
            print("未找到任何 worker（要求目录包含 config.toml）")
            return

        print(f"为 {len(workers)} 个 worker 生成模型...")
        print()

        success_count = 0
        for w in workers:
            worker_dir = os.path.join(_WORKERS_DIR, w)
            ok, msg = _generate_for_worker(
                worker_dir,
                dry_run,
                target_path=args.output,
                shared_only=args.shared,
            )
            status = "✓" if ok else "✗"
            print(f"  [{status}] {w}: {msg}")
            if ok:
                success_count += 1

        print()
        print(f"完成: {success_count}/{len(workers)} 个 worker 生成成功")

    elif args.name:
        # 为指定名称的 worker 生成
        worker_dir = os.path.join(_WORKERS_DIR, args.name)
        if not os.path.exists(worker_dir):
            print(f"错误：找不到 worker 目录：{worker_dir}")
            sys.exit(1)

        ok, msg = _generate_for_worker(
            worker_dir,
            dry_run,
            target_path=args.output,
            shared_only=args.shared,
        )

        if dry_run and ok:
            # 打印生成的代码
            from chongming_worker.model_gen import generate_models
            code = generate_models(worker_dir, shared_only=args.shared)
            print(code)
        else:
            print(msg)
            if not ok:
                sys.exit(1)

    else:
        # 尝试使用当前目录
        cwd = os.getcwd()
        if not os.path.exists(os.path.join(cwd, "config.toml")):
            print("错误：请在 worker 根目录（包含 config.toml）中运行")
            print("或指定 worker 名称：chongming gen-models <name>")
            print()
            print("可用 worker：")
            if os.path.exists(_WORKERS_DIR):
                for d in sorted(os.listdir(_WORKERS_DIR)):
                    if os.path.isdir(os.path.join(_WORKERS_DIR, d)):
                        print(f"  - {d}")
            sys.exit(1)

        ok, msg = _generate_for_worker(
            cwd,
            dry_run,
            target_path=args.output,
            shared_only=args.shared,
        )
        if ok:
            print(msg)
        else:
            print(msg)
            sys.exit(1)
