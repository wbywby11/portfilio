"""
定时任务管理模块
"""
import asyncio
import logging
from datetime import datetime, time, timedelta
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

from app.services.portfolio_service import PortfolioService

logger = logging.getLogger(__name__)

class TaskStatus(BaseModel):
    name: str
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    status: str = "PENDING"
    error: Optional[str] = None

class SchedulerService:
    _instance = None
    _tasks: Dict[str, TaskStatus] = {}
    _running = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SchedulerService, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, 'initialized'):
            self.initialized = True
            self.portfolio_service = PortfolioService()
            self._tasks = {
                "daily_portfolio_maintenance": TaskStatus(name="模拟组合每日维护"),
                "daily_monitor": TaskStatus(name="每日组合监控")
            }

    async def start(self):
        """启动调度器"""
        if self._running:
            return
        self._running = True
        asyncio.create_task(self._main_loop())
        logger.info("Scheduler service started")

    async def stop(self):
        """停止调度器"""
        self._running = False
        logger.info("Scheduler service stopped")

    def get_tasks_status(self) -> List[TaskStatus]:
        return list(self._tasks.values())

    async def _main_loop(self):
        while self._running:
            now = datetime.now()
            
            # 1. 模拟组合每日维护 (假设在凌晨 1:00 执行)
            task_name = "daily_portfolio_maintenance"
            task = self._tasks[task_name]
            
            maintenance_time = time(7, 0) # 01:00 AM
            target_dt = datetime.combine(now.date(), maintenance_time)
            
            if now >= target_dt:
                if task.last_run is None or task.last_run.date() < now.date():
                    # 今天还没跑，立即执行
                    await self._run_task(task_name, self.portfolio_service.run_daily_batch_maintenance)
                
                # 设置下一次执行时间为明天
                task.next_run = target_dt + timedelta(days=1)
            else:
                task.next_run = target_dt

            # 2. 每日组合监控 (在 07:30 执行，行情数据更新后)
            monitor_task_name = "daily_monitor"
            monitor_task = self._tasks[monitor_task_name]
            
            monitor_time = time(7, 30)  # 07:30 AM
            monitor_target_dt = datetime.combine(now.date(), monitor_time)
            
            if now >= monitor_target_dt:
                if monitor_task.last_run is None or monitor_task.last_run.date() < now.date():
                    # 今天还没跑，立即执行
                    await self._run_task(monitor_task_name, self._run_daily_monitor)
                
                # 设置下一次执行时间为明天
                monitor_task.next_run = monitor_target_dt + timedelta(days=1)
            else:
                monitor_task.next_run = monitor_target_dt

            await asyncio.sleep(60) # 每分钟检查一次

    async def _run_task(self, task_name: str, func):
        task = self._tasks[task_name]
        task.status = "RUNNING"
        try:
            logger.info(f"Starting task: {task_name}")
            await func()
            task.last_run = datetime.now()
            task.status = "SUCCESS"
            task.error = None
            logger.info(f"Task {task_name} completed successfully")
        except Exception as e:
            task.status = "FAILED"
            task.error = str(e)
            logger.error(f"Task {task_name} failed: {e}")

    async def _run_daily_monitor(self):
        """每日自动运行监控，在行情数据更新后触发"""
        from app.services.monitor_service import MonitorService
        monitor_service = MonitorService()
        await monitor_service.run_daily(monitor_id="default")

scheduler_service = SchedulerService()
