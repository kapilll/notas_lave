"""Tests for v2 Scheduler — periodic task runner.

The scheduler runs callbacks at specified intervals.
Decoupled from business logic — just timing and execution.
"""

import asyncio

import pytest


@pytest.mark.asyncio
async def test_scheduler_creation():
    from notas_lave.engine.scheduler import Scheduler

    sched = Scheduler()
    assert sched is not None
    assert sched.task_count == 0


@pytest.mark.asyncio
async def test_scheduler_add_task():
    from notas_lave.engine.scheduler import Scheduler

    sched = Scheduler()
    sched.add_task("test_task", lambda: None, interval_seconds=60)
    assert sched.task_count == 1


@pytest.mark.asyncio
async def test_scheduler_runs_task():
    from notas_lave.engine.scheduler import Scheduler

    sched = Scheduler()
    call_count = 0

    async def task():
        nonlocal call_count
        call_count += 1

    sched.add_task("counter", task, interval_seconds=0.05)
    await sched.start()
    await asyncio.sleep(0.15)
    sched.stop()

    assert call_count >= 2


@pytest.mark.asyncio
async def test_scheduler_multiple_tasks():
    from notas_lave.engine.scheduler import Scheduler

    sched = Scheduler()
    results = {"a": 0, "b": 0}

    async def task_a():
        results["a"] += 1

    async def task_b():
        results["b"] += 1

    sched.add_task("a", task_a, interval_seconds=0.05)
    sched.add_task("b", task_b, interval_seconds=0.05)
    assert sched.task_count == 2

    await sched.start()
    await asyncio.sleep(0.15)
    sched.stop()

    assert results["a"] >= 2
    assert results["b"] >= 2


@pytest.mark.asyncio
async def test_scheduler_error_doesnt_crash():
    from notas_lave.engine.scheduler import Scheduler

    sched = Scheduler()
    call_count = 0

    async def flaky():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("transient")

    sched.add_task("flaky", flaky, interval_seconds=0.05)
    await sched.start()
    await asyncio.sleep(0.2)
    sched.stop()

    # Should keep running after the error
    assert call_count >= 2


@pytest.mark.asyncio
async def test_scheduler_get_status():
    from notas_lave.engine.scheduler import Scheduler

    sched = Scheduler()
    sched.add_task("health", lambda: None, interval_seconds=60)
    sched.add_task("sync", lambda: None, interval_seconds=300)

    status = sched.get_status()
    assert len(status) == 2
    assert any(t["name"] == "health" for t in status)
    assert any(t["name"] == "sync" for t in status)
