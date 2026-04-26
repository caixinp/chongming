# server.py
import sys
from utils.launch import init_module_bank
from utils.config import ConfigLoader

# 加载配置文件并初始化模块银行
config = ConfigLoader("config.toml")
init_module_bank(config)

# 从数据库动态导入 app 模块
# 该模块存储在 SQLite 数据库中，通过自定义导入机制加载
try:
    import app  # type: ignore

    app_instance = app.app
except ImportError as e:
    print(f"无法从数据库导入 app 模块: {e}")
    sys.exit(1)

# 暴露 ASGI 应用实例，供 uvicorn 服务器使用
app = app_instance
