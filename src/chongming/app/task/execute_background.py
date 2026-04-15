from ..core.scheduler import logger
from ..service.user import UserService
from ..core.scheduler import get_task_service_instance


async def dev_init_admin():
    task_service = get_task_service_instance()
    if task_service.async_session_maker is None:
        return
    async with task_service.async_session_maker() as session:
        admin_user = await UserService.get_user_by_email("admin", session)
        if admin_user:  # type: ignore
            logger.info("管理员用户已存在")  # type: ignore
            return
        await UserService.create_user(session, "admin", "admin", is_superuser=True)  # type: ignore
