# chongming

**基于 module_bank 的 FastAPI 快速打包脚手架 —— 一体化开发与部署方案**

chongming 视一个专注企业级应用快速落地的全栈脚手架，深度整合 **FastAPI**、**SQLModel**、**Vue 3**、**APScheduler** 和自研 **模块银行(Module-Bank)** 技术，让你能够更快完成开发，并最终产出一个 **体积不足 30 MB 的单文件可执行程序**。从本地开发到镜像化部署，一条命令完成。

---

作者: chakcy

版本: 0.1.0

[TOC]

--- 

## 核心亮点

|特性|描述|
|---|---|
|单文件交付|通过 PyInstaller 打包，最终产物为单个可执行文件 (`chongming`/`chongming.exe`)|
|模块加密|业务代码使用 Module-Bank 技术加密打包至 SQLite，运行时动态加载，有效保护源码|
|前端内嵌|Vue 3 前端构建为 SQLite VFS 虚拟文件系统，无须额外部署 Nginx 或静态文件服务|
|开箱即用|内置认证 (JWT)、权限 (RBAC)、任务调度、日志、缓存、10 分钟搭建业务骨架|
|极简容器|Docker 镜像基于 `scratch`，总大小 **30.4 MB**，内存占用约 120 MB|
|多环境配置|通过 `config.toml` 区分 developmetn / production，开发热重载、生产 Gunicorn 多进程无缝切换|

---

## 方案对比

chongming 与传统 Python Web 部署方式及当今流行的单文件分发方式相比，再交付体积、部署复杂度、源码保护和集成方面具有显著优势。

|对比维度|chongming|FastAPI + pip/venv|FastAPI + Docker (python:slim)|Nginx + uWSGI + Django|
|---|---|---|---|---|
|最终交付物|单文件可执行程序(~30MB)|源代码 + 虚拟环境 + pip 依赖|镜像 >= 150 MB|多组件组合部署|
|部署命令|`./chongming`|`source venv/bin/activate && uvicorn main:app`|`docker run ...`|多部 Nginx/uWSGI 配置|
|运行环境要求|仅需 glibc (Linux发行版自带)|需要 Python + pip + 虚拟环境|需要 Docker 引擎|Python + 系统服务|
|Python 源码保护|Module-Bank 加密 + PyArmor 混淆，磁盘无明文|源码完全暴露|镜像层内源码可见|源码暴露|
|前端集成|前端自动嵌入，单进程服务|需要单独部署前端或挂载静态目录|同左|需 Nginx 配置静态文件|
|容器镜像体积|30.4 MB (`scratch` 基镜像)|不适用|>=150 MB(`python:slim`)|多容器组合体积庞大|
|运行时内存|~120 MB (4 Gunicorn workers)|~150 MB (单 uvicorn)|~200 MB|~500 MB + (含数据库)|
|多环境切换|同一份 config.toml，开发/生产平滑切换|环境变量 + 配置文件切换|环境变量 + 多 Dockerfile|多套配置文件|
|依赖管理|打包后无外部 Python 依赖|pip requirements.txt|镜像层安装|pip + 系统包|


**总结**: chongming 在 Python 生态中实现了类似 Go 的单文件交付体验，同时保留了 Python 快速开发的灵活性和丰富的异步生态。其独有的**模块加密**与**前端内置**能力，让企业级应用的交付从“配置说明书”简化为“拷贝-执行-访问”，且运行时资源占用远低于传统 Python 容器化方案。

---

## 项目架构

```text
chongming/
├── public/                  # 公开可执行程序的启动模板
│   ├── main.py              # 打包后的主入口（PyInstaller 入口）
│   ├── server.py            # ASGI 应用加载器（从模块银行动态导入）
│   ├── config.toml           # 生产配置（打包时自动注入密钥）
│   └── utils/               # 轻量工具（配置加载、模块银行初始化）
├── src/
│   ├── chongming/           # 核心 FastAPI 应用
│   │   ├── app/             # 业务逻辑：API、模型、服务、核心组件
│   │   ├── scripts/         # 构建脚本（编码、混淆、数据库初始化）
│   │   └── __init__.py      # 服务启动入口 (uvicorn/gunicorn)
│   ├── plugins/             # 可热插拔的插件模块
│   │   ├── jwt/             # JWT 认证与缓存
│   │   ├── scheduler/       # 基于 APScheduler 的持久化任务调度
│   │   ├── mqtt/            # (预留) MQTT 客户端
│   │   └── websocket/       # (预留) WebSocket 服务
│   └── chongming-web/       # Vue 3 + Element Plus 前端
├── build/                   # 打包输出目录（可执行程序、静态文件、数据库）
├── Dockerfile               # 多阶段构建，最终基于 scratch
├── deploy.sh                # 一键部署脚本（数据持久化、端口映射）
└── pyproject.toml           # 项目与构建依赖定义
```

