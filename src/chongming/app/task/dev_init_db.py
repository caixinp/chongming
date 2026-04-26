from ..core.logger import get_logger
from ..core.constant import PermissionConstant
from ..service.user import UserService
from ..service.permission import PermissionService

from plugins.scheduler.scheduler import get_task_service_instance


logger = get_logger("scheduler")


async def dev_init_admin(session):
    """
    初始化系统管理员用户

    检查是否存在邮箱为"admin"的管理员用户，如果不存在则创建一个新的超级管理员账户。
    该函数用于系统首次部署时的管理员账户初始化。

    Args:
        session: 数据库会话对象，用于执行数据库操作

    Returns:
        None

    Note:
        - 默认管理员邮箱和密码均为"admin"
        - 如果管理员已存在，则跳过创建并记录日志
        - 新创建的用户具有超级管理员权限（is_superuser=True）
    """
    admin_user = await UserService.get_user_by_email("admin", session)
    if admin_user:  # type: ignore
        logger.info("管理员用户已存在")  # type: ignore
        return
    await UserService.create_user(session, "admin", "admin", is_superuser=True)  # type: ignore


async def init_permission(session):
    """
    初始化系统权限数据

    遍历所有预定义的权限常量，检查数据库中是否已存在对应权限记录。
    对于不存在的权限，创建新的权限记录并关联对应的资源和操作类型。

    Args:
        session: 数据库会话对象，用于执行数据库操作

    Returns:
        None

    Note:
        - 权限格式为"resource:action"，例如"user:create"
        - 使用冒号分隔资源和操作，如果缺少操作部分则默认为空字符串
        - 已存在的权限会被跳过，避免重复创建
        - 每个新创建的权限都会记录到日志中
    """
    for permission in PermissionConstant.get_all():
        parts = permission.split(":", 1)
        resource = parts[0]
        action = parts[1] if len(parts) > 1 else ""

        existing_permission = await PermissionService.get_permission_by_name(
            session, permission
        )
        if existing_permission:
            logger.debug(f"权限已存在: {permission}")
            continue

        await PermissionService.create_permission(session, permission, resource, action)
        logger.info(f"创建权限: {permission}")


async def init_db():
    """
    执行数据库初始化流程

    协调执行所有数据库初始化任务，包括管理员账户创建和权限数据初始化。
    该函数是系统启动时数据库初始化的入口点。

    Returns:
        None

    Note:
        - 通过任务服务获取异步会话工厂
        - 如果会话工厂未初始化，则直接返回不执行任何操作
        - 按顺序执行：先初始化管理员，再初始化权限
        - 使用异步上下文管理器确保会话正确关闭
    """
    task_service = get_task_service_instance()
    if task_service.async_session_maker is None:
        return
    async with task_service.async_session_maker() as session:
        await dev_init_admin(session)
        await init_permission(session)
