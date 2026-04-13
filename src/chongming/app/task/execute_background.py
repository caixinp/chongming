from ..core.scheduler import logger


async def execute_background_task(task_name: str):
    from datetime import datetime

    """模拟后台任务执行"""
    logger.info(f"Executing task: {task_name} at {datetime.utcnow()}")
