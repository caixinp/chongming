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


if __name__ == "__main__":
    serve()
