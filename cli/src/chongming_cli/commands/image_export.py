"""
chongming image-export 命令 - 将所有 Docker 镜像导出为 tar 包，用于离线部署

工作流程：
  1. 构建所有必要的 Docker 镜像（基础设施 + Gateway + Workers + Nginx）
  2. 将镜像导出为 .tar 文件到 build/ 目录
  3. 复制 docker-compose 配置到 build/ 目录
  4. 生成 deploy.sh 部署脚本

目标环境离线部署：
  1. 在本机（有网络）执行 chongming image-export
  2. 将整个 build/ 目录拷贝到离线目标机器
  3. 在目标机器上执行 bash deploy.sh 一键部署
"""

import argparse
import os
import subprocess
import sys
import shutil
from datetime import datetime
from typing import Optional


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
BUILD_DIR = os.path.join(PROJECT_ROOT, "build")
DOCKER_ENV_DIR = os.path.join(PROJECT_ROOT, "docker-env")
WORKERS_DIR = os.path.join(PROJECT_ROOT, "workers")


def _ensure_docker_available():
    """检查 docker 是否可用"""
    try:
        subprocess.run(["docker", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("错误：未找到 docker 命令，请先安装 Docker")
        print("  参考：https://docs.docker.com/engine/install/")
        sys.exit(1)


def _list_workers():
    """列出所有可用的 worker 名称"""
    workers = []
    if os.path.isdir(WORKERS_DIR):
        for name in sorted(os.listdir(WORKERS_DIR)):
            worker_dir = os.path.join(WORKERS_DIR, name)
            main_py = os.path.join(worker_dir, "main.py")
            if os.path.isdir(worker_dir) and not name.startswith(".") and os.path.isfile(main_py):
                workers.append(name)
    return workers


# ============================================================
# 基础设施镜像（直接拉取官方镜像，无需自定义构建）
# ============================================================
INFRA_IMAGES = {
    "nats": {
        "image": "nats:2.10-alpine",
        "description": "NATS 消息队列",
    },
    "postgresql": {
        "image": "bitnamilegacy/postgresql-repmgr:16",
        "description": "PostgreSQL 主备数据库",
    },
    "minio": {
        "image": "minio/minio:latest",
        "description": "MinIO 分布式存储",
    },
    "nginx": {
        "image": "nginx:alpine",
        "description": "Nginx 反向代理",
    },
}


def _get_image_tag(worker_name: Optional[str] = None) -> str:
    """获取镜像的最终 tag 名称"""
    if worker_name is None:
        # API Gateway
        return "chongming/gateway-binary:latest"
    return f"chongming/{worker_name}-binary:latest"


def _build_frontend_image():
    """构建前端镜像（Vue SPA + Nginx）"""
    dockerfile = os.path.join(DOCKER_ENV_DIR, "frontend.Dockerfile")
    if not os.path.isfile(dockerfile):
        print(f"  ⚠  跳过 Frontend：找不到 Dockerfile ({dockerfile})")
        return None

    tag = "chongming/frontend:latest"
    print(f"  构建前端镜像: {tag} ...")

    env = os.environ.copy()
    env["DOCKER_BUILDKIT"] = "1"
    env["COMPOSE_DOCKER_CLI_BUILD"] = "1"

    cmd = [
        "docker", "build",
        "-t", tag,
        "-f", dockerfile,
        PROJECT_ROOT,
    ]

    result = subprocess.run(cmd, cwd=PROJECT_ROOT, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ✗ 前端构建失败: {result.stderr.strip()}")
        return None

    print(f"  ✓ 前端镜像构建成功")
    return tag


def _build_gateway_image():
    """构建 API Gateway 二进制镜像"""
    dockerfile = os.path.join(DOCKER_ENV_DIR, "gateway-binary.Dockerfile")
    if not os.path.isfile(dockerfile):
        print(f"  ⚠  跳过 Gateway：找不到 Dockerfile ({dockerfile})")
        return None

    tag = _get_image_tag()
    print(f"  构建 Gateway 镜像: {tag} ...")

    env = os.environ.copy()
    env["DOCKER_BUILDKIT"] = "1"
    env["COMPOSE_DOCKER_CLI_BUILD"] = "1"

    cmd = [
        "docker", "build",
        "-t", tag,
        "-f", dockerfile,
        PROJECT_ROOT,
    ]

    result = subprocess.run(cmd, cwd=PROJECT_ROOT, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ✗ Gateway 构建失败: {result.stderr.strip()}")
        return None

    print(f"  ✓ Gateway 镜像构建成功")
    return tag


def _build_worker_image(worker_name: str):
    """构建单个 Worker 的二进制镜像"""
    dockerfile = os.path.join(DOCKER_ENV_DIR, "worker-binary.Dockerfile")
    if not os.path.isfile(dockerfile):
        print(f"  ⚠  跳过 {worker_name}：找不到 Dockerfile ({dockerfile})")
        return None

    tag = _get_image_tag(worker_name)
    print(f"  构建 Worker [{worker_name}] 镜像: {tag} ...")

    env = os.environ.copy()
    env["DOCKER_BUILDKIT"] = "1"
    env["COMPOSE_DOCKER_CLI_BUILD"] = "1"

    cmd = [
        "docker", "build",
        "--build-arg", f"WORKER_NAME={worker_name}",
        "-t", tag,
        "-f", dockerfile,
        PROJECT_ROOT,
    ]

    result = subprocess.run(cmd, cwd=PROJECT_ROOT, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ✗ {worker_name} 构建失败: {result.stderr.strip()}")
        return None

    print(f"  ✓ Worker [{worker_name}] 镜像构建成功")
    return tag


def _pull_infra_image(key: str, info: dict):
    """拉取基础设施镜像"""
    image = info["image"]
    print(f"  拉取 {info['description']}: {image} ...")

    result = subprocess.run(
        ["docker", "pull", image],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  ⚠  拉取失败: {result.stderr.strip()}")
        print(f"  请检查网络连接或手动拉取此镜像")
        return False

    print(f"  ✓ {info['description']} 拉取成功")
    return True


def _export_image(image_name: str, output_path: str) -> bool:
    """将 Docker 镜像导出为 tar 文件"""
    print(f"  导出: {image_name} -> {output_path}")

    result = subprocess.run(
        ["docker", "save", "-o", output_path, image_name],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  ✗ 导出失败: {result.stderr.strip()}")
        return False

    # 获取文件大小
    size_bytes = os.path.getsize(output_path)
    size_mb = size_bytes / (1024 * 1024)
    print(f"  ✓ 导出成功 ({size_mb:.1f} MB)")
    return True


def _copy_docker_env():
    """复制 docker-compose 配置到 build 目录"""
    print("  复制 Docker Compose 配置 ...")

    # 复制 docker-compose 文件
    for f in ["docker-compose.yml", "docker-compose.prod.yml"]:
        src = os.path.join(DOCKER_ENV_DIR, f)
        dst = os.path.join(BUILD_DIR, f)
        if os.path.isfile(src):
            shutil.copy2(src, dst)
            print(f"    {f}")

    # 复制 NATS 配置
    for f in ["nats-1.conf", "nats-2.conf", "nats-3.conf"]:
        src = os.path.join(DOCKER_ENV_DIR, f)
        dst = os.path.join(BUILD_DIR, f)
        if os.path.isfile(src):
            shutil.copy2(src, dst)
            print(f"    {f}")

    # 复制 Nginx 配置
    src = os.path.join(DOCKER_ENV_DIR, "nginx.conf")
    dst = os.path.join(BUILD_DIR, "nginx.conf")
    if os.path.isfile(src):
        shutil.copy2(src, dst)
        print(f"    nginx.conf")

    # 复制 README
    src = os.path.join(DOCKER_ENV_DIR, "README.md")
    dst = os.path.join(BUILD_DIR, "README.md")
    if os.path.isfile(src):
        shutil.copy2(src, dst)

    print("  ✓ Docker Compose 配置复制完成")


def add_image_export_parser(subparsers):
    parser = subparsers.add_parser(
        "image-export",
        help="将所有 Docker 镜像打包导出到 build/，用于离线部署",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 默认导出所有镜像（基础设施 + Gateway + 所有 Workers）
  chongming image-export

  # 仅导出基础设施镜像（NATS、PostgreSQL、MinIO、Nginx）
  chongming image-export --infra-only

  # 导出指定 worker 的镜像（还需基础设施）
  chongming image-export --workers example,testworker

  # 跳过基础设施（只构建业务镜像）
  chongming image-export --skip-infra

  # 不构建，只重新导出已有镜像
  chongming image-export --no-build

工作流程：
  步骤 1 - 在联网开发机执行：
    chongming image-export
    # 自动构建所有镜像并导出到 build/ 目录

  步骤 2 - 将 build/ 目录拷贝到离线目标机：
    scp -r build/ user@target-server:/path/to/deploy/

  步骤 3 - 在离线目标机一键部署：
    cd /path/to/deploy/build/
    bash deploy.sh
        """,
    )
    parser.add_argument(
        "--infra-only",
        action="store_true",
        help="仅导出基础设施镜像（NATS、PostgreSQL、MinIO、Nginx）",
    )
    parser.add_argument(
        "--workers",
        type=str,
        default=None,
        help="指定要导出的 worker 名称，逗号分隔（默认导出所有 worker）",
    )
    parser.add_argument(
        "--skip-infra",
        action="store_true",
        help="跳过基础设施镜像（只导出自定义构建的业务镜像）",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="不构建镜像，仅导出已有镜像（需先手动构建）",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=BUILD_DIR,
        help=f"输出目录（默认: {BUILD_DIR}）",
    )


def handle_image_export(args):
    """处理 image-export 命令"""
    output_dir = args.output_dir

    # 创建输出目录
    images_dir = os.path.join(output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    # 清空 images 目录（确保无残留旧镜像）
    for f in os.listdir(images_dir):
        fpath = os.path.join(images_dir, f)
        if os.path.isfile(fpath):
            os.remove(fpath)

    print("=" * 70)
    print("chongming 离线部署包构建工具")
    print("=" * 70)
    print()
    print(f"输出目录: {output_dir}")
    print()

    # 检查 Docker
    if not args.no_build:
        _ensure_docker_available()

    exported_images = []  # 记录所有成功导出的镜像: [(image_name, tar_filename)]
    infra_exported = 0
    custom_exported = 0

    # ============================================================
    # 阶段 1: 基础设施镜像
    # ============================================================
    if not args.skip_infra:
        print("阶段 1/2: 基础设施镜像")
        print("-" * 50)
        for key, info in INFRA_IMAGES.items():
            image = info["image"]
            tar_name = f"infra-{key}.tar"
            tar_path = os.path.join(images_dir, tar_name)

            if not args.no_build:
                # 拉取镜像
                if not _pull_infra_image(key, info):
                    continue

            # 导出镜像
            if _export_image(image, tar_path):
                exported_images.append((image, tar_name))
                infra_exported += 1
            print()
        print(f"基础设施镜像导出完成: {infra_exported}/{len(INFRA_IMAGES)}")
        print()
    else:
        print("阶段 1/2: 跳过基础设施镜像 (--skip-infra)")
        print()

    # ============================================================
    # 阶段 2: 自定义业务镜像（Gateway + Workers）
    # ============================================================
    if not args.infra_only:
        print("阶段 2/2: 自定义业务镜像")
        print("-" * 50)

        # --- API Gateway ---
        if not args.no_build:
            gw_tag = _build_gateway_image()
        else:
            gw_tag = _get_image_tag()
            # 检查镜像是否存在
            result = subprocess.run(
                ["docker", "image", "inspect", gw_tag],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                print(f"  ⚠  Gateway 镜像 '{gw_tag}' 不存在，跳过")
                gw_tag = None

        if gw_tag:
            tar_name = "gateway-binary.tar"
            tar_path = os.path.join(images_dir, tar_name)
            if _export_image(gw_tag, tar_path):
                exported_images.append((gw_tag, tar_name))
                custom_exported += 1
        print()

        # --- Frontend (Vue SPA + Nginx) ---
        if not args.no_build:
            fe_tag = _build_frontend_image()
        else:
            fe_tag = "chongming/frontend:latest"
            result = subprocess.run(
                ["docker", "image", "inspect", fe_tag],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                print(f"  ⚠  Frontend 镜像 '{fe_tag}' 不存在，跳过")
                fe_tag = None

        if fe_tag:
            tar_name = "frontend.tar"
            tar_path = os.path.join(images_dir, tar_name)
            if _export_image(fe_tag, tar_path):
                exported_images.append((fe_tag, tar_name))
                custom_exported += 1
        print()

        # --- Workers ---
        # 确定要构建的 worker 列表
        if args.workers:
            worker_list = [w.strip() for w in args.workers.split(",") if w.strip()]
        else:
            worker_list = _list_workers()

        if not worker_list:
            print("  (没有可用的 worker)")
        else:
            for wname in worker_list:
                if not args.no_build:
                    w_tag = _build_worker_image(wname)
                else:
                    w_tag = _get_image_tag(wname)
                    result = subprocess.run(
                        ["docker", "image", "inspect", w_tag],
                        capture_output=True, text=True,
                    )
                    if result.returncode != 0:
                        print(f"  ⚠  Worker [{wname}] 镜像 '{w_tag}' 不存在，跳过")
                        w_tag = None

                if w_tag:
                    tar_name = f"worker-{wname}.tar"
                    tar_path = os.path.join(images_dir, tar_name)
                    if _export_image(w_tag, tar_path):
                        exported_images.append((w_tag, tar_name))
                        custom_exported += 1
                print()

        print(f"业务镜像导出完成: {custom_exported} 个")
        print()
    else:
        print("阶段 2/2: 跳过业务镜像 (--infra-only)")
        print()

    # ============================================================
    # 阶段 3: 复制 Docker Compose 配置
    # ============================================================
    print("阶段 3/3: 复制部署配置")
    print("-" * 50)
    _copy_docker_env()

    # ============================================================
    # 阶段 4: 生成部署脚本
    # ============================================================
    print()
    print("阶段 4/4: 生成部署脚本")
    print("-" * 50)
    _generate_deploy_script(output_dir, exported_images, args.skip_infra, args.infra_only)

    # ============================================================
    # 总结
    # ============================================================
    total = infra_exported + custom_exported
    print()
    print("=" * 70)
    print(f"✓ 离线部署包构建完成!")
    print(f"  输出目录: {output_dir}")
    print(f"  镜像文件: {total} 个")
    print(f"  总大小:   {_get_dir_size_mb(images_dir):.1f} MB")
    print()
    print("部署步骤：")
    print(f"  1. 将整个 build/ 目录拷贝到离线目标服务器")
    print(f"     scp -r {output_dir} user@target-server:/path/to/deploy/")
    print()
    print(f"  2. 在目标服务器上执行一键部署脚本")
    print(f"     cd /path/to/deploy/build/")
    print(f"     bash deploy.sh")
    print()
    print(f"  3. 查看服务状态")
    print(f"     docker compose ps")
    print("=" * 70)


def _generate_deploy_script(output_dir: str, exported_images: list, skip_infra: bool, infra_only: bool):
    """生成 deploy.sh 部署脚本"""
    # 构建镜像加载命令列表
    tar_list_str = ""
    for _image_name, tar_name in exported_images:
        tar_list_str += f'    "{tar_name}"\n'
    tar_list_str = tar_list_str.rstrip("\n")

    script_content = '''#!/bin/bash
# =============================================
# chongming 离线一键部署脚本
# 生成时间: ''' + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + '''
# 用法: bash deploy.sh
# =============================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGES_DIR="${SCRIPT_DIR}/images"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
COMPOSE_PROD_FILE="${SCRIPT_DIR}/docker-compose.prod.yml"

# 颜色定义
RED='\\033[0;31m'
GREEN='\\033[0;32m'
YELLOW='\\033[1;33m'
NC='\\033[0m' # No Color

echo "============================================"
echo " chongming 离线部署工具"
echo "============================================"
echo ""

# --------------------------------------------------
# 步骤 1: 检查 Docker
# --------------------------------------------------
echo -e "${YELLOW}步骤 1/4: 检查 Docker 环境...${NC}"

if ! command -v docker &> /dev/null; then
    echo -e "${RED}错误: 未找到 docker 命令，请先安装 Docker${NC}"
    echo "  参考: https://docs.docker.com/engine/install/"
    exit 1
fi

DOCKER_VERSION=$(docker --version 2>/dev/null)
echo "  ✓ Docker 可用: ${DOCKER_VERSION}"

if ! docker compose version &> /dev/null; then
    echo -e "${RED}错误: docker compose 插件不可用${NC}"
    echo "  请安装 Docker Compose 插件"
    exit 1
fi

# --------------------------------------------------
# 步骤 2: 加载所有镜像
# --------------------------------------------------
echo ""
echo -e "${YELLOW}步骤 2/4: 加载 Docker 镜像...${NC}"

if [ ! -d "${IMAGES_DIR}" ]; then
    echo -e "${RED}错误: 找不到镜像目录: ${IMAGES_DIR}${NC}"
    echo "请确保 images/ 目录与 deploy.sh 在同一目录下"
    exit 1
fi

# 列出所有 tar 文件
TAR_FILES=(
''' + tar_list_str + '''
)

if [ ${#TAR_FILES[@]} -eq 0 ]; then
    echo -e "${YELLOW}  没有找到镜像文件，跳过${NC}"
else
    TOTAL=${#TAR_FILES[@]}
    COUNT=0
    for TAR_FILE in "${TAR_FILES[@]}"; do
        TAR_PATH="${IMAGES_DIR}/${TAR_FILE}"
        if [ ! -f "${TAR_PATH}" ]; then
            echo -e "${YELLOW}  ⚠ 跳过: ${TAR_FILE} (文件不存在)${NC}"
            continue
        fi

        COUNT=$((COUNT + 1))
        DESC="${TAR_FILE}"
        echo -e "  [${COUNT}/${TOTAL}] 加载 ${DESC} ..."

        LOAD_OUTPUT=$(docker load -i "${TAR_PATH}" 2>&1)
        if [ $? -ne 0 ]; then
            echo -e "${RED}  ✗ 加载失败: ${TAR_FILE}${NC}"
            echo "    ${LOAD_OUTPUT}"
            exit 1
        fi
        echo -e "  ${GREEN}  ✓ 加载成功${NC}"
    done
    echo ""
    echo -e "${GREEN}  所有镜像加载完成!${NC}"
fi

'''

    if not infra_only:
        script_content += '''
# --------------------------------------------------
# 步骤 3: 创建 Docker 网络（如果不存在）
# --------------------------------------------------
echo ""
echo -e "${YELLOW}步骤 3/4: 准备 Docker 网络...${NC}"

NETWORK_NAME="microservices-net"
if docker network inspect ${NETWORK_NAME} &>/dev/null; then
    echo "  ✓ 网络 ${NETWORK_NAME} 已存在"
else
    echo "  创建网络 ${NETWORK_NAME} ..."
    docker network create ${NETWORK_NAME}
    echo "  ✓ 网络创建成功"
fi

# --------------------------------------------------
# 步骤 4: 启动服务
# --------------------------------------------------
echo ""
echo -e "${YELLOW}步骤 4/4: 启动所有服务...${NC}"

if [ -f "${COMPOSE_PROD_FILE}" ]; then
    echo "  使用生产模式配置"
    docker compose -f "${COMPOSE_FILE}" -f "${COMPOSE_PROD_FILE}" up -d
else
    echo "  使用标准配置"
    docker compose -f "${COMPOSE_FILE}" up -d
fi

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN} 部署完成!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "服务状态:"
docker compose -f "${COMPOSE_FILE}" $([ -f "${COMPOSE_PROD_FILE}" ] && echo "-f ${COMPOSE_PROD_FILE}") ps

echo ""
echo "查看日志:"
echo "  docker compose logs -f --tail 50"
echo ""
echo "停止服务:"
echo "  docker compose down"
'''
    else:
        # infra-only 模式
        script_content += '''
# --------------------------------------------------
# 步骤 3: 启动基础设施服务
# --------------------------------------------------
echo ""
echo -e "${YELLOW}步骤 3/3: 启动基础设施服务...${NC}"

if [ -f "${COMPOSE_FILE}" ]; then
    docker compose -f "${COMPOSE_FILE}" up -d
    echo ""
    echo -e "${GREEN} 基础设施服务已启动!${NC}"
else
    echo -e "${RED} 错误: 找不到 docker-compose.yml${NC}"
    exit 1
fi

echo ""
echo "服务状态:"
docker compose -f "${COMPOSE_FILE}" ps

echo ""
echo "查看日志:"
echo "  docker compose logs -f --tail 50"
echo ""
echo "停止服务:"
echo "  docker compose down"
'''

    script_content += '''
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN} 🎉 chongming 离线部署完成!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "============================================"
echo " 端口映射（宿主机访问）"
echo "============================================"
echo "  Nginx 网关:       http://localhost"
echo "  NATS 集群节点1:   localhost:4222"
echo "  NATS 管理界面:    http://localhost:8222"
echo "  PostgreSQL 主:    localhost:5432"
echo "  PostgreSQL 备:    localhost:5433"
echo "  MinIO API:        http://localhost:9000"
echo "  MinIO 控制台:     http://localhost:9001"
echo ""
echo "健康检查:"
echo "  curl http://localhost/nginx/health    # Nginx 状态"
echo "  curl http://localhost/api/v1/health   # API Gateway 状态"
echo ""
echo "查看日志:"
echo "  docker compose logs -f --tail 50           # 所有服务"
echo "  docker compose logs api-gateway-1 --tail 20 # 指定服务"
echo ""
echo "停止服务:"
echo "  docker compose down"
echo "============================================"
'''

    script_path = os.path.join(output_dir, "deploy.sh")
    with open(script_path, "w") as f:
        f.write(script_content)

    # 设置可执行权限
    os.chmod(script_path, 0o755)
    print(f"  ✓ deploy.sh 已生成")


def _get_dir_size_mb(directory: str) -> float:
    """计算目录大小（MB）"""
    total = 0
    for dirpath, dirnames, filenames in os.walk(directory):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total / (1024 * 1024)
