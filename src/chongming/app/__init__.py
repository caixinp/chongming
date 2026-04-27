import time
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlmodel import SQLModel, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.exc import OperationalError

from .core.config import get_config
from .core.cache import get_cache
from .core.logger import get_logger
from .core.static_files import SVFSStaticFiles
from .api import api_router
from .task import init_tasks_callback

from plugins.scheduler.scheduler import get_task_service_instance


config = get_config()
cache = get_cache()
logger = get_logger("app")


try:
    env = config["default"]["env"]
except KeyError:  # pragma: no cover
    raise ValueError("配置不存在")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理函数，负责应用的启动和关闭时的资源初始化与清理。

    在应用启动时：
    - 初始化JWT缓存
    - 创建异步数据库引擎和会话工厂
    - 在开发环境下创建数据库表
    - 初始化定时任务服务

    在应用关闭时：
    - 关闭定时任务服务
    - 释放数据库引擎资源
    - 关闭缓存连接

    参数:
        app: FastAPI应用实例

    Yields:
        None: 应用运行期间保持上下文激活
    """
    from plugins import hello
    from plugins.jwt.jwt_cache import get_jwt_cache

    get_jwt_cache(config, cache)

    hello()
    database = config["database"]
    database_type = database["type"]
    database_config = database.get(database_type, None)
    if database_config is None:
        raise ValueError("配置不存在")
    database_path = database.get("database_path", None)
    if database_path:
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    engine_config = {k: v for k, v in database_config.items() if k != "database_path"}

    engine = create_async_engine(database["url"], **engine_config)
    async_session_maker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    app.state.engine = engine
    app.state.async_session_maker = async_session_maker

    if env == "development":
        async with engine.begin() as conn:
            if database_type == "sqlite":
                await conn.execute(text("PRAGMA journal_mode=WAL"))
                await conn.execute(text("PRAGMA synchronous=NORMAL"))
            try:
                await conn.run_sync(
                    lambda conn: SQLModel.metadata.create_all(
                        bind=conn, checkfirst=True
                    )
                )
            except OperationalError as e:
                if "already exists" in str(e):
                    raise

    task_service = get_task_service_instance(
        config, get_logger("scheduler"), async_session_maker
    )
    app.state.task_service = task_service
    await task_service.start(init_tasks_callback)

    yield

    await task_service.shutdown(wait=True)
    await engine.dispose()
    cache.close()


cors = config[env].get("cors", {})
app = FastAPI(
    title=config["default"]["app"]["name"],
    version=config["default"]["app"]["version"],
    description=config["default"]["app"]["description"],
    docs_url="/docs" if config[env]["debug"] else None,
    redoc_url="/redoc" if config[env]["debug"] else None,
    openapi_url="/openapi.json" if config[env]["debug"] else None,
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware, **cors)

app.include_router(api_router, prefix=config["default"]["prefix"])


@app.middleware("http")
async def access_log_middleware(request: Request, call_next):
    """
    HTTP访问日志中间件，记录每个请求的详细信息。

    记录的信息包括：
    - 请求方法和路径
    - 响应状态码
    - 请求处理时长（毫秒）
    - 客户端IP地址

    参数:
        request: FastAPI请求对象
        call_next: 下一个中间件或路由处理函数

    返回:
        Response: 处理后的响应对象
    """
    start = time.perf_counter()
    response = await call_next(request)
    duration = (time.perf_counter() - start) * 1000
    client = request.client.host if request.client else "-"

    logger.info(
        f"{request.method} {request.url.path} status={response.status_code} "
        f"duration={duration:.2f}ms client={client}",
        extra={"status_code": response.status_code},
    )
    return response


@app.get("/", summary="根路径")
async def root():
    """
    根路径端点，返回应用的基本信息。

    返回:
        dict: 包含应用名称、版本、文档地址和健康检查地址的字典
    """
    return {
        "message": f"欢迎使用 {config['default']['app']['name']}",
        "version": config["default"]["app"]["version"],
        "docs": "/docs" if config[env]["debug"] else None,
        "health": f"{config['default']['prefix']}/health",
    }


# from pydantic import BaseModel


# class TaskRequest(BaseModel):
#     task_name: str
#     interval: int


# @app.post("/schedule")
# async def add_task(
#     request: TaskRequest, task_service: TaskService = Depends(get_task_service)
# ):
#     """添加定时任务接口"""
#     job = await task_service.add_interval_job(
#         execute_background_task,
#         seconds=request.interval,
#         args=[request.task_name],
#         job_id=request.task_name,
#     )
#     return {"status": "success", "job_id": job.id}

config = get_config()
IMAGE_DIR = Path(f"./{config['default']['upload_path']}/images")
app.mount(
    f"{config['default']['prefix']}/images",
    StaticFiles(directory=f"./{config['default']['upload_path']}/images"),
    name="images",
)

if vfs_db_path := config[env].get("file_system", {}).get("path", None):
    logger.info("静态文件已存在，将使用静态文件服务")
    static_files_handler = SVFSStaticFiles(directory="/", vfs_db_path=vfs_db_path)
    app.mount("/static", static_files_handler, name="static")


@app.exception_handler(Exception)
async def global_exception_handler(_: Request, exc: Exception):
    """
    全局异常处理器，捕获并处理应用中未捕获的异常。

    在调试模式下返回详细的异常信息，在生产模式下返回通用错误提示。

    参数:
        _: FastAPI请求对象（未使用）
        exc: 捕获到的异常对象

    返回:
        JSONResponse: 包含错误信息的JSON响应，状态码为500
    """
    logger.error(f"全局异常: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "内部服务器错误",
            "detail": str(exc) if config[env]["debug"] else "请查看服务器日志",
        },
    )
