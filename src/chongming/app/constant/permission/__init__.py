from .personnel import PersonnelConstant
from .role import RoleConstant
from .permission_mgt import PermissionMgtConstant
from .system_config import SystemConfigConstant
from .todo import TodoConstant


class PermissionConstant:
    """
    权限常量类 - 按业务模块分组管理所有系统权限

    该类定义了系统中各个业务模块的权限标识符，采用分层结构组织：
    - 每个业务域作为一个内部类（Personnel, Role, Permission, SystemConfig, Todo）
    - 每个权限使用 "资源:操作" 格式定义

    使用示例:
        >>> PermissionConstant.Personnel.PERSONNEL_CREATE
        'personnel:create'
        >>> PermissionConstant.get_all()
        ['personnel:create', 'personnel:read', ...]
    """

    Personnel = PersonnelConstant
    PREFIX_PERSONNEL = "personnel"
    Role = RoleConstant
    PREFIX_ROLE = "role"
    Permission = PermissionMgtConstant
    PREFIX_PERMISSION = "permission"
    SystemConfig = SystemConfigConstant
    PREFIX_SYSTEM_CONFIG = "system_config"
    PREFIX_AUDIT_LOG = "audit_log"
    PREFIX_BACKUP = "backup"
    Todo = TodoConstant
    PREFIX_TODO = "todo"

    @classmethod
    def get_all(cls):
        """
        获取系统中定义的所有权限字符串列表

        通过反射机制自动收集所有内部类中定义的权限常量。

        Returns:
            list[str]: 所有权限字符串的列表
        """
        perms = []
        for attr_name in dir(cls):
            attr = getattr(cls, attr_name)
            if attr_name.startswith("_") or not hasattr(attr, "__dict__"):
                continue
            # 遍历内部类的属性
            for sub_attr in dir(attr):
                if sub_attr.startswith("_"):
                    continue
                val = getattr(attr, sub_attr)
                if isinstance(val, str) and ":" in val:
                    perms.append(val)
        return perms

    @classmethod
    def get_description_map(cls) -> dict:
        """
        获取系统中所有权限的描述映射

        Returns:
            dict[str, str]: 权限字符串到描述的映射字典
        """
        description_map = {}
        for attr_name in dir(cls):
            attr = getattr(cls, attr_name)
            if attr_name.startswith("_") or not hasattr(attr, "__dict__"):
                continue
            description_dict = getattr(attr, "permission_description_dict", None)
            if isinstance(description_dict, dict):
                description_map.update(description_dict)
        return description_map
