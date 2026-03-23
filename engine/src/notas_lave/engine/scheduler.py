"""v2 Scheduler — periodic task runner.

Simple asyncio-based scheduler for recurring tasks.
Each task runs at a specified interval. Errors are logged
but don't crash other tasks.

Usage:
    sched = Scheduler()
    sched.add_task("health_check", check_health, interval_seconds=60)
    sched.add_task("balance_sync", sync_balance, interval_seconds=300)
    await sched.start()
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class _Task:
    name: str
    callback: Callable
    interval_seconds: float
    run_count: int = 0


class Scheduler:
    """Runs registered tasks at specified intervals."""

    def __init__(self) -> None:
        self._tasks: list[_Task] = []
        self._running = False
        self._async_tasks: list[asyncio.Task] = []

    @property
    def task_count(self) -> int:
        return len(self._tasks)

    def add_task(
        self, name: str, callback: Callable, interval_seconds: float,
    ) -> None:
        self._tasks.append(_Task(
            name=name, callback=callback, interval_seconds=interval_seconds,
        ))

    async def start(self) -> None:
        if self._running:
            return
        self._running = True

        for task in self._tasks:
            at = asyncio.create_task(self._run_loop(task))
            self._async_tasks.append(at)

    def stop(self) -> None:
        self._running = False
        for at in self._async_tasks:
            at.cancel()
        self._async_tasks.clear()

    async def _run_loop(self, task: _Task) -> None:
        while self._running:
            try:
                result = task.callback()
                if asyncio.iscoroutine(result):
                    await result
                task.run_count += 1
            except Exception as e:
                logger.error("Scheduler task '%s' failed: %s", task.name, e)
            await asyncio.sleep(task.interval_seconds)

    def get_status(self) -> list[dict]:
        return [
            {
                "name": t.name,
                "interval_seconds": t.interval_seconds,
                "run_count": t.run_count,
            }
            for t in self._tasks
        ]
