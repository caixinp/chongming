#!/bin/bash
# deploy.sh - chongming 快速部署脚本
set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 检测架构
ARCH=$(uname -m)
case "$ARCH" in
    x86_64|amd64)
        DEFAULT_IMAGE="chongming:latest"
        ARCH_FLAG="x86_64"
        ;;
    aarch64|arm64)
        DEFAULT_IMAGE="chongming:arm64"
        ARCH_FLAG="aarch64"
        ;;
    *)
        log_error "不支持的架构: $ARCH"
        exit 1
        ;;
esac

# 配置：可通过环境变量覆盖镜像标签，例如: IMAGE=chongming:arm64 ./deploy.sh
IMAGE="${IMAGE:-$DEFAULT_IMAGE}"
CONTAINER="chongming"
PORT=8000
DATA_DIR="${HOME}/chongming-data"

# 检查 docker
if ! command -v docker &> /dev/null; then
    log_error "Docker 未安装，请先安装 Docker"
    exit 1
fi

# 检查镜像
if ! docker image inspect "$IMAGE" &> /dev/null; then
    log_error "镜像 $IMAGE 不存在，请先构建: docker build -t $IMAGE ."
    exit 1
fi

# 1. 停止并删除旧容器
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    log_warn "发现旧容器，正在停止并删除..."
    docker stop "$CONTAINER" 2>/dev/null || true
    docker rm "$CONTAINER" 2>/dev/null || true
fi

# 2. 创建目录
log_info "创建数据目录..."
mkdir -p "$DATA_DIR"/{data,uploads,logs}
chmod 755 "$DATA_DIR"/{data,uploads,logs}

# 3. 复制初始数据（仅在目录为空时）
if [ -z "$(ls -A $DATA_DIR/data 2>/dev/null)" ]; then
    log_info "首次部署，从镜像中提取初始数据库..."
    TMP_CONTAINER="chongming-tmp-$$"
    docker create --name "$TMP_CONTAINER" "$IMAGE" &> /dev/null
    docker cp "$TMP_CONTAINER:/app/data/." "$DATA_DIR/data/" &> /dev/null
    docker rm "$TMP_CONTAINER" &> /dev/null
    log_info "初始数据库已就绪"
else
    log_info "数据库已存在，跳过初始化"
fi

# 检查端口是否被占用
if ss -tlnp | grep -q ":${PORT}"; then
    log_error "端口 ${PORT} 已被占用，请修改 PORT 变量或释放端口"
    exit 1
fi

# 根据架构设置默认 worker 数
case "$ARCH" in
    aarch64|arm64)
        DEFAULT_WORKERS=2
        ;;
    *)
        DEFAULT_WORKERS=4
        ;;
esac

# 4. 启动容器
log_info "启动容器..."
log_info "架构: $ARCH, workers: ${APP_WORKERS:-$DEFAULT_WORKERS}, 端口: $PORT"
docker run -d \
    -p "$PORT:8000" \
    -v "$DATA_DIR/data:/app/data" \
    -v "$DATA_DIR/uploads:/app/uploads" \
    -v "$DATA_DIR/logs:/app/logs" \
    -e "APP_WORKERS=${APP_WORKERS:-$DEFAULT_WORKERS}" \
    --ulimit nproc=65535 \
    --ulimit nofile=65535 \
    --restart unless-stopped \
    --name "$CONTAINER" \
    "$IMAGE"

# 5. 等待启动
log_info "等待应用启动..."
sleep 3

# 6. 检查状态
if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    log_info "=========================================="
    log_info "✅ 部署成功！"
    log_info "=========================================="
    log_info "应用地址: http://localhost:$PORT"
    log_info "API 文档: http://localhost:$PORT/docs"
    log_info "数据目录: $DATA_DIR"
    log_info ""
    log_info "查看日志: docker logs -f $CONTAINER"
    log_info "停止服务: docker stop $CONTAINER"
    log_info "重启服务: docker restart $CONTAINER"
    log_info "=========================================="
else
    log_error "容器启动失败，查看日志:"
    docker logs "$CONTAINER" 2>/dev/null || true
    exit 1
fi
