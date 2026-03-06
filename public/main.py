# main.py - 修复 reload 问题
#!/usr/bin/env python3
"""
FastAPI + Tortoise-ORM + chongming 示例
主入口文件，适配 chongming 打包系统
"""
import sys
from utils.launch import launch
from multiprocessing import freeze_support
import server


def app_run(app_config: dict, default_config: dict):
    """
    应用运行函数 - 适配模块银行环境

    Args:
        app_config: 应用配置
        default_config: 默认配置
    """
    import uvicorn
    from app.core.logger import setup_logging, get_logger  # type: ignore

    setup_logging(app_config["logging"])
    logger = get_logger("app")

    # 获取服务器配置
    server_config = app_config.get("server", {})
    host = server_config.get("host", "0.0.0.0")
    port = server_config.get("port", 8000)

    # 打包环境强制禁用重载
    is_frozen = getattr(sys, "frozen", False)
    reload = False if is_frozen else server_config.get("reload", False)
    workers = server_config.get("workers", 4)

    # 显示启动信息
    env = app_config.get("env", "development")
    logger.info("=" * 50)
    logger.info(f"🚀 启动 {default_config.get('app.name', 'FastAPI 应用')}")
    logger.info(f"📦 版本: {default_config.get('app.version', '1.0.0')}")
    logger.info(f"🌍 环境: {env}")
    logger.info(f"📍 地址: http://{host}:{port}")
    logger.info(f"📚 文档: http://{host}:{port}/docs")
    logger.info(f"🔧 调试: {'启用' if app_config.get('debug', False) else '禁用'}")
    logger.info(f"🔄 重载: {'启用' if reload else '禁用'}")
    logger.info(f"👥 Workers: {workers}")
    logger.info("=" * 50)

    uvicorn.run(
        "server:app",
        host=host,
        port=port,
        reload=reload,
        workers=workers,
        log_level="debug" if app_config.get("debug", False) else "info",
        access_log=True,
    )


def main():
    freeze_support()
    launch(app_run, "production")


if __name__ == "__main__":
    main()
