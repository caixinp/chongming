# ================================================
# Builder stage: build all local packages
# ================================================
FROM python:3.12-slim AS builder

WORKDIR /build

# No gcc needed - all dependencies are pure Python (fastapi, nats-py, etc.)

# Step 1: Copy only package metadata first (pyproject.toml + README.md)
# This layer is cached unless metadata files change
COPY utils/config/pyproject.toml utils/config/README.md utils/config/
COPY utils/logging/pyproject.toml utils/logging/README.md utils/logging/
COPY utils/cache/pyproject.toml utils/cache/README.md utils/cache/
COPY utils/lock/pyproject.toml utils/lock/README.md utils/lock/
COPY utils/worker/pyproject.toml utils/worker/README.md utils/worker/
COPY api_gateway/pyproject.toml api_gateway/README.md api_gateway/

# Step 2: Copy actual source code (smaller, changes more frequently)
COPY utils/config/src utils/config/src
COPY utils/logging/src utils/logging/src
COPY utils/cache/src utils/cache/src
COPY utils/lock/src utils/lock/src
COPY utils/worker/src utils/worker/src
COPY api_gateway/src api_gateway/src

# Step 3: Install all packages
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir \
    ./utils/config \
    ./utils/logging \
    ./utils/cache \
    ./utils/lock \
    ./utils/worker \
    ./api_gateway

# ================================================
# Production stage: minimal runtime image
# ================================================
FROM python:3.12-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Create config directory and copy production config from public/
RUN mkdir -p /app/config
COPY api_gateway/public/config.toml /app/config/config.toml

# Copy static files
COPY api_gateway/public /app/public

# Expose gateway port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Run with gunicorn + uvicorn workers for production
CMD ["sh", "-c", "cd /app/config && python -m chongming_gateway.scripts.build && python -c \"from chongming_gateway import gunicorn_serve; gunicorn_serve()\""]
