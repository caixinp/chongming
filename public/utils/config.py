# config_loader.py - 读取config.toml的示例代码


import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


class ConfigLoader:
    """TOML配置文件加载器"""

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置加载器

        Args:
            config_path: 配置文件路径，如果为None则自动查找
        """
        if config_path is None:
            # 自动查找配置文件
            config_path = self._find_config_file()

        self.config_path = Path(config_path)
        self._config: Dict[str, Any] = {}
        self.load()

    def _find_config_file(self) -> str:
        """自动查找配置文件"""
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
        """加载配置文件"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            self._config = tomllib.loads(f.read())

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值，支持点号分隔的路径"""
        keys = key.split(".")
        value = self._config

        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default

    def get_section(self, section: str) -> Dict[str, Any]:
        """获取整个配置节"""
        return self._config.get(section, {})

    def reload(self) -> None:
        """重新加载配置文件"""
        self.load()

    def __getitem__(self, key: str) -> Any:
        """支持字典式访问"""
        return self.get(key)

    def __contains__(self, key: str) -> bool:
        """检查配置是否存在"""
        return self.get(key) is not None

    @property
    def all(self) -> Dict[str, Any]:
        """获取所有配置"""
        return self._config
