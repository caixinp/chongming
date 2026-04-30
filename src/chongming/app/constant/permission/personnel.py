class PersonnelConstant:
    """人员管理权限常量"""

    PERSONNEL_CREATE = "personnel:create"  # 创建人员
    PERSONNEL_READ = "personnel:read"  # 读取人员
    PERSONNEL_UPDATE = "personnel:update"  # 更新人员
    PERSONNEL_DELETE = "personnel:delete"  # 删除人员

    permission_description_dict = {
        PERSONNEL_CREATE: "创建人员",
        PERSONNEL_READ: "读取人员",
        PERSONNEL_UPDATE: "更新人员",
        PERSONNEL_DELETE: "删除人员",
    }
