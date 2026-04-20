from ..core.scheduler import logger
from ..core.scheduler import get_task_service_instance
from ..core.constant import PermissionConstant
from ..service.user import UserService
from ..service.permission import PermissionService


async def dev_init_admin(session):
    admin_user = await UserService.get_user_by_email("admin", session)
    if admin_user:  # type: ignore
        logger.info("管理员用户已存在")  # type: ignore
        return
    await UserService.create_user(session, "admin", "admin", is_superuser=True)  # type: ignore


async def init_permission(session):
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
    task_service = get_task_service_instance()
    if task_service.async_session_maker is None:
        return
    async with task_service.async_session_maker() as session:
        await dev_init_admin(session)
        await init_permission(session)
