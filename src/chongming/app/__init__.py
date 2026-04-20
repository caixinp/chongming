from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlmodel import SQLModel, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.exc import OperationalError
from pydantic import BaseModel

from .core.config import get_config
from .core.cache import get_cache
from .core.logger import get_logger
from .core.scheduler import get_task_service_instance
from .core.static_files import SVFSStaticFiles
from .api import api_router
from .task import init_tasks_callback


class TaskRequest(BaseModel):
    task_name: str
    interval: int


config = get_config()
logger = get_logger("app")


try:
    env = config["default"]["env"]
except KeyError:  # pragma: no cover
    raise ValueError("配置不存在")


# 生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    from plugins import hello

    hello()
    database = config["database"]
    database_type = database["type"]
    database_config = database.get(database_type, None)
    if database_config is None:
        raise ValueError("配置不存在")

    # 启动时：创建引擎和会话工厂，初始化数据库表
    engine = create_async_engine(database["url"], **database_config)
    async_session_maker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    # 将资源存储到 app.state
    app.state.engine = engine
    app.state.async_session_maker = async_session_maker

    # 创建表（异步方式）
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

    # 启动时：初始化任务服务
    task_service = get_task_service_instance(async_session_maker)
    app.state.task_service = task_service
    await task_service.start(init_tasks_callback)

    yield  # 应用运行期间

    # 关闭时：释放引擎
    await task_service.shutdown(wait=True)
    await engine.dispose()
    get_cache().close()


# 创建 FastAPI 应用
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

# 添加 CORS 中间件
app.add_middleware(CORSMiddleware, **cors)

# 添加路由
app.include_router(api_router, prefix=config["default"]["prefix"])


# 根路由
@app.get("/", summary="根路径")
async def root():
    """根路径，返回应用信息"""
    return {
        "message": f"欢迎使用 {config['default']['app']['name']}",
        "version": config["default"]["app"]["version"],
        "docs": "/docs" if config[env]["debug"] else None,
        "health": f"{config['default']['prefix']}/health",
    }


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

# 挂载静态文件
config = get_config()
IMAGE_DIR = Path(f"./{config['default']['upload_path']}/images")
app.mount(
    f"{config['default']['prefix']}/images",
    StaticFiles(directory=f"./{config['default']['upload_path']}/images"),
    name="images",
)

# 挂载前端静态文件
if vfs_db_path := config[env].get("file_system", {}).get("path", None):
    logger.info("静态文件已存在，将使用静态文件服务")
    static_files_handler = SVFSStaticFiles(directory="/", vfs_db_path=vfs_db_path)
    app.mount("/static", static_files_handler, name="static")


# 全局异常处理器
@app.exception_handler(Exception)
async def global_exception_handler(_: Request, exc: Exception):
    """全局异常处理器"""
    logger.error(f"全局异常: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "内部服务器错误",
            "detail": str(exc) if config[env]["debug"] else "请查看服务器日志",
        },
    )
