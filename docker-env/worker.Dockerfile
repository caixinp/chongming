# ================================================
# Builder stage: build all local packages
# ================================================
FROM python:3.12-slim AS builder

ARG WORKER_NAME
ENV WORKER_NAME=${WORKER_NAME}

WORKDIR /build

# No gcc needed - all dependencies are pure Python (nats-py, chongming-*, etc.)

# Step 1: Copy only package metadata first (pyproject.toml + README.md)
# This layer is cached unless metadata files change
COPY utils/config/pyproject.toml utils/config/README.md utils/config/
COPY utils/logging/pyproject.toml utils/logging/README.md utils/logging/
COPY utils/cache/pyproject.toml utils/cache/README.md utils/cache/
COPY utils/lock/pyproject.toml utils/lock/README.md utils/lock/
COPY utils/worker/pyproject.toml utils/worker/README.md utils/worker/
COPY workers/${WORKER_NAME}/pyproject.toml workers/${WORKER_NAME}/README.md workers/${WORKER_NAME}/

# Step 2: Copy actual source code (smaller, changes more frequently)
COPY utils/config/src utils/config/src
COPY utils/logging/src utils/logging/src
COPY utils/cache/src utils/cache/src
COPY utils/lock/src utils/lock/src
COPY utils/worker/src utils/worker/src

# Step 3: Install all dependencies (utils only, before worker code)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir \
    ./utils/config \
    ./utils/logging \
    ./utils/cache \
    ./utils/lock \
    ./utils/worker

# Step 4: Copy worker source code last (changes most frequently)
COPY workers/${WORKER_NAME}/ workers/${WORKER_NAME}/

# Step 5: Install the worker (only the worker itself, deps already cached)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir ./workers/${WORKER_NAME}

# ================================================
# Production stage: minimal runtime image
# ================================================
FROM python:3.12-slim

ARG WORKER_NAME
ENV WORKER_NAME=${WORKER_NAME}

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy worker source code (main.py + other modules)
COPY --from=builder /build/workers/${WORKER_NAME}/*.py /app/

# Copy production config from public/ as default config.toml
COPY workers/${WORKER_NAME}/public/config.toml /app/config.toml

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import sys; sys.exit(0)" || exit 1

# Run the worker
CMD ["sh", "-c", "python main.py"]
