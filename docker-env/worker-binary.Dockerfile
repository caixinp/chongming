# ================================================
# Builder stage: PyInstaller 打包 worker 为独立二进制
# ================================================
FROM python:3.12-slim AS builder

ARG WORKER_NAME
ENV WORKER_NAME=${WORKER_NAME}

WORKDIR /build

# Step 1: Copy package metadata first
COPY utils/config/pyproject.toml utils/config/README.md utils/config/
COPY utils/logging/pyproject.toml utils/logging/README.md utils/logging/
COPY utils/cache/pyproject.toml utils/cache/README.md utils/cache/
COPY utils/lock/pyproject.toml utils/lock/README.md utils/lock/
COPY utils/worker/pyproject.toml utils/worker/README.md utils/worker/
COPY workers/${WORKER_NAME}/pyproject.toml workers/${WORKER_NAME}/README.md workers/${WORKER_NAME}/

# Step 2: Copy source code
COPY utils/config/src utils/config/src
COPY utils/logging/src utils/logging/src
COPY utils/cache/src utils/cache/src
COPY utils/lock/src utils/lock/src
COPY utils/worker/src utils/worker/src
COPY workers/${WORKER_NAME}/ workers/${WORKER_NAME}/

# Step 3: Install system dependencies for PyInstaller (objdump, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    binutils \
    && rm -rf /var/lib/apt/lists/*

# Step 4: Configure pip mirror for faster downloads and install build dependencies
RUN pip config set global.index-url https://mirrors.ustc.edu.cn/pypi/web/simple/

# Step 5: Install build dependencies first (wheel, setuptools) to avoid download timeouts
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --default-timeout=120 \
    setuptools wheel

# Step 6: Install all dependencies + pyinstaller
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --default-timeout=120 \
    ./utils/config \
    ./utils/logging \
    ./utils/cache \
    ./utils/lock \
    ./utils/worker \
    ./workers/${WORKER_NAME} \
    pyinstaller

# Step 7: 删除 mypyc 编译的 .so 文件
# tomli 等依赖的 mypyc 编译会产生随机命名模块（如 955cd85d__mypyc），
# PyInstaller 无法自动发现，运行时会导致 ModuleNotFoundError。
# 注意：mypyc 编译会替换原始 .py 文件，删除 .so 后纯 Python 回退代码不存在，
# 需要强制重新安装纯 Python 版本。
RUN find /usr/local/lib/python3.12/site-packages -name "*.so" -path "*mypyc*" -delete 2>/dev/null; \
    find /usr/local/lib/python3.12/site-packages -name "*.cpython-*.so" -delete 2>/dev/null; \
    echo "Deleted mypyc compiled .so files"

# Step 7.1: 重新安装被 mypyc 覆盖的依赖为纯 Python 版本
# mypyc 编译会替换包的 .py 源文件为 .so，删除 .so 后 module 消失导致 ImportError。
# 需要强制重新安装纯 Python 版本以保证 PyInstaller 运行时能找到模块。
# 目前已知受影响依赖：tomli
RUN pip install --no-compile --force-reinstall --no-binary tomli tomli; \
    echo "Reinstalled tomli as pure Python (no mypyc compilation)"

# Step 8: Build single binary with PyInstaller
# 注意: config.toml 通过 --add-data 嵌入二进制，运行时在 sys._MEIPASS
# 生产 stage 会单独从 source 复制 config.toml 到 /app/，确保 CWD 中可读取
RUN pyinstaller --onefile \
    --name "${WORKER_NAME}-worker" \
    --hidden-import="nats" \
    --hidden-import="nats.aio" \
    --hidden-import="nats.aio.client" \
    --hidden-import="chongming_worker" \
    --hidden-import="chongming_worker.worker_lifespan" \
    --hidden-import="chongming_config" \
    --hidden-import="chongming_logging" \
    --hidden-import="chongming_cache" \
    --hidden-import="chongming_lock" \
    --hidden-import="tomli" \
    --hidden-import="tomli._re" \
    --collect-all="chongming_worker" \
    --collect-all="chongming_config" \
    --collect-all="chongming_logging" \
    --add-data "workers/${WORKER_NAME}/public/config.toml:config.toml" \
    --distpath /build/dist \
    --workpath /build/pyibuild \
    --specpath /build \
    workers/${WORKER_NAME}/main.py

# ================================================
# Production stage: 最小化运行镜像
# ================================================
# 使用 debian:stable-slim 作为基础镜像
# 注意: busybox 缺少 PyInstaller 二进制所需的 libdl.so.2 等共享库
# debian-slim (~80MB) 比 busybox (~5MB) 大，但保证了二进制兼容性
FROM debian:stable-slim

ARG WORKER_NAME
ENV WORKER_NAME=${WORKER_NAME}

WORKDIR /app

# 从 builder 复制打包好的二进制文件
COPY --from=builder /build/dist/${WORKER_NAME}-worker /app/worker

# 从 source 复制生产配置文件到 /app/config.toml
# （PyInstaller 的 --add-data 嵌入在二进制内部，运行时在 sys._MEIPASS
#  但 worker 的 main.py 使用 "config.toml" 相对路径从 CWD 查找）
COPY workers/${WORKER_NAME}/public/config.toml /app/config.toml

# 健康检查（二进制运行时返回 0）
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD ["sh", "-c", "pgrep worker || exit 1"]

# 直接运行二进制
CMD ["/app/worker"]
