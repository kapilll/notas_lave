"""Tests for v2 EventBus — pub/sub with failure policies.

The event bus decouples publishers from subscribers.
Failure policies determine what happens when a handler crashes.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest


@dataclass(frozen=True)
class FakeEvent:
    value: int


@dataclass(frozen=True)
class OtherEvent:
    text: str


@pytest.mark.asyncio
async def test_subscribe_and_publish():
    from notas_lave.engine.event_bus import EventBus

    bus = EventBus()
    received = []

    def handler(event: FakeEvent):
        received.append(event.value)

    bus.subscribe(FakeEvent, handler)
    await bus.publish(FakeEvent(value=42))

    assert received == [42]


@pytest.mark.asyncio
async def test_multiple_handlers():
    from notas_lave.engine.event_bus import EventBus

    bus = EventBus()
    results = []

    def handler_a(event: FakeEvent):
        results.append(f"a:{event.value}")

    def handler_b(event: FakeEvent):
        results.append(f"b:{event.value}")

    bus.subscribe(FakeEvent, handler_a)
    bus.subscribe(FakeEvent, handler_b)
    await bus.publish(FakeEvent(value=1))

    assert "a:1" in results
    assert "b:1" in results


@pytest.mark.asyncio
async def test_only_matching_event_type():
    from notas_lave.engine.event_bus import EventBus

    bus = EventBus()
    received = []

    def handler(event: FakeEvent):
        received.append(event.value)

    bus.subscribe(FakeEvent, handler)
    await bus.publish(OtherEvent(text="hello"))

    assert received == []


@pytest.mark.asyncio
async def test_async_handler():
    from notas_lave.engine.event_bus import EventBus

    bus = EventBus()
    received = []

    async def async_handler(event: FakeEvent):
        received.append(event.value)

    bus.subscribe(FakeEvent, async_handler)
    await bus.publish(FakeEvent(value=99))

    assert received == [99]


@pytest.mark.asyncio
async def test_log_and_continue_policy():
    """Handler failure with LOG_AND_CONTINUE should not raise."""
    from notas_lave.engine.event_bus import EventBus, FailurePolicy

    bus = EventBus()

    def failing_handler(event: FakeEvent):
        raise RuntimeError("oops")

    bus.subscribe(FakeEvent, failing_handler, FailurePolicy.LOG_AND_CONTINUE)

    # Should not raise
    await bus.publish(FakeEvent(value=1))


@pytest.mark.asyncio
async def test_halt_policy_raises():
    """Handler failure with HALT should bubble up the exception."""
    from notas_lave.engine.event_bus import EventBus, FailurePolicy

    bus = EventBus()

    def critical_handler(event: FakeEvent):
        raise RuntimeError("DB write failed")

    bus.subscribe(FakeEvent, critical_handler, FailurePolicy.HALT)

    with pytest.raises(RuntimeError, match="DB write failed"):
        await bus.publish(FakeEvent(value=1))


@pytest.mark.asyncio
async def test_retry_policy():
    """RETRY_3X should retry the handler up to 3 times before giving up."""
    from notas_lave.engine.event_bus import EventBus, FailurePolicy

    bus = EventBus()
    call_count = 0

    def flaky_handler(event: FakeEvent):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise RuntimeError("transient error")

    bus.subscribe(FakeEvent, flaky_handler, FailurePolicy.RETRY_3X)
    await bus.publish(FakeEvent(value=1))

    assert call_count == 3  # Failed twice, succeeded on third


@pytest.mark.asyncio
async def test_no_handlers_is_ok():
    """Publishing an event with no subscribers should be a no-op."""
    from notas_lave.engine.event_bus import EventBus

    bus = EventBus()
    await bus.publish(FakeEvent(value=1))  # No error


@pytest.mark.asyncio
async def test_handler_count():
    from notas_lave.engine.event_bus import EventBus

    bus = EventBus()

    bus.subscribe(FakeEvent, lambda e: None)
    bus.subscribe(FakeEvent, lambda e: None)
    bus.subscribe(OtherEvent, lambda e: None)

    assert bus.handler_count(FakeEvent) == 2
    assert bus.handler_count(OtherEvent) == 1
