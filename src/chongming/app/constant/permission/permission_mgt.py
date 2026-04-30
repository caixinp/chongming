class PermissionMgtConstant:
    """权限管理权限常量"""

    PERMISSION_CREATE = "permission:create"  # 创建权限
    PERMISSION_UPDATE = "permission:update"  # 修改权限
    PERMISSION_DELETE = "permission:delete"  # 删除权限
    PERMISSION_READ = "permission:read"  # 读取权限
    PERMISSION_BIND = "permission:bind"  # 分配权限
    PERMISSION_UNBIND = "permission:unbind"  # 解绑权限

    permission_description_dict = {
        PERMISSION_CREATE: "创建权限",
        PERMISSION_UPDATE: "修改权限",
        PERMISSION_DELETE: "删除权限",
        PERMISSION_READ: "读取权限",
        PERMISSION_BIND: "分配权限",
        PERMISSION_UNBIND: "解绑权限",
    }
