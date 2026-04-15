from typing import Callable, Optional

from ..core.scheduler import TaskService
from .execute_background import dev_init_admin


async def init_tasks_callback(task_service: TaskService):
    await task_service.add_date_job(
        dev_init_admin,
        run_date=None,
        args=[],
        job_id="task_name",
    )
