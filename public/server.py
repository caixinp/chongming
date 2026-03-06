# server.py
import sys
from utils.launch import init_module_bank
from utils.config import ConfigLoader

config = ConfigLoader("config.toml")
init_module_bank(config)

# 从数据库导入真正的 app 模块
try:
    import app  # type: ignore # 此时会从 SQLite 数据库加载

    app_instance = app.app  # 获取 FastAPI 实例
except ImportError as e:
    print(f"无法从数据库导入 app 模块: {e}")
    sys.exit(1)

# 暴露 ASGI 应用变量，供 uvicorn 使用
app = app_instance
