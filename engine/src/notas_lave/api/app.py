"""v2 FastAPI application factory with dependency injection.

The app factory takes a Container of dependencies. No globals.
Routes are organized into APIRouter modules and included here.

Usage:
    container = Container(broker=..., journal=..., bus=..., pnl=...)
    app = create_app(container)
    uvicorn.run(app, host="127.0.0.1", port=8000)
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..core.ports import IAlerter, IBroker, ITradeJournal
from ..engine.event_bus import EventBus
from ..engine.pnl import PnLService


@dataclass
class Container:
    """Dependency injection container."""
    broker: IBroker
    journal: ITradeJournal
    bus: EventBus
    pnl: PnLService
    alerter: IAlerter | None = None
    lab_broker: IBroker | None = None
    lab_journal: ITradeJournal | None = None
    lab_engine: Any = None
    config: dict[str, Any] = field(default_factory=dict)


_container: Container | None = None


def get_container() -> Container:
    if _container is None:
        raise RuntimeError("Container not initialized. Call create_app() first.")
    return _container


def create_app(container: Container) -> FastAPI:
    global _container
    _container = container

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: start lab engine if configured
        if container.lab_engine:
            await container.lab_engine.start()

        yield

        # Shutdown: stop lab engine
        if container.lab_engine and container.lab_engine.is_running:
            container.lab_engine.stop()
        await container.broker.disconnect()

    app = FastAPI(
        title="Notas Lave Trading Engine",
        description="AI-powered trading engine — v2 architecture",
        version="2.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-API-Key"],
    )

    from .system_routes import router as system_router
    from .trade_routes import router as trade_router
    from .lab_routes import router as lab_router
    from .learning_routes import router as learning_router

    app.include_router(system_router)
    app.include_router(trade_router)
    app.include_router(lab_router)
    app.include_router(learning_router)

    return app
