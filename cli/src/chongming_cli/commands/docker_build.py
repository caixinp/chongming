"""
chongming docker-build 命令 - 打包 worker 的 Docker 镜像
"""

import argparse
import os
import subprocess
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))


def add_docker_build_parser(subparsers):
    parser = subparsers.add_parser(
        "docker-build",
        help="打包 worker 的 Docker 镜像",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 打包 example worker，默认 tag 为 chongming/example:latest
  chongming docker-build example

  # 打包 testworker，指定 tag
  chongming docker-build testworker --tag registry.example.com/workers/testworker:v1.0.0

  # 打包并推送到远程仓库
  chongming docker-build example --tag myrepo/example:latest --push

  # 打包并指定 Dockerfile 路径
  chongming docker-build example --dockerfile /path/to/Dockerfile

生产环境部署说明：
  生成镜像后，需要将镜像推送到镜像仓库（如 Docker Hub、Harbor、AWS ECR 等），
  然后在生产服务器上拉取镜像并运行容器。
  详见 chongming docker-build --help-deploy
        """,
    )
    parser.add_argument(
        "name",
        type=str,
        help="worker 名称（对应 workers/ 下的子目录名）",
    )
    parser.add_argument(
        "--tag",
        "-t",
        type=str,
        default=None,
        help="镜像标签（默认: chongming/<name>:latest）",
    )
    parser.add_argument(
        "--dockerfile",
        "-f",
        type=str,
        default=None,
        help="Dockerfile 路径（默认: docker-env/worker.Dockerfile）",
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
        "--build-arg",
        type=str,
        action="append",
        default=[],
        help="构建参数，可多次使用（如 --build-arg KEY=VALUE）",
    )
    parser.add_argument(
        "--help-deploy",
        action="store_true",
        help="打印生产环境部署指南",
    )


def _ensure_worker_exists(name: str):
    """验证 worker 目录存在"""
    worker_dir = os.path.join(PROJECT_ROOT, "workers", name)
    if not os.path.isdir(worker_dir):
        print(f"错误：找不到 worker '{name}'，目录不存在：{worker_dir}")
        print("可用的 worker：")
        workers_root = os.path.join(PROJECT_ROOT, "workers")
        if os.path.isdir(workers_root):
            for d in sorted(os.listdir(workers_root)):
                dpath = os.path.join(workers_root, d)
                if os.path.isdir(dpath) and not d.startswith("."):
                    print(f"  - {d}")
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
        print("  参考：https://docs.docker.com/engine/install/")
        sys.exit(1)


def _build_image(name: str, tag: str, dockerfile: str, no_cache: bool, build_args: list):
    """执行 Docker 构建"""
    # 默认 tag
    if tag is None:
        tag = f"chongming/{name}:latest"

    # 默认 Dockerfile
    if dockerfile is None:
        dockerfile = os.path.join(PROJECT_ROOT, "docker-env", "worker.Dockerfile")

    if not os.path.isfile(dockerfile):
        print(f"错误：找不到 Dockerfile：{dockerfile}")
        sys.exit(1)

    print(f"正在构建 Docker 镜像 ...")
    print(f"  Worker:     {name}")
    print(f"  Tag:        {tag}")
    print(f"  Dockerfile: {dockerfile}")
    print(f"  工作目录:   {PROJECT_ROOT}")
    print()

    # 使用 BuildKit 以获得：
    #   - 更好的层缓存
    #   - --mount=type=cache 支持（apt/pip 缓存加速）
    #   - 更快的构建
    env = os.environ.copy()
    env["DOCKER_BUILDKIT"] = "1"
    env["COMPOSE_DOCKER_CLI_BUILD"] = "1"

    cmd = ["docker", "build"]

    # 添加 --no-cache
    if no_cache:
        cmd.append("--no-cache")

    # 添加 --build-arg
    cmd.extend(["--build-arg", f"WORKER_NAME={name}"])
    for ba in build_args:
        cmd.extend(["--build-arg", ba])

    # 添加 tag
    cmd.extend(["-t", tag])

    # Dockerfile
    cmd.extend(["-f", dockerfile])

    # 上下文目录（项目根目录）
    cmd.append(PROJECT_ROOT)

    print(f"执行: {' '.join(cmd)}")
    print()

    result = subprocess.run(cmd, cwd=PROJECT_ROOT)

    if result.returncode != 0:
        print(f"\n错误：Docker 构建失败（退出码: {result.returncode}）")
        sys.exit(result.returncode)

    print(f"\n✓ 镜像构建成功: {tag}")
    return tag


def _push_image(tag: str):
    """推送到镜像仓库"""
    print(f"正在推送镜像: {tag}")
    print()

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
        tag = f"chongming/{name}:latest"

    print("=" * 70)
    print("生产环境部署指南")
    print("=" * 70)
    print()
    print("前提条件：")
    print("  1. 生产服务器已安装 Docker")
    print("  2. 已搭建基础设施（NATS、PostgreSQL、MinIO 等）")
    print("  3. 生产服务器能访问镜像仓库")
    print()
    print("步骤 1：在生产服务器上登录镜像仓库")
    print(f"  docker login <registry-url>")
    print()
    print("步骤 2：拉取镜像")
    print(f"  docker pull {tag}")
    print()
    print("步骤 3：运行容器")

    print(f"""
  docker run -d \\
    --name {name}-worker \\
    --restart unless-stopped \\
    --network microservices-net \\
    -e NATS_SERVERS=nats://nats-1:4222,nats://nats-2:4222,nats://nats-3:4222 \\
    -e CONFIG_PATH=/app/config.toml \\
    -v /path/to/production-config.toml:/app/config.toml:ro \\
    {tag}
""")

    print("如果使用 Docker Compose（推荐），在 docker-compose.prod.yml 中添加：")
    print(f"""
  {name}-worker:
    image: {tag}
    container_name: {name}-worker
    restart: unless-stopped
    networks:
      - microservices-net
    environment:
      - NATS_SERVERS=nats://nats-1:4222,nats://nats-2:4222,nats://nats-3:4222
      - CONFIG_PATH=/app/config.toml
    volumes:
      - /path/to/production-config.toml:/app/config.toml:ro
""")

    print("步骤 4：验证 worker 运行状态")
    print(f"  docker ps -a --filter name={name}-worker")
    print(f"  docker logs {name}-worker --tail 50")
    print()
    print("步骤 5：在 API Gateway 中验证路由注册")
    print("  # 通过网关调用 worker 注册的路由，例如：")
    print("  # 如果 example worker 注册了 calc.add，则：")
    print('  curl http://<gateway-host>:8080/api/v1/calc/add?a=1&b=2')
    print()
    print("扩缩容：")
    print(f"  运行多个实例实现高可用：")
    print(f"  docker run -d --name {name}-worker-1 ... {tag}")
    print(f"  docker run -d --name {name}-worker-2 ... {tag}")
    print()
    print("更新：")
    print(f"  1. 重新构建镜像：chongming docker-build {name} --tag {tag}")
    print(f"  2. 推送镜像：docker push {tag}")
    print(f"  3. 拉取新镜像：docker pull {tag}")
    print(f"  4. 重启容器：docker restart {name}-worker")
    print("=" * 70)


def handle_docker_build(args):
    if args.help_deploy:
        _print_deploy_guide(args.name, args.tag)
        return

    # 验证 worker 存在
    _ensure_worker_exists(args.name)

    # 检查 docker 是否可用
    _ensure_docker_available()

    # 构建镜像
    tag = _build_image(
        name=args.name,
        tag=args.tag,
        dockerfile=args.dockerfile,
        no_cache=args.no_cache,
        build_args=args.build_arg,
    )

    # 推送
    if args.push:
        _push_image(tag)

    print()
    print("生产环境部署说明：")
    print(f"  使用以下命令查看部署指南：")
    print(f"    chongming docker-build {args.name} --help-deploy")
