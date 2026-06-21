"""最小可用的进程内任务执行器（P0-2 过渡方案）。"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Dict, Optional

from app.utils.logger import logger

TaskFactory = Callable[[], Awaitable[None]]


class InMemoryTaskRunner:
    def __init__(self) -> None:
        self.enabled = True
        self._tasks: Dict[str, asyncio.Task] = {}

    def submit(self, task_id: str, factory: TaskFactory) -> None:
        if not self.enabled:
            logger.info(f"任务执行器已禁用，跳过提交任务: {task_id}")
            return

        async def _runner() -> None:
            try:
                await factory()
            except Exception as exc:  # pragma: no cover
                logger.error(f"后台任务执行失败 task_id={task_id}: {exc}")
                raise
            finally:
                self._tasks.pop(task_id, None)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(f"无运行中的事件循环，无法提交后台任务: {task_id}")
            return

        self._tasks[task_id] = loop.create_task(_runner())
        logger.info(f"后台任务已提交: {task_id}")

    async def shutdown(self) -> None:
        if not self._tasks:
            return
        tasks = list(self._tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()


task_runner = InMemoryTaskRunner()
