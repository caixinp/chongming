# ================================================
# Builder stage: compile Rust worker binary
# ================================================
FROM rust:bookworm AS builder

ARG WORKER_NAME
ARG RUST_BUILD_MODE=release
ENV WORKER_NAME=${WORKER_NAME}

WORKDIR /build

# Step 1: Copy dependency manifests first (for caching)
# Copy the shared Rust worker library manifest
COPY utils/rust/worker/Cargo.toml utils/rust/worker/
COPY utils/rust/worker/src utils/rust/worker/src

# Copy the worker's own manifest
COPY workers/${WORKER_NAME}/Cargo.toml workers/${WORKER_NAME}/

# Step 2: Create a dummy main.rs to build dependencies (for layer caching)
RUN mkdir -p workers/${WORKER_NAME}/src && \
    echo "fn main() {}" > workers/${WORKER_NAME}/src/main.rs

# Step 3: Build dependencies (this layer is cached unless Cargo.toml changes)
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/build/target \
    if [ "$RUST_BUILD_MODE" = "release" ]; then \
        cargo build --release --manifest-path workers/${WORKER_NAME}/Cargo.toml; \
    else \
        cargo build --manifest-path workers/${WORKER_NAME}/Cargo.toml; \
    fi

# Step 4: Copy actual source code and rebuild
COPY workers/${WORKER_NAME}/src workers/${WORKER_NAME}/src
COPY utils/rust/worker/ utils/rust/worker/

# Step 5: Touch main.rs to force recompilation with real source
RUN touch workers/${WORKER_NAME}/src/main.rs

# Step 6: Build the actual binary
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/build/target \
    if [ "$RUST_BUILD_MODE" = "release" ]; then \
        cargo build --release --manifest-path workers/${WORKER_NAME}/Cargo.toml && \
        cp workers/${WORKER_NAME}/target/release/${WORKER_NAME} /build/worker; \
    else \
        cargo build --manifest-path workers/${WORKER_NAME}/Cargo.toml && \
        cp workers/${WORKER_NAME}/target/debug/${WORKER_NAME} /build/worker; \
    fi

# ================================================
# Production stage: minimal runtime image
# ================================================
FROM debian:stable-slim

ARG WORKER_NAME
ENV WORKER_NAME=${WORKER_NAME}

WORKDIR /app

# Install minimal runtime dependencies (glibc, ca-certificates for SSL)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy the compiled Rust binary
COPY --from=builder /build/worker /app/worker

# Copy production config (from public/ directory, same as Python worker)
COPY workers/${WORKER_NAME}/public/config.toml /app/config.toml

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD ["sh", "-c", "pgrep worker || exit 1"]

# Run the worker (config.toml path is passed as arg or default)
CMD ["/app/worker", "/app/config.toml"]
