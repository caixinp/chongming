# ================================================
# Builder stage: PyInstaller 打包 API Gateway 为独立二进制
# ================================================
FROM python:3.12-slim AS builder

WORKDIR /build

# Step 1: Copy package metadata first (pyproject.toml + README.md)
COPY utils/config/pyproject.toml utils/config/README.md utils/config/
COPY utils/logging/pyproject.toml utils/logging/README.md utils/logging/
COPY utils/cache/pyproject.toml utils/cache/README.md utils/cache/
COPY utils/lock/pyproject.toml utils/lock/README.md utils/lock/
COPY utils/worker/pyproject.toml utils/worker/README.md utils/worker/
COPY api_gateway/pyproject.toml api_gateway/README.md api_gateway/

# Step 2: Copy source code
COPY utils/config/src utils/config/src
COPY utils/logging/src utils/logging/src
COPY utils/cache/src utils/cache/src
COPY utils/lock/src utils/lock/src
COPY utils/worker/src utils/worker/src
COPY api_gateway/src api_gateway/src
COPY api_gateway/public api_gateway/public
COPY api_gateway/config.toml api_gateway/

# Step 3: Install system dependencies for PyInstaller (objdump, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    binutils \
    && rm -rf /var/lib/apt/lists/*

# Step 4: Install all dependencies + pyinstaller
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir \
    ./utils/config \
    ./utils/logging \
    ./utils/cache \
    ./utils/lock \
    ./utils/worker \
    ./api_gateway \
    pyinstaller

# Step 5: 删除 mypyc 编译的 .so 文件，保留 pydantic_core 等 Rust/C 扩展
# tomli 等依赖的 mypyc 编译会产生随机命名模块（如 955cd85d__mypyc），
# PyInstaller 无法自动发现，运行时会导致 ModuleNotFoundError。
# 注意：只删除 mypyc 编译的 .so，不删除 pydantic_core (Rust) 等原生扩展
# 注意：mypyc 编译会替换原始 .py 文件，删除 .so 后需要重新安装纯 Python 版本
RUN find /usr/local/lib/python3.12/site-packages -name "*.so" -path "*mypyc*" -delete 2>/dev/null; \
    echo "Deleted mypyc compiled .so files (preserving native extensions like pydantic_core)"

# Step 5.1: 重新安装被 mypyc 覆盖的依赖为纯 Python 版本
# mypyc 编译会替换包的 .py 源文件为 .so，删除 .so 后纯 Python 回退代码不存在，
# 需要强制重新安装纯 Python 版本以保证 PyInstaller 运行时能找到模块。
# 目前已知受影响依赖：tomli
RUN pip install --no-compile --force-reinstall --no-binary tomli tomli; \
    echo "Reinstalled tomli as pure Python (no mypyc compilation)"

# Step 6: Prepare the entry point script for PyInstaller
# PyInstaller needs a .py entry point; we create a thin wrapper
RUN echo '#!/usr/bin/env python3' > /build/entry_gateway.py && \
    echo '"""PyInstaller entry point for API Gateway"""' >> /build/entry_gateway.py && \
    echo 'import os' >> /build/entry_gateway.py && \
    echo 'import sys' >> /build/entry_gateway.py && \
    echo '' >> /build/entry_gateway.py && \
    echo '# PyInstaller --onefile extracts to a temp dir (sys._MEIPASS)' >> /build/entry_gateway.py && \
    echo '# config.toml is bundled there via --add-data, so chdir to it' >> /build/entry_gateway.py && \
    echo 'if hasattr(sys, "_MEIPASS"):' >> /build/entry_gateway.py && \
    echo '    os.chdir(sys._MEIPASS)' >> /build/entry_gateway.py && \
    echo '' >> /build/entry_gateway.py && \
    echo '# Run build script first to generate routes' >> /build/entry_gateway.py && \
    echo 'from chongming_gateway.scripts.build import build' >> /build/entry_gateway.py && \
    echo 'build()' >> /build/entry_gateway.py && \
    echo '' >> /build/entry_gateway.py && \
    echo '# Then start gunicorn' >> /build/entry_gateway.py && \
    echo 'from chongming_gateway import gunicorn_serve' >> /build/entry_gateway.py && \
    echo 'gunicorn_serve()' >> /build/entry_gateway.py

# Step 7: Build single binary with PyInstaller
# uvicorn/gunicorn use dynamic imports extensively, need careful hidden-imports
RUN pyinstaller --onefile \
    --name "gateway" \
    --hidden-import="uvicorn" \
    --hidden-import="uvicorn.workers" \
    --hidden-import="uvicorn.workers.UvicornWorker" \
    --hidden-import="gunicorn" \
    --hidden-import="gunicorn.app" \
    --hidden-import="gunicorn.app.wsgiapp" \
    --hidden-import="fastapi" \
    --hidden-import="starlette" \
    --hidden-import="pydantic" \
    --hidden-import="pydantic_core" \
    --hidden-import="pydantic_core._pydantic_core" \
    --hidden-import="nats" \
    --hidden-import="nats.aio" \
    --hidden-import="nats.aio.client" \
    --hidden-import="tomli" \
    --hidden-import="tomli._re" \
    --hidden-import="chongming_gateway" \
    --hidden-import="chongming_gateway.app" \
    --hidden-import="chongming_gateway.app.api" \
    --hidden-import="chongming_gateway.app.core" \
    --hidden-import="chongming_gateway.app.core.dynamic_route" \
    --hidden-import="chongming_gateway.app.core.nats_client" \
    --hidden-import="chongming_gateway.scripts" \
    --hidden-import="chongming_gateway.scripts.build" \
    --hidden-import="chongming_config" \
    --hidden-import="chongming_logging" \
    --hidden-import="chongming_cache" \
    --hidden-import="chongming_lock" \
    --hidden-import="multipart" \
    --collect-all="chongming_gateway" \
    --collect-all="uvicorn" \
    --collect-all="gunicorn" \
    --collect-all="fastapi" \
    --collect-all="starlette" \
    --collect-all="pydantic" \
    --add-data "api_gateway/public/config.toml:." \
    --add-data "api_gateway/public:public" \
    --distpath /build/dist \
    --workpath /build/pyibuild \
    --specpath /build \
    /build/entry_gateway.py

# ================================================
# Production stage: 最小化运行镜像
# ================================================
# 使用 debian:stable-slim 作为基础镜像（替代 busybox:glibc）
# 因为 PyInstaller 二进制需要 libdl.so.2 等共享库，busybox 不包含
FROM debian:stable-slim

WORKDIR /app

# 复制二进制
COPY --from=builder /build/dist/gateway /app/gateway

# 注意：配置和静态文件已通过 PyInstaller --add-data 打包进二进制内部，
# 运行时通过 sys._MEIPASS 访问，无需单独复制。

# 健康检查
HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD ["sh", "-c", "pgrep gateway || exit 1"]

# 暴露端口
EXPOSE 8000

# 运行二进制
CMD ["/app/gateway"]
