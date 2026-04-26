from ..core.config import get_config
from .dev_init_db import init_db

from plugins.scheduler.scheduler import TaskService


config = get_config()


async def init_tasks_callback(task_service: TaskService):
    """
    初始化任务回调函数

    在开发环境下自动添加数据库初始化定时任务。

    Args:
        task_service (TaskService): 任务服务实例，用于管理和调度定时任务

    Returns:
        None: 此函数不返回任何值

    Note:
        仅在开发环境（env == "development"）下执行数据库初始化任务
    """
    if config["default"]["env"] == "development":

        await task_service.add_date_job(
            init_db,
            run_date=None,
            args=[],
            job_id="task_name",
        )
