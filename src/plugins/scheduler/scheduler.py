"""
APScheduler 集成模块
提供持久化任务调度服务
"""

import os
import sys
import tempfile
from contextlib import suppress
from typing import Dict, List, Optional, Callable, AsyncGenerator
from datetime import datetime

from fastapi import Request
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.job import Job
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger


def acquire_scheduler_lock():
    lock_path = os.path.join(tempfile.gettempdir(), "chongming_scheduler.lock")
    lock_file = open(lock_path, "w")
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_NB | fcntl.LOCK_EX)
        return lock_file, True
    except (IOError, OSError):
        lock_file.close()
        return None, False


class TaskService:
    """任务调度服务"""

    def __init__(self, config, logger, async_session_maker=None):
        self.async_session_maker = async_session_maker
        # 使用独立的 SQLite 数据库存储任务（与业务数据库分开）
        self.job_store_db_path = config.get("scheduler", {}).get(
            "job_store_path", "scheduler_jobs.db"
        )
        job_store_url = f"sqlite:///{self.job_store_db_path}"

        # 配置 job stores 和 executors
        jobstores = {"default": SQLAlchemyJobStore(url=job_store_url)}
        executors = {"default": AsyncIOExecutor()}
        job_defaults = {
            "coalesce": True,  # 合并错过的任务
            "max_instances": 3,  # 最大并发实例数
            "misfire_grace_time": 30,  # 错过任务的宽限时间（秒）
        }

        self.scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
            timezone="Asia/Shanghai",
        )
        self._started = False
        self.lock_file, self.is_scheduler_worker = acquire_scheduler_lock()
        self.logger = logger

    async def start(self, init_tasks_callback: Optional[Callable] = None):
        """启动调度器"""
        if self.is_scheduler_worker:
            if not self._started:
                self.scheduler.start()
                self._started = True
                self.logger.info("任务调度器已启动")
            if init_tasks_callback:
                await init_tasks_callback(self)

    async def shutdown(self, wait: bool = True):
        """关闭调度器"""
        if self.lock_file:
            with suppress(Exception):
                for job in await self.get_jobs():
                    await self.pause_job(job.get("id", ""))

                if self._started:
                    self.scheduler.shutdown(wait=wait)
                    self._started = False
                    self.logger.info("任务调度器已关闭")
                if sys.platform == "win32":
                    import msvcrt

                    msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
            self.lock_file.close()

    async def add_interval_job(
        self,
        func: Callable,
        seconds: int = 0,
        minutes: int = 0,
        hours: int = 0,
        days: int = 0,
        job_id: Optional[str] = None,
        args: Optional[List] = None,
        kwargs: Optional[Dict] = None,
        replace_existing: bool = True,
    ) -> Job:
        """添加间隔执行任务"""
        trigger = IntervalTrigger(
            seconds=seconds, minutes=minutes, hours=hours, days=days
        )
        job = self.scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            args=args or [],
            kwargs=kwargs or {},
            replace_existing=replace_existing,
        )
        self.logger.info(f"添加间隔任务: {job.id}")
        return job

    async def add_cron_job(
        self,
        func: Callable,
        job_id: Optional[str] = None,
        year: Optional[int] = None,
        month: Optional[int] = None,
        day: Optional[int] = None,
        week: Optional[int] = None,
        day_of_week: Optional[int] = None,
        hour: Optional[int] = None,
        minute: Optional[int] = None,
        second: Optional[int] = None,
        args: Optional[List] = None,
        kwargs: Optional[Dict] = None,
        replace_existing: bool = True,
    ) -> Job:
        """添加 cron 表达式任务"""
        trigger = CronTrigger(
            year=year,
            month=month,
            day=day,
            week=week,
            day_of_week=day_of_week,
            hour=hour,
            minute=minute,
            second=second,
        )
        job = self.scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            args=args or [],
            kwargs=kwargs or {},
            replace_existing=replace_existing,
        )
        self.logger.info(f"添加 cron 任务: {job.id}")
        return job

    async def add_date_job(
        self,
        func: Callable,
        run_date: Optional[datetime] = None,
        job_id: Optional[str] = None,
        args: Optional[List] = None,
        kwargs: Optional[Dict] = None,
        replace_existing: bool = True,
    ) -> Job:
        """添加一次性任务"""
        trigger = DateTrigger(run_date=run_date)
        job = self.scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            args=args or [],
            kwargs=kwargs or {},
            replace_existing=replace_existing,
        )
        self.logger.info(f"添加一次性任务: {job.id}")
        return job

    async def remove_job(self, job_id: str) -> bool:
        """删除任务"""
        try:
            self.scheduler.remove_job(job_id)
            self.logger.info(f"删除任务: {job_id}")
            return True
        except Exception as e:
            self.logger.error(f"删除任务失败 {job_id}: {e}")
            return False

    async def pause_job(self, job_id: str) -> bool:
        """暂停任务"""
        try:
            self.scheduler.pause_job(job_id)
            self.logger.info(f"暂停任务: {job_id}")
            return True
        except Exception as e:
            self.logger.error(f"暂停任务失败 {job_id}: {e}")
            return False

    async def resume_job(self, job_id: str) -> bool:
        """恢复任务"""
        try:
            self.scheduler.resume_job(job_id)
            self.logger.info(f"恢复任务: {job_id}")
            return True
        except Exception as e:
            self.logger.error(f"恢复任务失败 {job_id}: {e}")
            return False

    async def get_job(self, job_id: str) -> Optional[Dict]:
        """获取任务信息"""
        job = self.scheduler.get_job(job_id)
        if job:
            return self._job_to_dict(job)
        return None

    async def get_jobs(self) -> List[Dict]:
        """获取所有任务"""
        jobs = self.scheduler.get_jobs()
        return [self._job_to_dict(job) for job in jobs]

    async def reschedule_job(
        self, job_id: str, trigger_type: str, **trigger_args
    ) -> Optional[Job]:
        """重新调度任务（修改触发时间）"""
        try:
            job = self.scheduler.get_job(job_id)
            if not job:
                return None

            if trigger_type == "interval":
                trigger = IntervalTrigger(**trigger_args)
            elif trigger_type == "cron":
                trigger = CronTrigger(**trigger_args)
            elif trigger_type == "date":
                trigger = DateTrigger(**trigger_args)
            else:
                raise ValueError(f"不支持的 trigger 类型: {trigger_type}")

            job.reschedule(trigger=trigger)
            self.logger.info(f"重新调度任务: {job_id}")
            return job
        except Exception as e:
            self.logger.error(f"重新调度任务失败 {job_id}: {e}")
            return None

    def _job_to_dict(self, job: Job) -> Dict:
        """将 Job 对象转换为字典"""
        return {
            "id": job.id,
            "name": job.name,
            "next_run_time": (
                job.next_run_time.isoformat() if job.next_run_time else None
            ),
            "trigger": str(job.trigger),
            "pending": job.pending,
            "args": job.args,
            "kwargs": job.kwargs,
        }


_task_service: Optional[TaskService] = None


def get_task_service_instance(config=None, logger=None, async_session_maker=None):
    global _task_service
    if _task_service is None:
        if config is None or logger is None:
            raise ValueError("请传入 config 和 logger")
        _task_service = TaskService(config, logger, async_session_maker)
    return _task_service


async def get_task_service(request: Request) -> AsyncGenerator:
    return request.app.state.task_service
