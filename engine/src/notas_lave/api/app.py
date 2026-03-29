"""v2 FastAPI application factory with dependency injection.

The app factory takes a Container of dependencies. No globals.
Routes are organized into APIRouter modules and included here.

Usage:
    container = Container(broker=..., journal=..., bus=..., pnl=...)
    app = create_app(container)
    uvicorn.run(app, host="127.0.0.1", port=8000)
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
    alert_scanner: Any = None
    config: dict[str, Any] = field(default_factory=dict)


_container: Container | None = None


def get_container() -> Container:
    if _container is None:
        raise RuntimeError("Container not initialized. Call create_app() first.")
    return _container


def create_app(container: Container) -> FastAPI:
    global _container
    _container = container

    _weekly_review_task: asyncio.Task | None = None

    async def _run_weekly_review():
        """Background task: run Claude weekly review every 7 days."""
        while True:
            await asyncio.sleep(7 * 24 * 3600)
            try:
                from ..learning.claude_review import generate_review
                result = await generate_review()
                logger.info("Weekly review completed: %s", result.get("status"))
            except Exception as e:
                logger.warning("Weekly review failed: %s", e)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal _weekly_review_task

        # Startup: start lab engine if configured
        if container.lab_engine:
            await container.lab_engine.start()

        # Startup: start alert scanner if enabled
        if container.alert_scanner and os.environ.get("ALERT_SCANNER_ENABLED", "false").lower() == "true":
            await container.alert_scanner.start()

        # Startup: schedule weekly Claude review
        _weekly_review_task = asyncio.create_task(_run_weekly_review())

        yield

        # Shutdown: cancel weekly review task
        if _weekly_review_task:
            _weekly_review_task.cancel()

        # Shutdown: stop alert scanner
        if container.alert_scanner:
            container.alert_scanner.stop()

        # Shutdown: stop lab engine
        if container.lab_engine and container.lab_engine.is_running:
            await container.lab_engine.stop()
        await container.broker.disconnect()

    app = FastAPI(
        title="Notas Lave Trading Engine",
        description="AI-powered trading engine — v2 architecture",
        version="2.0.0",
        lifespan=lifespan,
    )

    # SE-01 FIX: Restrict CORS to dashboard origin (not wildcard).
    # In dev, allow localhost. In prod, only the VM's own origin.
    allowed_origins = os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-API-Key"],
    )

    # SE-01 FIX: API key middleware for all endpoints except /health.
    # Set API_KEY env var to enable. If empty, auth is disabled (dev mode).
    api_key = os.environ.get("API_KEY", "")

    @app.middleware("http")
    async def check_api_key(request: Request, call_next):
        if not api_key:
            return await call_next(request)  # Dev mode: no auth
        if request.url.path in ("/health", "/docs", "/openapi.json"):
            return await call_next(request)  # Health check always open
        req_key = request.headers.get("X-API-Key", "")
        if req_key != api_key:
            return JSONResponse(status_code=401, content={"detail": "Invalid API key"})
        return await call_next(request)

    from .system_routes import router as system_router
    from .trade_routes import router as trade_router
    from .lab_routes import router as lab_router
    from .learning_routes import router as learning_router
    from .backtest_routes import router as backtest_router
    from .ws_routes import router as ws_router

    app.include_router(system_router)
    app.include_router(trade_router)
    app.include_router(lab_router)
    app.include_router(learning_router)
    app.include_router(backtest_router)
    app.include_router(ws_router)

    return app
