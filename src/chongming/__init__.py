import uvicorn
from .app.core.config import load_config
from .app.core.logger import get_logger


def serve():
    config = load_config()
    env = config["default"]["env"]
    server_config = config[env]["server"]
    log_config = config[env]["logging"]
    logget = get_logger("app")
    logget.info(f"启动服务: {server_config}")
    logget.info(f"启动日志: {log_config}")
    uvicorn.run("chongming.app:app", **server_config)

def gunicorn_serve():
    """使用 gunicorn 启动服务"""
    import sys
    from gunicorn.app.wsgiapp import run
    config = load_config()
    env = config["default"]["env"]
    server_config = config[env]["server"]
    
    # 设置 gunicorn 参数
    sys.argv = [
        "gunicorn",
        "chongming.app:app",
        "-k", "uvicorn.workers.UvicornWorker",
        "-w", f"{server_config.get('workers', 4)}",
        "-b", f"{server_config.get('host', '0.0.0.0')}:{server_config.get('port', 8000)}"
    ]
    run()

if __name__ == "__main__":
    serve()
