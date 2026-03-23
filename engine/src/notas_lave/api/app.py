"""v2 FastAPI application factory with dependency injection.

The app factory takes a Container of dependencies. No globals.
Routes are organized into APIRouter modules and included here.

Usage:
    container = Container(broker=..., journal=..., bus=..., pnl=...)
    app = create_app(container)
    uvicorn.run(app, host="127.0.0.1", port=8000)
"""

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..core.ports import IAlerter, IBroker, ITradeJournal
from ..engine.event_bus import EventBus
from ..engine.pnl import PnLService


@dataclass
class Container:
    """Dependency injection container — holds all system dependencies.

    Pass this to create_app(). Route modules access it via get_container().
    No globals, no use_db(), no scattered imports.
    """
    broker: IBroker
    journal: ITradeJournal
    bus: EventBus
    pnl: PnLService
    alerter: IAlerter | None = None
    lab_broker: IBroker | None = None
    lab_journal: ITradeJournal | None = None
    config: dict[str, Any] | None = None


# Module-level reference set by create_app()
_container: Container | None = None


def get_container() -> Container:
    """FastAPI dependency — returns the DI container."""
    if _container is None:
        raise RuntimeError("Container not initialized. Call create_app() first.")
    return _container


def create_app(container: Container) -> FastAPI:
    """Create and configure the FastAPI application with DI."""
    global _container
    _container = container

    app = FastAPI(
        title="Notas Lave v2",
        description="AI-powered trading engine — clean architecture",
        version="2.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-API-Key"],
    )

    # Include route modules
    from .system_routes import router as system_router
    from .trade_routes import router as trade_router
    from .lab_routes import router as lab_router
    from .learning_routes import router as learning_router

    app.include_router(system_router)
    app.include_router(trade_router)
    app.include_router(lab_router)
    app.include_router(learning_router)

    return app
