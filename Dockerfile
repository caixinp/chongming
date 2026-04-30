# 架构参数：可选值 x86_64 或 aarch64
ARG TARGETARCH=x86_64

FROM ubuntu:24.04 AS builder

ARG TARGETARCH

# 跳过 GPG 签名验证（兼容 BM1684 等系统时间不准的设备）
RUN apt-get update -o Acquire::AllowInsecureRepositories=yes \
        -o Acquire::AllowDowngradeToInsecureRepositories=yes \
        --allow-unauthenticated 2>/dev/null || true && \
    apt-get install -y --no-install-recommends \
        -o Acquire::AllowInsecureRepositories=yes \
        --allow-unauthenticated \
        ca-certificates tzdata 2>/dev/null || true && \
    rm -rf /var/lib/apt/lists/*

COPY build/chongming /tmp/chongming

# 构建最小 rootfs
RUN \
    if [ "$TARGETARCH" = "aarch64" ]; then \
        LIB_PATH="/lib/aarch64-linux-gnu"; \
        LD_LINKER="/lib/ld-linux-aarch64.so.1"; \
        LD_LINKER_TARGET="/tmp/rootfs/lib/ld-linux-aarch64.so.1"; \
    else \
        LIB_PATH="/lib/x86_64-linux-gnu"; \
        LD_LINKER="/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2"; \
        LD_LINKER_TARGET="/tmp/rootfs/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2"; \
    fi && \
    mkdir -p /tmp/rootfs/app && \
    mkdir -p /tmp/rootfs/tmp && chmod 1777 /tmp/rootfs/tmp && \
    mkdir -p /tmp/rootfs/app/data && chmod 777 /tmp/rootfs/app/data && \
    # === aarch64 链接器路径特殊处理 ===
    if [ "$TARGETARCH" = "aarch64" ]; then \
        mkdir -p /tmp/rootfs/lib && \
        cp /lib/ld-linux-aarch64.so.1 /tmp/rootfs/lib/ && \
        mkdir -p /tmp/rootfs/lib64 && \
        ln -s /lib/ld-linux-aarch64.so.1 /tmp/rootfs/lib64/ld-linux-aarch64.so.1; \
    else \
        mkdir -p /tmp/rootfs/lib64 && \
        mkdir -p /tmp/rootfs${LIB_PATH} && \
        cp ${LIB_PATH}/ld-linux-x86-64.so.2 /tmp/rootfs${LIB_PATH}/ && \
        ln -s ${LIB_PATH}/ld-linux-x86-64.so.2 /tmp/rootfs/lib64/ld-linux-x86-64.so.2; \
    fi && \
    # === 依赖库 ===
    mkdir -p /tmp/rootfs${LIB_PATH} && \
    cp ${LIB_PATH}/libdl.so.2 /tmp/rootfs${LIB_PATH}/ && \
    cp ${LIB_PATH}/libz.so.1 /tmp/rootfs${LIB_PATH}/ && \
    cp ${LIB_PATH}/libpthread.so.0 /tmp/rootfs${LIB_PATH}/ && \
    cp ${LIB_PATH}/libc.so.6 /tmp/rootfs${LIB_PATH}/ && \
    cp ${LIB_PATH}/librt.so.1 /tmp/rootfs${LIB_PATH}/ && \
    cp ${LIB_PATH}/libm.so.6 /tmp/rootfs${LIB_PATH}/ && \
    cp ${LIB_PATH}/libutil.so.1 /tmp/rootfs${LIB_PATH}/ && \
    cp ${LIB_PATH}/libnss_dns.so.2 /tmp/rootfs${LIB_PATH}/ 2>/dev/null || true && \
    cp ${LIB_PATH}/libnss_files.so.2 /tmp/rootfs${LIB_PATH}/ 2>/dev/null || true && \
    cp ${LIB_PATH}/libresolv.so.2 /tmp/rootfs${LIB_PATH}/ 2>/dev/null || true && \
    # === 时区数据 ===
    mkdir -p /tmp/rootfs/usr/share/zoneinfo && \
    cp -r /usr/share/zoneinfo/Asia /tmp/rootfs/usr/share/zoneinfo/ 2>/dev/null || true && \
    cp /usr/share/zoneinfo/UTC /tmp/rootfs/usr/share/zoneinfo/ 2>/dev/null || true && \
    # === 证书和 DNS ===
    mkdir -p /tmp/rootfs/etc/ssl/certs && \
    cp /etc/ssl/certs/ca-certificates.crt /tmp/rootfs/etc/ssl/certs/ 2>/dev/null || true && \
    echo "hosts: files dns" > /tmp/rootfs/etc/nsswitch.conf && \
    # === /proc /sys /dev ===
    mkdir -p /tmp/rootfs/proc /tmp/rootfs/sys /tmp/rootfs/dev

FROM scratch

ARG TARGETARCH

COPY --from=builder /tmp/rootfs/ /

COPY build/chongming /app/chongming
COPY build/config.toml /app/config.toml
COPY build/resources/ /app/resources/
COPY build/static.svfs /app/static.svfs
COPY build/data /app/data

WORKDIR /app

EXPOSE 8000

CMD ["./chongming"]
