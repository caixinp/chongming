# 使用 Debian 的极简版，确保有基础的 glibc（推荐）
FROM debian:bookworm-slim

# 可选：设置时区、安装 ca-certificates 等
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 复制打包好的可执行文件
COPY build/chongming /app/

# 复制运行时需要的静态资源、配置文件、.mbank 等
COPY build/config.toml /app/
COPY build/resources/ /app/resources/
COPY build/static.svfs /app/

# 暴露端口
EXPOSE 8000

# 启动
CMD ["./chongming"]