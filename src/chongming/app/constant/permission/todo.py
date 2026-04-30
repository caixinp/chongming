class TodoConstant:
    """Todo任务管理权限常量"""

    TODO_CREATE = "todo:create"  # 创建待办事项
    TODO_READ = "todo:read"  # 读取待办事项
    TODO_UPDATE = "todo:update"  # 更新待办事项
    TODO_DELETE = "todo:delete"  # 删除待办事项

    permission_description_dict = {
        TODO_CREATE: "创建待办事项",
        TODO_READ: "读取待办事项",
        TODO_UPDATE: "更新待办事项",
        TODO_DELETE: "删除待办事项",
    }
