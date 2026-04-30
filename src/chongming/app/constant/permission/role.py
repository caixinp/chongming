class RoleConstant:
    """角色管理权限常量"""

    ROLE_CREATE = "role:create"  # 创建角色
    ROLE_READ = "role:read"  # 读取角色
    ROLE_UPDATE = "role:update"  # 更新角色
    ROLE_DELETE = "role:delete"  # 删除角色
    ROLE_BIND = "role:assign"  # 分配角色
    ROLE_UNBIND = "role:unbind"  # 解绑角色

    permission_description_dict = {
        ROLE_CREATE: "创建角色",
        ROLE_READ: "读取角色",
        ROLE_UPDATE: "更新角色",
        ROLE_DELETE: "删除角色",
        ROLE_BIND: "分配角色",
        ROLE_UNBIND: "解绑角色",
    }
