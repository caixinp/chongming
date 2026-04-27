FROM debian:bookworm-slim AS builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY build/chongming /tmp/chongming

RUN mkdir -p /tmp/rootfs/app && \
    # === 临时目录 ===
    mkdir -p /tmp/rootfs/tmp && \
    chmod 1777 /tmp/rootfs/tmp && \
    # === 数据目录 ===
    mkdir -p /tmp/rootfs/app/data && \
    chmod 777 /tmp/rootfs/app/data && \
    # === 解释器目录 ===
    mkdir -p /tmp/rootfs/lib64 && \
    mkdir -p /tmp/rootfs/lib/x86_64-linux-gnu && \
    cp /lib/x86_64-linux-gnu/ld-linux-x86-64.so.2 /tmp/rootfs/lib/x86_64-linux-gnu/ && \
    ln -s /lib/x86_64-linux-gnu/ld-linux-x86-64.so.2 /tmp/rootfs/lib64/ld-linux-x86-64.so.2 && \
    # === 依赖库 ===
    cp /lib/x86_64-linux-gnu/libdl.so.2 /tmp/rootfs/lib/x86_64-linux-gnu/ && \
    cp /lib/x86_64-linux-gnu/libz.so.1 /tmp/rootfs/lib/x86_64-linux-gnu/ && \
    cp /lib/x86_64-linux-gnu/libpthread.so.0 /tmp/rootfs/lib/x86_64-linux-gnu/ && \
    cp /lib/x86_64-linux-gnu/libc.so.6 /tmp/rootfs/lib/x86_64-linux-gnu/ && \
    cp /lib/x86_64-linux-gnu/librt.so.1 /tmp/rootfs/lib/x86_64-linux-gnu/ && \
    cp /lib/x86_64-linux-gnu/libm.so.6 /tmp/rootfs/lib/x86_64-linux-gnu/ && \
    cp /lib/x86_64-linux-gnu/libutil.so.1 /tmp/rootfs/lib/x86_64-linux-gnu/ && \
    cp /lib/x86_64-linux-gnu/libnss_dns.so.2 /tmp/rootfs/lib/x86_64-linux-gnu/ 2>/dev/null || true && \
    cp /lib/x86_64-linux-gnu/libnss_files.so.2 /tmp/rootfs/lib/x86_64-linux-gnu/ 2>/dev/null || true && \
    cp /lib/x86_64-linux-gnu/libresolv.so.2 /tmp/rootfs/lib/x86_64-linux-gnu/ 2>/dev/null || true && \
    # === 时区数据 ===
    mkdir -p /tmp/rootfs/usr/share/zoneinfo && \
    cp -r /usr/share/zoneinfo/Asia /tmp/rootfs/usr/share/zoneinfo/ && \
    cp /usr/share/zoneinfo/UTC /tmp/rootfs/usr/share/zoneinfo/ && \
    # === 证书和 DNS ===
    mkdir -p /tmp/rootfs/etc/ssl/certs && \
    cp /etc/ssl/certs/ca-certificates.crt /tmp/rootfs/etc/ssl/certs/ && \
    echo "hosts: files dns" > /tmp/rootfs/etc/nsswitch.conf && \
    # === /proc /sys /dev ===
    mkdir -p /tmp/rootfs/proc /tmp/rootfs/sys /tmp/rootfs/dev

FROM scratch

COPY --from=builder /tmp/rootfs/ /

COPY build/chongming /app/chongming
COPY build/config.toml /app/config.toml
COPY build/resources/ /app/resources/
COPY build/static.svfs /app/static.svfs
COPY build/data /app/data

WORKDIR /app

EXPOSE 8000

CMD ["./chongming"]