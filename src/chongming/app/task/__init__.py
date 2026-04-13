from typing import Callable, Optional

from ..core.scheduler import TaskService
from .execute_background import execute_background_task


task_dict = {"execute_background_task": execute_background_task}


def get_task(task_name: str) -> Optional[Callable]:
    return task_dict.get(task_name, None)


async def init_tasks_callback(task_service: TaskService):
    await task_service.add_interval_job(
        execute_background_task,
        seconds=1,
        args=["task_name"],
        job_id="task_name",
    )
