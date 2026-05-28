"""
chongming binary-build 命令 - 使用 PyInstaller 打包 worker/gateway 为独立二进制并构建 Docker 镜像

相比 docker-build（pip + Python 运行时），binary-build 的优势：
  - 镜像大小从 ~200MB 减小到 ~20MB
  - 无需 Python 运行时，启动更快
  - 不包含源码，保护知识产权
  - 运行环境完全独立，无依赖冲突

适用于生产环境部署。开发调试请使用 docker-build。
"""

import argparse
import os
import subprocess
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))


def _is_gateway(name: str) -> bool:
    """判断是否为 API Gateway"""
    return name == "gateway"


def _get_dockerfile(name: str) -> str:
    """根据名称返回对应的 Dockerfile 路径"""
    if _is_gateway(name):
        return os.path.join(PROJECT_ROOT, "docker-env", "gateway-binary.Dockerfile")
    return os.path.join(PROJECT_ROOT, "docker-env", "worker-binary.Dockerfile")


def _get_default_tag(name: str) -> str:
    """根据名称返回默认 tag"""
    if _is_gateway(name):
        return "chongming/gateway-binary:latest"
    return f"chongming/{name}-binary:latest"


def add_binary_build_parser(subparsers):
    parser = subparsers.add_parser(
        "binary-build",
        help="使用 PyInstaller 将 worker/gateway 打包为单二进制 Docker 镜像（生产环境推荐）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 打包 API Gateway 为二进制 Docker 镜像（300MB → ~30MB）
  chongming binary-build gateway

  # 打包 example worker 为二进制 Docker 镜像
  chongming binary-build example

  # 指定镜像仓库 tag 并推送
  chongming binary-build gateway --tag registry.example.com/gateway:v1.0 --push

  # 不缓存 PyInstaller 构建
  chongming binary-build example --no-cache

  # 查看生产环境部署指南
  chongming binary-build gateway --help-deploy

支持的目标：
  gateway     - API Gateway（使用 docker-env/gateway-binary.Dockerfile）
  <worker>    - workers/ 下的任意 worker（使用 docker-env/worker-binary.Dockerfile）

工作流程：
  1. 在 builder 容器中安装所有依赖 + PyInstaller
  2. PyInstaller --onefile 打包为单文件二进制
  3. 将二进制复制到 busybox:glibc 最小镜像中
  4. 最终镜像仅包含：二进制 + config.toml（+ public/ 对于 gateway）

对比 chongming docker-build：
  docker-build  → 完整 Python 运行时，适合开发/CI 快速迭代
  binary-build  → 单二进制，极小镜像，适合生产部署
        """,
    )
    parser.add_argument(
        "name",
        type=str,
        help="目标名称: gateway 或 workers/ 下的子目录名（如 example, testworker）",
    )
    parser.add_argument(
        "--tag",
        "-t",
        type=str,
        default=None,
        help="镜像标签（默认: chongming/gateway-binary:latest 或 chongming/<name>-binary:latest）",
    )
    parser.add_argument(
        "--push",
        action="store_true",
        help="构建完成后推送到镜像仓库",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="构建时不使用缓存",
    )
    parser.add_argument(
        "--base-image",
        type=str,
        default="busybox:glibc",
        help="运行阶段的基础镜像（默认: busybox:glibc，可选: alpine, scratch）",
    )
    parser.add_argument(
        "--help-deploy",
        action="store_true",
        help="打印生产环境部署指南",
    )


def _ensure_target_exists(name: str):
    """验证构建目标存在"""
    if _is_gateway(name):
        # 验证 api_gateway 目录存在
        gateway_dir = os.path.join(PROJECT_ROOT, "api_gateway")
        if not os.path.isdir(gateway_dir):
            print(f"错误：找不到 API Gateway 目录：{gateway_dir}")
            sys.exit(1)
        return gateway_dir

    # 验证 worker 目录存在
    worker_dir = os.path.join(PROJECT_ROOT, "workers", name)
    if not os.path.isdir(worker_dir):
        print(f"错误：找不到目标 '{name}'")
        print("可用的构建目标：")
        print("  gateway              - API Gateway")
        workers_root = os.path.join(PROJECT_ROOT, "workers")
        if os.path.isdir(workers_root):
            for d in sorted(os.listdir(workers_root)):
                dpath = os.path.join(workers_root, d)
                if os.path.isdir(dpath) and not d.startswith("."):
                    print(f"  {d}                  - workers/{d}")
        sys.exit(1)
    return worker_dir


def _ensure_docker_available():
    """检查 docker 是否可用"""
    try:
        subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("错误：未找到 docker 命令，请先安装 Docker")
        sys.exit(1)


def _build_image(name: str, tag: str, no_cache: bool, base_image: str):
    """执行 Docker 构建（PyInstaller 打包）"""
    if tag is None:
        tag = _get_default_tag(name)

    dockerfile = _get_dockerfile(name)
    if not os.path.isfile(dockerfile):
        print(f"错误：找不到 Dockerfile：{dockerfile}")
        sys.exit(1)

    target_label = "API Gateway" if _is_gateway(name) else f"Worker ({name})"
    print("=" * 70)
    print(f"PyInstaller 二进制打包与 Docker 构建")
    print("=" * 70)
    print(f"  目标:        {target_label}")
    print(f"  Tag:         {tag}")
    print(f"  Dockerfile:  {dockerfile}")
    print(f"  基础镜像:    {base_image}")
    print(f"  工作目录:    {PROJECT_ROOT}")
    print()
    print("步骤：")
    print("  1. pip install 依赖 + PyInstaller")
    print("  2. PyInstaller --onefile 打包为单二进制")
    print("  3. 复制到最小基础镜像")
    print()

    env = os.environ.copy()
    env["DOCKER_BUILDKIT"] = "1"
    env["COMPOSE_DOCKER_CLI_BUILD"] = "1"

    cmd = ["docker", "build"]

    if no_cache:
        cmd.append("--no-cache")

    if not _is_gateway(name):
        cmd.extend(["--build-arg", f"WORKER_NAME={name}"])

    cmd.extend(["-t", tag])
    cmd.extend(["-f", dockerfile])
    cmd.append(PROJECT_ROOT)

    print(f"执行: {' '.join(cmd)}")
    print()

    result = subprocess.run(cmd, cwd=PROJECT_ROOT, env=env)

    if result.returncode != 0:
        print(f"\n错误：Docker 构建失败（退出码: {result.returncode}）")
        sys.exit(result.returncode)

    print(f"\n✓ 二进制镜像构建成功: {tag}")
    return tag


def _push_image(tag: str):
    """推送到镜像仓库"""
    print(f"正在推送镜像: {tag}")
    cmd = ["docker", "push", tag]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"\n错误：推送失败（退出码: {result.returncode}）")
        print("请确保已通过 docker login 登录到目标镜像仓库")
        sys.exit(result.returncode)
    print(f"\n✓ 镜像推送成功: {tag}")


def _print_deploy_guide(name: str, tag: str):
    """打印生产环境部署指南"""
    if tag is None:
        tag = _get_default_tag(name)

    is_gw = _is_gateway(name)

    print("=" * 70)
    if is_gw:
        print("API Gateway 生产环境部署指南（二进制模式）")
    else:
        print(f"{name} Worker 生产环境部署指南（二进制模式）")
    print("=" * 70)
    print()
    print("镜像信息：")
    print(f"  镜像: {tag}")
    print(f"  基础: busybox:glibc（仅 5MB + 二进制 ~15-30MB）")
    print(f"  内容: 单文件静态编译二进制 + 配置文件")
    print()
    print("步骤 1：在生产服务器上拉取镜像")
    print(f"  docker pull {tag}")
    print()

    if is_gw:
        print("步骤 2：运行网关（替代现有的 api-gateway-1/api-gateway-2 Python 容器）")
        print(f"""
  docker run -d \\
    --name gateway \\
    --restart unless-stopped \\
    --network microservices-net \\
    -p 8000:8000 \\
    {tag}
""")
        print("步骤 3：Nginx 负载均衡配置不变，指向二进制网关")
        print("  将 nginx.conf 中的 upstream 指向 gateway:8000")
        print()
        print("镜像大小对比：")
        print("  docker images chongming/gateway              (~300MB) - Python 运行时模式")
        print(f"  docker images {tag} (~30MB)  - 二进制模式 ✅")
    else:
        print("步骤 2：单实例运行")
        print(f"""
  docker run -d \\
    --name {name}-worker \\
    --restart unless-stopped \\
    --network microservices-net \\
    -v /path/to/production-config.toml:/app/config.toml:ro \\
    {tag}
""")
        print("步骤 3：多实例负载均衡运行")
        print(f"""
  docker run -d --name {name}-worker-1 --restart unless-stopped --network microservices-net {tag}
  docker run -d --name {name}-worker-2 --restart unless-stopped --network microservices-net {tag}
""")
        print("镜像大小对比：")
        print(f"  docker images chongming/{name}              (~200MB) - Python 运行时模式")
        print(f"  docker images {tag} (~20MB)   - 二进制模式 ✅")

    print()
    print("步骤 4：验证运行状态")
    container_name = "gateway" if is_gw else f"{name}-worker"
    print(f"  docker ps --filter name={container_name}")
    print(f"  docker logs {container_name} --tail 20")
    print()
    print("步骤 5：验证功能")
    if is_gw:
        print("  curl http://localhost:8000/health")
    else:
        print("  # 通过网关调用 worker 注册的路由")
        print("  curl http://<gateway-host>:8080/api/v1/calc/add?a=1&b=2")
    print()
    print("更新流程：")
    print(f"  1. 本地构建新版本：chongming binary-build {name} --tag {tag} --push")
    print(f"  2. 生产拉取：docker pull {tag}")
    print(f"  3. 滚动更新：docker stop {container_name} && docker rm {container_name} && docker run ...")
    print("=" * 70)


def handle_binary_build(args):
    if args.help_deploy:
        _print_deploy_guide(args.name, args.tag)
        return

    _ensure_target_exists(args.name)
    _ensure_docker_available()

    tag = _build_image(
        name=args.name,
        tag=args.tag,
        no_cache=args.no_cache,
        base_image=args.base_image,
    )

    if args.push:
        _push_image(tag)

    print()
    print("💡 生产环境部署说明：")
    print(f"  使用以下命令查看部署指南：")
    print(f"    chongming binary-build {args.name} --help-deploy")
    print()
    print(f"📊 镜像大小对比：")
    print(f"  当前二进制模式: docker images {tag}")
    target = "API Gateway" if _is_gateway(args.name) else args.name
    print(f"  Python 运行时模式: chongming docker-build {args.name} 后再对比大小")
