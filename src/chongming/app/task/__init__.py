from ..core.scheduler import TaskService
from ..core.config import get_config
from .dev_init_db import init_db


config = get_config()


async def init_tasks_callback(task_service: TaskService):
    if config["default"]["env"] == "development":

        await task_service.add_date_job(
            init_db,
            run_date=None,
            args=[],
            job_id="task_name",
        )
