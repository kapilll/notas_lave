"""Event bus with configurable failure handling.

CRITICAL events (DB logging) -> retry 3x, then halt
OPTIONAL events (Telegram) -> log error, continue

Usage:
    bus = EventBus()
    bus.subscribe(TradeClosed, save_to_db, FailurePolicy.RETRY_3X)
    bus.subscribe(TradeClosed, notify_telegram, FailurePolicy.LOG_AND_CONTINUE)
    await bus.publish(TradeClosed(...))
"""

import asyncio
import logging
from collections import defaultdict
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class FailurePolicy(Enum):
    LOG_AND_CONTINUE = "log"   # For notifications
    RETRY_3X = "retry"         # For persistence
    HALT = "halt"              # For critical invariants


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type, list[tuple[Callable, FailurePolicy]]] = defaultdict(list)

    def subscribe(
        self,
        event_type: type,
        handler: Callable,
        policy: FailurePolicy = FailurePolicy.LOG_AND_CONTINUE,
    ) -> None:
        self._handlers[event_type].append((handler, policy))

    def handler_count(self, event_type: type) -> int:
        return len(self._handlers.get(event_type, []))

    async def publish(self, event: Any) -> None:
        for handler, policy in self._handlers.get(type(event), []):
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                if policy == FailurePolicy.HALT:
                    raise
                elif policy == FailurePolicy.RETRY_3X:
                    await self._retry(handler, event, max_retries=3)
                else:
                    logger.error(
                        "Event handler %s failed: %s",
                        handler.__name__,
                        e,
                    )

    async def _retry(
        self, handler: Callable, event: Any, max_retries: int = 3,
    ) -> None:
        for attempt in range(1, max_retries + 1):
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
                return
            except Exception as e:
                if attempt == max_retries:
                    logger.error(
                        "Event handler %s failed after %d retries: %s",
                        handler.__name__,
                        max_retries,
                        e,
                    )
                else:
                    logger.warning(
                        "Event handler %s retry %d/%d: %s",
                        handler.__name__,
                        attempt,
                        max_retries,
                        e,
                    )
