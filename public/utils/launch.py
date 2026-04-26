from .config import ConfigLoader
import os
from module_bank import PythonToSQLite
from typing import Callable

key = None


def init_module_bank(config):
    """
    初始化模块银行系统，将指定路径下的Python模块打包并安装导入器。

    该函数会验证所有模块路径的有效性，创建PythonToSQLite打包器实例，
    列出所有可用模块，并为每个打包器安装导入器以支持模块的动态加载。

    Args:
        config (dict): 配置字典，必须包含 'production' -> 'module_system' -> 'path' 键，
                      其值为模块路径列表

    Raises:
        ValueError: 当配置的模块路径中有任何一个不存在时抛出异常
    """
    MODULE_BANK_PATH_LIST = config["production"]["module_system"]["path"]
    for module_path in MODULE_BANK_PATH_LIST:
        if not os.path.exists(module_path):
            raise ValueError(f"模块路径不存在: {module_path}")

    # 为每个模块路径创建PythonToSQLite打包器实例
    packer_list = [
        PythonToSQLite(module_path, key=key) for module_path in MODULE_BANK_PATH_LIST
    ]
    # 遍历所有打包器，列出模块信息并安装导入器
    for packer in packer_list:
        modules = packer.list_modules()
        for module in modules:
            print(f"{module['module_name']} {'[包]' if module['is_package'] else ''}")
        packer.install_importer(key=key)


def launch(run_fun: Callable[[dict, dict], None], run_mode: str):
    """
    启动应用程序，加载配置并执行指定的运行函数。

    该函数从config.toml文件中加载配置，根据运行模式获取对应的应用配置和默认配置，
    然后调用传入的运行函数执行应用程序逻辑。

    Args:
        run_fun (Callable[[dict, dict], None]): 运行函数，接收两个参数：
                                               - app_config (dict): 当前运行模式的配置
                                               - default_config (dict): 默认配置
        run_mode (str): 运行模式，用于从配置文件中获取对应模式的配置项

    Returns:
        None
    """
    config = ConfigLoader("config.toml")

    # 获取对应运行模式的配置
    default_config = config.get("default", {})
    app_config = config.get(run_mode, {})

    run_fun(app_config, default_config)
