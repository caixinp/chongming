class SystemConfigConstant:
    """系统配置、审计日志与备份恢复权限常量"""

    CONFIG_READ = "system_config:read"  # 读取系统配置
    CONFIG_UPDATE = "system_config:update"  # 更新系统配置
    AUDIT_LOG_READ = "audit_log:read"  # 读取审计日志
    BACKUP_CREATE = "backup:create"  # 创建备份
    BACKUP_RESTORE = "backup:restore"  # 恢复备份

    permission_description_dict = {
        CONFIG_READ: "读取系统配置",
        CONFIG_UPDATE: "更新系统配置",
        AUDIT_LOG_READ: "读取审计日志",
        BACKUP_CREATE: "创建备份",
        BACKUP_RESTORE: "恢复备份",
    }
