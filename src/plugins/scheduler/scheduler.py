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
    """
    获取调度器分布式锁，确保只有一个进程实例运行调度器

    通过在临时目录创建锁文件并使用文件系统锁机制，防止多个进程同时启动调度器。
    支持 Windows 和 Unix/Linux 系统的不同锁实现。

    Returns:
        tuple: 包含两个元素的元组
            - lock_file (file object or None): 锁文件对象，如果获取锁失败则为 None
            - bool: 是否成功获取锁，成功为 True，失败为 False
    """
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
    """
    任务调度服务类

    基于 APScheduler 实现的异步任务调度服务，支持多种触发器类型（间隔、Cron、一次性）。
    使用 SQLite 数据库持久化存储任务信息，确保服务重启后任务不丢失。
    通过文件锁机制保证多进程环境下只有一个实例执行调度任务。
    """

    def __init__(self, config, logger, async_session_maker=None):
        """
        初始化任务调度服务

        Args:
            config (dict): 配置字典，包含调度器相关配置项
                - scheduler.job_store_path (str): 任务存储数据库路径，默认为 "scheduler_jobs.db"
            logger (logging.Logger): 日志记录器实例，用于记录调度器运行日志
            async_session_maker (callable, optional): 异步会话工厂函数，用于数据库操作，默认为 None

        Attributes:
            async_session_maker: 异步会话工厂函数
            job_store_db_path: 任务存储数据库文件路径
            scheduler: AsyncIOScheduler 调度器实例
            _started (bool): 调度器是否已启动的标志
            lock_file: 锁文件对象
            is_scheduler_worker (bool): 当前进程是否为调度器工作进程
            logger: 日志记录器实例
        """
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
        """
        启动任务调度器

        仅在当前进程成功获取调度器锁时启动调度器，避免多进程重复启动。
        启动后可选择执行初始化任务回调函数。

        Args:
            init_tasks_callback (callable, optional): 初始化任务回调函数，接收 TaskService 实例作为参数。
                用于在调度器启动后注册初始任务。默认为 None。

        Note:
            - 如果调度器已经启动，不会重复启动
            - 只有成功获取锁的进程才会启动调度器
        """
        if self.is_scheduler_worker:
            if not self._started:
                self.scheduler.start()
                self._started = True
                self.logger.info("任务调度器已启动")
            if init_tasks_callback:
                await init_tasks_callback(self)

    async def shutdown(self, wait: bool = True):
        """
        关闭任务调度器

        优雅地关闭调度器，包括暂停所有运行中的任务、关闭调度器、释放文件锁。

        Args:
            wait (bool): 是否等待正在执行的任务完成后再关闭。
                True 表示等待任务完成，False 表示立即关闭。默认为 True。

        Note:
            - 先暂停所有任务，再关闭调度器
            - 释放文件锁以允许其他进程获取锁
            - 使用 suppress 捕获所有异常，确保关闭过程不会抛出异常
        """
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
        """
        添加间隔执行任务

        创建按照固定时间间隔重复执行的任务。

        Args:
            func (callable): 要执行的任务函数
            seconds (int): 间隔秒数，默认为 0
            minutes (int): 间隔分钟数，默认为 0
            hours (int): 间隔小时数，默认为 0
            days (int): 间隔天数，默认为 0
            job_id (str, optional): 任务唯一标识符，如果未提供则自动生成
            args (list, optional): 传递给任务函数的位置参数列表，默认为空列表
            kwargs (dict, optional): 传递给任务函数的关键字参数字典，默认为空字典
            replace_existing (bool): 如果存在相同 ID 的任务，是否替换它。默认为 True

        Returns:
            Job: 创建的任务对象

        Example:
            >>> await service.add_interval_job(my_func, minutes=5, job_id="cleanup_task")
        """
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
        """
        添加 Cron 表达式任务

        创建按照 Cron 表达式规则执行的任务，支持精确的时间调度。

        Args:
            func (callable): 要执行的任务函数
            job_id (str, optional): 任务唯一标识符，如果未提供则自动生成
            year (int, optional): 年份，支持通配符和范围
            month (int, optional): 月份 (1-12)
            day (int, optional): 日期 (1-31)
            week (int, optional): 周数 (1-53)
            day_of_week (int, optional): 星期几 (0-6, 0 表示周一)
            hour (int, optional): 小时 (0-23)
            minute (int, optional): 分钟 (0-59)
            second (int, optional): 秒 (0-59)
            args (list, optional): 传递给任务函数的位置参数列表，默认为空列表
            kwargs (dict, optional): 传递给任务函数的关键字参数字典，默认为空字典
            replace_existing (bool): 如果存在相同 ID 的任务，是否替换它。默认为 True

        Returns:
            Job: 创建的任务对象

        Example:
            >>> # 每天凌晨 2 点执行
            >>> await service.add_cron_job(my_func, hour=2, minute=0, job_id="daily_task")
        """
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
        """
        添加一次性任务

        创建在指定时间点执行一次的任务，执行后自动移除。

        Args:
            func (callable): 要执行的任务函数
            run_date (datetime, optional): 任务执行的具体时间，如果未提供则立即执行
            job_id (str, optional): 任务唯一标识符，如果未提供则自动生成
            args (list, optional): 传递给任务函数的位置参数列表，默认为空列表
            kwargs (dict, optional): 传递给任务函数的关键字参数字典，默认为空字典
            replace_existing (bool): 如果存在相同 ID 的任务，是否替换它。默认为 True

        Returns:
            Job: 创建的任务对象

        Example:
            >>> from datetime import datetime
            >>> run_time = datetime(2024, 12, 25, 10, 0, 0)
            >>> await service.add_date_job(my_func, run_date=run_time, job_id="christmas_task")
        """
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
        """
        删除任务

        从调度器中移除指定任务，任务将不再执行。

        Args:
            job_id (str): 要删除的任务的唯一标识符

        Returns:
            bool: 删除是否成功，成功返回 True，失败返回 False

        Note:
            - 如果任务不存在或删除过程中发生异常，返回 False
            - 会记录删除操作的日志
        """
        try:
            self.scheduler.remove_job(job_id)
            self.logger.info(f"删除任务: {job_id}")
            return True
        except Exception as e:
            self.logger.error(f"删除任务失败 {job_id}: {e}")
            return False

    async def pause_job(self, job_id: str) -> bool:
        """
        暂停任务

        暂停指定任务的执行，任务保留在调度器中但不会触发。

        Args:
            job_id (str): 要暂停的任务的唯一标识符

        Returns:
            bool: 暂停是否成功，成功返回 True，失败返回 False

        Note:
            - 暂停的任务可以通过 resume_job 恢复
            - 如果任务不存在或暂停过程中发生异常，返回 False
        """
        try:
            self.scheduler.pause_job(job_id)
            self.logger.info(f"暂停任务: {job_id}")
            return True
        except Exception as e:
            self.logger.error(f"暂停任务失败 {job_id}: {e}")
            return False

    async def resume_job(self, job_id: str) -> bool:
        """
        恢复任务

        恢复之前被暂停的任务，使其继续按照原定计划执行。

        Args:
            job_id (str): 要恢复的任务的唯一标识符

        Returns:
            bool: 恢复是否成功，成功返回 True，失败返回 False

        Note:
            - 只能恢复已被暂停的任务
            - 如果任务不存在或恢复过程中发生异常，返回 False
        """
        try:
            self.scheduler.resume_job(job_id)
            self.logger.info(f"恢复任务: {job_id}")
            return True
        except Exception as e:
            self.logger.error(f"恢复任务失败 {job_id}: {e}")
            return False

    async def get_job(self, job_id: str) -> Optional[Dict]:
        """
        获取单个任务信息

        查询指定任务的详细信息，包括下次执行时间、触发器等。

        Args:
            job_id (str): 要查询的任务的唯一标识符

        Returns:
            dict or None: 任务信息字典，如果任务不存在则返回 None。
                字典包含以下字段：
                - id (str): 任务 ID
                - name (str): 任务名称
                - next_run_time (str or None): 下次执行时间的 ISO 格式字符串
                - trigger (str): 触发器描述
                - pending (bool): 任务是否处于待处理状态
                - args (list): 任务函数的位置参数
                - kwargs (dict): 任务函数的关键字参数
        """
        job = self.scheduler.get_job(job_id)
        if job:
            return self._job_to_dict(job)
        return None

    async def get_jobs(self) -> List[Dict]:
        """
        获取所有任务信息

        查询调度器中所有任务的详细信息列表。

        Returns:
            list[dict]: 任务信息字典列表，每个字典的结构与 get_job 返回的相同。
                如果没有任务，返回空列表。
        """
        jobs = self.scheduler.get_jobs()
        return [self._job_to_dict(job) for job in jobs]

    async def reschedule_job(
        self, job_id: str, trigger_type: str, **trigger_args
    ) -> Optional[Job]:
        """
        重新调度任务（修改触发时间）

        修改现有任务的触发器配置，改变任务的执行时间规则。

        Args:
            job_id (str): 要重新调度的任务的唯一标识符
            trigger_type (str): 触发器类型，可选值：
                - "interval": 间隔触发器
                - "cron": Cron 表达式触发器
                - "date": 一次性触发器
            **trigger_args: 触发器参数，根据 trigger_type 不同而不同：
                - interval: seconds, minutes, hours, days
                - cron: year, month, day, week, day_of_week, hour, minute, second
                - date: run_date

        Returns:
            Job or None: 重新调度后的任务对象，如果任务不存在或重新调度失败则返回 None

        Raises:
            ValueError: 当传入不支持的 trigger_type 时抛出

        Example:
            >>> # 将任务改为每 10 分钟执行一次
            >>> await service.reschedule_job("task_id", "interval", minutes=10)
        """
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
        """
        将 Job 对象转换为字典

        内部辅助方法，将 APScheduler 的 Job 对象序列化为字典格式，
        便于 API 返回和数据传输。

        Args:
            job (Job): APScheduler 的 Job 对象

        Returns:
            dict: 包含任务信息的字典，字段包括：
                - id (str): 任务 ID
                - name (str): 任务名称
                - next_run_time (str or None): 下次执行时间的 ISO 8601 格式字符串
                - trigger (str): 触发器的字符串描述
                - pending (bool): 任务是否处于待处理状态
                - args (list): 任务函数的位置参数列表
                - kwargs (dict): 任务函数的关键字参数字典
        """
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
    """
    获取任务调度服务单例实例

    使用全局变量实现单例模式，确保整个应用中只有一个 TaskService 实例。
    首次调用时创建实例，后续调用直接返回已创建的实例。

    Args:
        config (dict, optional): 配置字典，仅在首次创建实例时需要
        logger (logging.Logger, optional): 日志记录器，仅在首次创建实例时需要
        async_session_maker (callable, optional): 异步会话工厂函数，仅在首次创建实例时需要

    Returns:
        TaskService: 任务调度服务单例实例

    Raises:
        ValueError: 如果首次调用时未提供 config 或 logger 参数

    Note:
        - 这是一个单例模式实现，确保全局只有一个调度器实例
        - 首次调用必须提供 config 和 logger 参数
        - 后续调用可以不提供参数，直接返回已创建的实例
    """
    global _task_service
    if _task_service is None:
        if config is None or logger is None:
            raise ValueError("请传入 config 和 logger")
        _task_service = TaskService(config, logger, async_session_maker)
    return _task_service


async def get_task_service(request: Request) -> AsyncGenerator:
    """
    FastAPI 依赖注入函数，获取任务调度服务实例

    用于 FastAPI 路由函数的依赖注入，从应用状态中获取已初始化的任务调度服务。

    Args:
        request (Request): FastAPI 请求对象，从中获取应用实例

    Returns:
        TaskService: 从 request.app.state.task_service 获取的任务调度服务实例

    Note:
        - 此函数应在应用启动时通过 startup 事件初始化 task_service
        - 适用于 FastAPI 的 Depends 依赖注入机制
    """
    return request.app.state.task_service
