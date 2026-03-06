from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.exc import OperationalError

from .core.config import get_config
from .core.jwt_cache import get_jwt_cache
from .core.logger import get_logger
from .api import api_router

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

    yield  # 应用运行期间

    # 关闭时：释放引擎
    await engine.dispose()
    get_jwt_cache().close()


cors = config[env].get("cors", {})

# 创建 FastAPI 应用
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
app.include_router(api_router, prefix="/api/v1")


# 根路由
@app.get("/", summary="根路径")
async def root():
    """根路径，返回应用信息"""
    return {
        "message": f"欢迎使用 {config["default"]["app"]["name"]}",
        "version": config["default"]["app"]["version"],
        "docs": "/docs" if config[env]["debug"] else None,
        "health": "/api/v1/health",
    }


# 全局异常处理器
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """全局异常处理器"""
    logger.error(f"全局异常: {exc}")
    return {
        "error": "内部服务器错误",
        "detail": str(exc) if config[env]["debug"] else "请查看服务器日志",
    }