### 运行原理

开发时通过 `uv run serve` 直接启动 uvicon。
打包后，`chongming` 可执行文件内嵌了经过混淆的引导程序，引导程序从加密的 Module-Bank 文件 (`app.mbank`, `plugins.mbank`) 中动态加载应用模块，同时从 SQLite VFS (`static.svfs`) 提供前端静态文件。所有 Python 业务代码不暴露与明文磁盘。

---

## 快速开始

### 环境要求

- Python >= 3.8 (推荐 3.11+)
- [uv](https://docs.astral.sh/uv/) (推荐) 或 普通 pip
- Node.js >= 20.19 (仅开发前端时需要)

### 1. 克隆并安装依赖
```bash
git clone https://github.com/caixinp/chongming.git
cd chongming

# 适用 uv (自动创建虚拟环境并安装)
uv sync

# 或传统方式
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

### 2. 开发模式运行
```bash
uv run serve
```
此时系统使用 `config.toml` 中的 `[development]` 配置: 热重载开启，调试日志，CORS 全允许。

前端开发 (独立启动)
```bash
cd src/chongming-web
# 下载依赖
npm install
# 生成 api
npm run openapi
# 启动
npm run dev
```

---

## 配置体系

项目通过 `config.toml` 实现环境分离，核心节点说明:
```toml
[default]
env = "development"          # 当前环境：development 或 production

[database]
type = "sqlite"
url = "sqlite+aiosqlite:///./data/database.db"

[development.server]
host = "127.0.0.1"
port = 8000
reload = true                # 开发热重载

[production.server]
host = "0.0.0.0"
port = 8000
workers = 4                  # Gunicorn 多进程（打包后自动使用）

[production.module_system]   # 打包后从 mbank 加载模块
path = ["resources/app.mbank", "resources/plugins.mbank"]

[production.file_system]     # 打包后从 svfs 提供前端
path = "static.svfs"
```

> **打包脚本会自动**将 `secret_key` 注入到 `build/config.toml` 中，开发者无需手动处理敏感信息。

---

## 构建与打包

chongming 的打包流程集成了加密、混淆、静态资源嵌入等步骤，最终生成独立可执行文件。

```bash
uv run build
```

### 构建产物

位于 `build` 目录下

```text
build/
├── chongming           # 单文件可执行程序 (Linux) 或 chongming.exe (Windows)
├── config.toml         # 生产配置（密钥已注入）
├── resources/          # 加密的模块银行 (.mbank) 和图标
├── static.svfs         # Vue 前端虚拟文件系统
└── data/               # 初始 SQLite 数据库
```

### 打包过程详解：

1. **模块加密**
    
    使用 `module_bank.PythonToSQLite` 将 `src/chongming/app` 和 `src/plugins` 目录分别打包为加密的 `.mbank` 文件，密钥随机生成并注入启动脚本。
2. **代码混淆**

    对 `main.py`，`server.py`，`utils/*.py` 使用 PyArmor 进行代码保护。
3. **PyInstaller 打包**

    编译为单文件可执行程序，隐藏导入所有依赖项。

4. **Vue 前端构建**

    `npm run build` 后将 `dist` 目录打包到 SQLite VFS (`static.svfs`)。
5. **数据库初始化**
    自动创建初始 SQLite 数据库 (WAL 模式)，包含管理员账户 (`admin/admin`) 和基础权限集。

---

## Docker 部署

Docker 镜像采用多角度构建 + `scratch` 基础镜像，真正做到最小化。

### 构建镜像

```bash
docker build -t chongming:latest .
```

### 执行部署脚本
```bash
sudo chmod +x deploy.sh
./deploy.sh
```
部署脚本会：

- 在 `$HOME/chongming-data` 下创建 `data/`, `uploads/`, `logs/` 目录
- 若首次运行，从镜像提取初始数据库
- 启动容器并挂载上述目录，端口 `8000` 映射
- 自动设置 `--restart unless-stopped`

### 镜像特性

- 基础镜像：`scratch`（零额外依赖）
- 仅需拷贝 glibc 动态库、时区数据、CA 证书
- 最终尺寸 **30.4 MB**
- 运行时内存占用 **~120 MiB**

## 核心组件说明

### 1. 认证与权限 (JWT + RBAC)
- 使用 `bcrypt` 密码加密
- 基于磁盘缓存 (`diskcache`) 的 JWT 管理，支持多设备登录、会话限制
- 刷新 Token 机制
- 完整的 RBAC 模型: 用户、角色、权限，支持用户专属角色直接分配权限

### 2. 任务调度 (APScheduler)
- 异步调度器，支持 interval, cron, date 触发器
- 持久化至独立 SQLite 数据库，重启不丢失
- 基于文件锁的多进程互斥，避免重复执行

### 3. 静态文件服务
- 开发期间直接使用 `StaticFiles` 指向本地目录
- 打包后通过 `SVFSStaticFiles` 从 SQLite VFS 读取，实现前端内嵌
- 支持 SPA 路由回退 (`index.html`)

### 4. 日志系统
- 按天自动轮转，文件大小限制（默认 10 MB）和历史备份
- 控制台带 **HTTP 状态码颜色**输出
- 过滤第三方库 (SQLAlchemy, watchfiles 等) 噪音

### 5. 缓存
- 基于 `diskcache` 的本地持久化缓存，API 兼容 Redis 常用操作
- 提供 `@cached` 装饰器透明缓存函数结果

---

## 性能指标
|指标|数值|
|---|---|
|Docker 镜像体积|**30.4 MB**|
|运行时内存|**~121 MiB** (含 Gunicorn 4 workers)|
|数据库模式|SQLite WAL + NORMAL synchronous (写性能提升)|
|连接池|最大 20，支持池预热和连接回收|
|静态文件处理|SQLite VFS 内存级读取，无磁盘 I/O 开销|

---

## 设计理念
### 1. 极致的便携性
一切皆文件，一个可执行程序 + 配置文件即可运行完整 Web 应用。告别复杂的依赖安装与环境配置。

### 2. 源码深度保护
业务逻辑通过 Module‑Bank 加密存储于 SQLite，运行时动态导入内存，不落盘明文。配合 PyArmor 混淆，有效防止逆向。

### 3. 插件化架构
认证、调度、缓存等通用能力剥离为独立插件 (plugins/)，可插拔可替换，确保核心应用的简洁。

### 4. 渐进式架构
同一套代码支持从开发热重载到生产 Gunicorn 多进程的平滑过渡。配置即环境，无代码分支。

### 5. 最小基础设施依赖
无需 Redis、Nginx、外部数据库。SQLite 满足绝大多数中低并发场景，简化运维。

### 6. 前端一体化
Vue 前端自动打包进可执行程序，用户通过浏览器访问 http://host:8000/static/ 即可使用，真正单进程部署。

## 开发指南

### 目录约定

- 业务 API：`src/chongming/app/api/routers/`
- 数据模型：`src/chongming/app/model/`
- 服务逻辑：`src/chongming/app/service/`
- 核心组件：`src/chongming/app/core/`
- 插件扩展：`src/plugins/`

### 添加新路由

在 `src/chongming/app/api/__init__.py` 中引入你的路由模块并挂载。

### 前端开发

前端代码位于 `src/chongming-web/`，基于 Vite + Vue 3 + Element Plus。
API 客户端由 `@hey-api/openapi-ts` 自动生成，重新生成命令：
```bash
cd src/chongming-web
npm run openapi   # 需要先启动后端
```

### 打包注意事项

- 打包前务必确保没有语法错误
- 新增 Python 依赖需要在 `pyproject.toml` 的 `dev.dependencies` 添加 `pyarmor` 和 `pyinstaller`（已默认包含）
- 若添加了新的第三方库，需在 `scripts/build.py` 的 `run_pyinstaller()` 中声明对应的 --hidden-import
- Windows 下打包需事先安装 `pyarmor` 和 `pyinstaller`

--- 

## 许可证

本项目基于 [MIT License](./LICENSE) 开源。

---

**chongming** —— 让事情更简单
