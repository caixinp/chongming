from .config import ConfigLoader
import os
from module_bank import PythonToSQLite
from typing import Callable

key = None


def init_module_bank(config):
    MODULE_BANK_PATH_LIST = config["production"]["module_system"]["path"]
    for module_path in MODULE_BANK_PATH_LIST:
        if os.path.exists(module_path) == False:
            raise ValueError(f"模块路径不存在: {module_path}")

    packer_list = [
        PythonToSQLite(module_path, key=key) for module_path in MODULE_BANK_PATH_LIST
    ]
    for packer in packer_list:
        modules = packer.list_modules()
        for module in modules:
            print(f"{module['module_name']} {'[包]' if module['is_package'] else ''}")
        packer.install_importer(key=key)


def launch(run_fun: Callable[[dict, dict], None], run_mode: str):
    config = ConfigLoader("config.toml")

    # 获取对应运行模式的配置
    default_config = config.get("default", {})
    app_config = config.get(run_mode, {})

    run_fun(app_config, default_config)
