import uvicorn
from .app.core.config import load_config
from .app.core.logger import get_logger


def serve():
    """
    使用 uvicorn 启动服务

    从配置文件中加载服务器配置和日志配置，然后使用 uvicorn 启动应用服务。
    该函数适用于开发环境或单进程部署场景。

    Returns:
        None: 该函数不返回值，会阻塞运行直到服务停止
    """
    config = load_config()
    env = config["default"]["env"]
    server_config = config[env]["server"]
    log_config = config[env]["logging"]
    logger = get_logger("app")
    logger.info(f"启动服务: {server_config}")
    logger.info(f"启动日志: {log_config}")
    uvicorn.run("chongming.app:app", **server_config)


def gunicorn_serve():
    """
    使用 gunicorn 启动服务

    通过 gunicorn 作为进程管理器启动应用，使用 UvicornWorker 作为 worker 类型，
    支持多进程部署，适用于生产环境。

    从配置文件中读取服务器配置，动态设置 gunicorn 的 worker 数量、绑定地址和端口等参数。

    Returns:
        None: 该函数不返回值，会阻塞运行直到服务停止
    """
    import sys
    from gunicorn.app.wsgiapp import run

    config = load_config()
    env = config["default"]["env"]
    server_config = config[env]["server"]

    # 构建 gunicorn 命令行参数并启动服务
    sys.argv = [
        "gunicorn",
        "chongming.app:app",
        "-k",
        "uvicorn.workers.UvicornWorker",
        "-w",
        f"{server_config.get('workers', 4)}",
        "-b",
        f"{server_config.get('host', '0.0.0.0')}:{server_config.get('port', 8000)}",
    ]
    run()


if __name__ == "__main__":
    serve()
