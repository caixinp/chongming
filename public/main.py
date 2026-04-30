# main.py - 修复 reload 问题
#!/usr/bin/env python3
"""
FastAPI chongming 示例
主入口文件，适配 chongming 打包系统
"""
import os
import sys
import platform
from utils.launch import launch
from multiprocessing import freeze_support
import server

use_shell = platform.system() == "Windows"


def app_run(app_config: dict, default_config: dict):
    """
    应用运行函数 - 适配模块银行环境

    Args:
        app_config: 应用配置字典，包含服务器配置、环境设置等
        default_config: 默认配置字典，包含应用名称、版本等基础信息

    Returns:
        None: 此函数不返回值，直接启动服务器并阻塞运行
    """
    from app.core.logger import get_logger  # type: ignore

    logger = get_logger("app")

    # 获取服务器配置
    server_config = app_config.get("server", {})
    host = server_config.get("host", "0.0.0.0")
    port = server_config.get("port", 8000)
    timeout_keep_alive = server_config.get("timeout_keep_alive", 5)

    # 打包环境强制禁用重载
    is_frozen = getattr(sys, "frozen", False)
    reload = False if is_frozen else server_config.get("reload", False)
    # 支持通过环境变量 APP_WORKERS 覆盖 worker 数量（方便嵌入式设备调优）
    default_workers = server_config.get("workers", 4)
    workers = int(os.environ.get("APP_WORKERS", str(default_workers)))

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

    # 根据操作系统选择不同的服务器启动方式
    if use_shell:
        import uvicorn

        uvicorn.run(
            "server:app",
            host=host,
            port=port,
            reload=reload,
            workers=workers,
            log_level="debug" if app_config.get("debug", False) else "info",
            access_log=False,
            timeout_keep_alive=timeout_keep_alive,
        )
    else:
        from gunicorn.app.wsgiapp import run

        sys.argv = [
            "gunicorn",
            "server:app",
            "-k",
            "uvicorn.workers.UvicornWorker",
            "-w",
            str(workers),
            "-b",
            f"{host}:{port}",
        ]
        run()


def main():
    """
    主函数入口 - 初始化多进程支持并启动应用

    Returns:
        None: 此函数不返回值，调用launch函数启动应用
    """
    freeze_support()
    launch(app_run, "production")


if __name__ == "__main__":
    main()
