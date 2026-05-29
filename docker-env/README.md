# Docker 基础设施环境

Chongming 微服务架构的基础设施 Docker Compose 部署方案，支持**开发**与**生产**两种运行模式，涵盖 NATS 集群、PostgreSQL 主备、MinIO 分布式存储、API Gateway 双实例和 Nginx 负载均衡。

---

## 组件概览

| 组件 | 节点数 | 用途 |
|------|--------|------|
| **NATS** | 3 节点集群 | 微服务间消息通信 + JetStream KV 存储 |
| **PostgreSQL** | 主备架构 (repmgr) | 数据持久化，自动故障转移 |
| **MinIO** | 2 节点集群 | 对象 / 文件存储（擦除编码） |
| **API Gateway** (生产) | 双实例 | REST 请求转发，高可用 |
| **Nginx** (生产) | 1 实例 | 反向代理 + 负载均衡（least_conn） |

---

## 网络架构

所有服务加入 `microservices-net` 桥接网络，内部通过服务名互相访问。

```
                    ┌─────────────┐
                    │   Nginx     │  :8080 → 80
                    │  (生产)     │
                    └──────┬──────┘
                           │ least_conn
                   ┌───────┴───────┐
                   │               │
            ┌──────▼──────┐ ┌──────▼──────┐
            │ API Gateway │ │ API Gateway │  双实例
            │   inst-1    │ │   inst-2    │  自动负载均衡
            └──────┬──────┘ └──────┬──────┘
                   │               │
                   └───────┬───────┘
                           │ NATS Request/Reply
                   ┌───────┴───────┐
                   │  NATS 集群    │  3 节点
                   │  (4222-4224)  │  高可用
                   └───────┬───────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
           ┌──▼──┐    ┌───▼───┐    ┌───▼──┐
           │  Pg │    │  Pg   │    │MinIO │
           │Master│   │ Slave │    │Cluster│
           │:5432│    │:5433  │    │:9000 │
           └─────┘    └───────┘    └──────┘
```

---

## 快速开始

### 开发 / 测试环境

```bash
cd docker-env

# 启动所有基础服务（NATS + PostgreSQL + MinIO）
docker compose up -d

# 查看服务状态
docker compose ps

# 查看日志
docker compose logs -f
```

### 生产环境（含 API Gateway 双实例 + Nginx）

```bash
cd docker-env

# 构建并启动所有服务
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# 访问入口（Nginx 端口 8080）
curl http://localhost:8080/health
curl http://localhost:8080/api/v1/calc/add?a=1&b=2
```

---

## 服务详情

### NATS 集群（3 节点）

基于 NATS 2.10，配置 JetStream 和集群路由。

| 节点 | 客户端端口 | HTTP 管理端口 | 内部路由端口 |
|------|-----------|--------------|-------------|
| nats-1 | 4222 | 8222 | 6222 |
| nats-2 | 4223 | — | 6222 |
| nats-3 | 4224 | — | 6222 |

配置文件：`nats-1.conf`、`nats-2.conf`、`nats-3.conf`

### PostgreSQL 主备（repmgr 自动故障转移）

| 节点 | 外部端口 | 角色 |
|------|---------|------|
| pg-master | 5432 | 主节点（读写） |
| pg-slave | 5433 | 备节点（只读） |

**默认凭据：**
| 项目 | 值 |
|------|-----|
| 管理员密码 | `admin123` |
| 应用用户 | `myuser` |
| 应用密码 | `mypassword` |
| 数据库 | `mydb` |

### MinIO 分布式集群（2 节点）

使用擦除编码模式实现数据冗余。

| 节点 | API 端口 | Console 端口 |
|------|---------|-------------|
| minio-1 | 9000 | 9001 |
| minio-2 | 9002 | 9003 |

**默认凭据：**
- 用户名：`minioadmin`
- 密码：`minioadmin`

### API Gateway（生产环境双实例）

基于 FastAPI 的动态路由网关，接收 HTTP 请求并通过 NATS 转发到 Worker。

| 实例 | 容器名 | 内部端口 |
|------|--------|---------|
| api-gateway-1 | api-gateway-1 | 8000 |
| api-gateway-2 | api-gateway-2 | 8000 |

