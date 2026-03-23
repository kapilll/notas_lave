"""System routes — health, status, broker info.

No business logic here. Just reads from the DI container
and formats responses.
"""

from fastapi import APIRouter, Depends

from .app import Container, get_container

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}


@router.get("/api/v2/system/health")
async def system_health(c: Container = Depends(get_container)):
    broker_connected = c.broker.is_connected
    journal_events = c.journal.event_count() if hasattr(c.journal, "event_count") else -1
    bus_handlers = sum(
        c.bus.handler_count(t) for t in c.bus._handlers
    ) if hasattr(c.bus, "_handlers") else 0

    return {
        "status": "ok",
        "broker": c.broker.name,
        "broker_connected": broker_connected,
        "journal_events": journal_events,
        "event_bus_handlers": bus_handlers,
    }
