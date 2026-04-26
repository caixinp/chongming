# config_loader.py - 读取config.toml的示例代码


import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# 根据Python版本选择合适的TOML解析库
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


class ConfigLoader:
    """TOML配置文件加载器

    提供配置文件的加载、访问和管理功能。支持自动查找配置文件、
    点号分隔的嵌套键访问、配置节获取以及配置重载等功能。

    Attributes:
        config_path: 配置文件的路径
        _config: 存储解析后的配置数据
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置加载器

        Args:
            config_path: 配置文件路径，如果为None则自动查找

        Raises:
            FileNotFoundError: 当无法找到配置文件时抛出异常
        """
        if config_path is None:
            # 自动查找配置文件
            config_path = self._find_config_file()

        self.config_path = Path(config_path)
        self._config: Dict[str, Any] = {}
        self.load()

    def _find_config_file(self) -> str:
        """
        自动查找配置文件

        按照预定义的优先级顺序搜索配置文件：
        1. 当前目录下的config.toml
        2. config子目录下的config.toml
        3. 用户配置目录~/.config/myapp/config.toml
        4. 系统配置目录/etc/myapp/config.toml

        Returns:
            str: 找到的第一个配置文件路径

        Raises:
            FileNotFoundError: 当所有可能的位置都未找到配置文件时抛出异常
        """
        possible_paths = [
            "config.toml",
            "config/config.toml",
            "~/.config/myapp/config.toml",
            "/etc/myapp/config.toml",
        ]

        for path in possible_paths:
            expanded_path = os.path.expanduser(path)
            if os.path.exists(expanded_path):
                return expanded_path

        raise FileNotFoundError("未找到配置文件")

    def load(self) -> None:
        """
        加载配置文件

        读取并解析TOML格式的配置文件，将配置数据存储到内部字典中。

        Raises:
            FileNotFoundError: 当配置文件不存在时抛出异常
            tomllib.TOMLDecodeError: 当配置文件格式不正确时抛出异常
        """
        if not self.config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            self._config = tomllib.loads(f.read())

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值，支持点号分隔的路径

        通过点号分隔的键路径访问嵌套的配置值。例如：
        - "database.host" 访问 {"database": {"host": "localhost"}}
        - "server.port" 访问 {"server": {"port": 8080}}

        Args:
            key: 配置键，支持点号分隔的嵌套路径
            default: 当键不存在时返回的默认值，默认为None

        Returns:
            Any: 配置值，如果键不存在则返回默认值
        """
        keys = key.split(".")
        value = self._config

        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default

    def get_section(self, section: str) -> Dict[str, Any]:
        """
        获取整个配置节

        返回指定配置节的完整字典内容，适用于需要访问某个配置节下
        所有配置项的场景。

        Args:
            section: 配置节名称

        Returns:
            Dict[str, Any]: 配置节的内容字典，如果节不存在则返回空字典
        """
        return self._config.get(section, {})

    def reload(self) -> None:
        """
        重新加载配置文件

        从磁盘重新读取配置文件并更新内部配置数据。
        适用于配置文件在运行时被修改的场景。

        Raises:
            FileNotFoundError: 当配置文件不存在时抛出异常
        """
        self.load()

    def __getitem__(self, key: str) -> Any:
        """
        支持字典式访问

        允许使用方括号语法访问配置值，如：config["database.host"]

        Args:
            key: 配置键

        Returns:
            Any: 配置值

        Raises:
            KeyError: 当键不存在且无默认值时抛出异常（通过get方法处理）
        """
        return self.get(key)

    def __contains__(self, key: str) -> bool:
        """
        检查配置是否存在

        支持使用in操作符检查配置键是否存在，如："database.host" in config

        Args:
            key: 要检查的配置键

        Returns:
            bool: 如果配置键存在且值不为None则返回True，否则返回False
        """
        return self.get(key) is not None

    @property
    def all(self) -> Dict[str, Any]:
        """
        获取所有配置

        返回完整的配置字典，适用于需要遍历或导出所有配置的场景。

        Returns:
            Dict[str, Any]: 包含所有配置的字典
        """
        return self._config