**特性：**
- 动态路由注册（监听 NATS `service.registry` 主题）
- NATS 集群高可用连接
- 分布式锁保护路由注册（基于 `chongming-lock`）
- 健康检查端点 `/health`

**Docker 构建方案：**

| 文件 | 用途 |
|------|------|
| `gateway.Dockerfile` | Python 运行时模式（开发） |
| `gateway-binary.Dockerfile` | PyInstaller 二进制模式（**推荐生产**） |

### Nginx 负载均衡（生产环境）

| 配置项 | 值 |
|--------|-----|
| 入口端口 | `8080`（映射到容器 80） |
| 负载均衡算法 | `least_conn`（最少连接） |
| 健康检查端点 | `GET /nginx/health` |
| 失败重试 | 超时/5xx 时最多重试 3 次 |

```nginx
upstream gateway_cluster {
    least_conn;
    server api-gateway-1:8000 max_fails=3 fail_timeout=10s;
    server api-gateway-2:8000 max_fails=3 fail_timeout=10s;
}
```

---

## 数据持久化

使用 Docker 命名卷持久化数据：

| 卷名 | 用途 |
|------|------|
| `nats1-data`、`nats2-data`、`nats3-data` | NATS 数据 |
| `pg-master-data`、`pg-slave-data` | PostgreSQL 数据 |
| `minio1-data`、`minio2-data` | MinIO 数据 |

---

## 生产部署指南

### 步骤 1：构建二进制镜像（推荐）

```bash
# 在开发机上执行
chongming binary-build gateway
chongming binary-build example

# 推送到镜像仓库
chongming binary-build gateway --tag registry.example.com/gateway:v1.0 --push
```

### 步骤 2：切换为二进制镜像

在 `docker-compose.prod.yml` 中将 `build` 块切换为预构建的 `image`：

```yaml
api-gateway-1:
  # 注释掉 build 块
  # build:
  #   context: ..
  #   dockerfile: docker-env/gateway.Dockerfile
  # 改用预构建二进制镜像
  image: chongming/gateway-binary:latest
```

### 方案 A：单机部署

```bash
cd /path/to/project/docker-env
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### 方案 B：分布式部署（多台服务器）

**基础服务服务器：**
```bash
docker compose up -d nats-1 nats-2 nats-3 pg-master pg-slave minio-1 minio-2
```

**API Gateway 服务器：**
```bash
docker pull registry.example.com/gateway:v1.0
docker run -d --name gateway --restart unless-stopped \
  --network microservices-net -p 8000:8000 \
  registry.example.com/gateway:v1.0
```

**Worker 服务器（支持水平扩容）：**
```bash
# 启动 Worker
docker run -d --name example-worker --restart unless-stopped \
  --network microservices-net \
  -e NATS_SERVERS=nats://<nats-ip>:4222 \
  registry.example.com/example:v1.0

# 水平扩容
docker run -d --name example-worker-2 registry.example.com/example:v1.0
docker run -d --name example-worker-3 registry.example.com/example:v1.0
```

### 步骤 3：验证

```bash
# 检查容器
docker ps

# 查看日志
docker logs gateway --tail 50

# 访问 API
curl http://<nginx-host>:8080/health
curl http://<nginx-host>:8080/api/v1/calc/add?a=1&b=2
```

---

## 常见问题

### Q：构建二进制镜像报错 "Readme file does not exist: README.md"

**原因：** PyInstaller 依赖 `hatchling` 构建 Python 包，需要 `README.md` 文件。

**解决：** 确保所有子模块目录下都有 `README.md` 文件。

### Q：二进制镜像运行时找不到配置文件

**原因：** 二进制运行时会从当前工作目录（`/app`）查找 `config.toml`。

**解决：** 通过卷挂载注入配置文件：
```bash
docker run -v /host/config.toml:/app/config.toml:ro chongming/example-binary:latest
```

### Q：网络通信问题

**原因：** 容器不在同一 Docker 网络。

**解决：** 所有容器需在 `microservices-net` 网络中。生产环境应使用服务名或 IP 地址，而非 `localhost`。

---

## 清理

```bash
# 停止并移除容器
docker compose down

# 同时清理数据卷（⚠️ 将删除所有数据）
docker compose down -v
