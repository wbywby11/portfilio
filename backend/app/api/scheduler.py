"""
定时任务管理接口
"""
from typing import List
from fastapi import APIRouter, Depends
from app.schemas.response import Response
from app.services.scheduler_service import scheduler_service, TaskStatus

router = APIRouter()

@router.get("/status", response_model=Response[List[TaskStatus]], summary="获取定时任务状态")
async def get_scheduler_status():
    """查看系统中所有定时任务的运行状态、上次运行时间和下次运行时间"""
    return Response.success(data=scheduler_service.get_tasks_status())

@router.post("/run-now/{task_name}", response_model=Response[bool], summary="手动触发任务")
async def run_task_now(task_name: str):
    """立即手动执行指定的定时任务"""
    if task_name == "daily_portfolio_maintenance":
        # 在后台异步执行，不阻塞 API
        import asyncio
        from app.services.portfolio_service import PortfolioService
        service = PortfolioService()
        asyncio.create_task(scheduler_service._run_task(task_name, service.run_daily_batch_maintenance))
        return Response.success(data=True, message=f"任务 {task_name} 已在后台启动")

    if task_name == "daily_live_monitoring":
        import asyncio
        asyncio.create_task(scheduler_service._run_task(task_name, scheduler_service._run_live_monitoring_task))
        return Response.success(data=True, message=f"任务 {task_name} 已在后台启动")
    
    return Response.error(message=f"未找到任务: {task_name}")
