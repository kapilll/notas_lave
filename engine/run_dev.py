#!/usr/bin/env python
"""Development server bootstrap."""

import asyncio
import uvicorn
from dotenv import load_dotenv
import os

load_dotenv('.env')

# Set up logging
import structlog
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
    logger_factory=structlog.PrintLoggerFactory(),
)

# Bootstrap container
from notas_lave.api.app import Container, create_app
from notas_lave.execution.registry import create_broker
from notas_lave.journal.event_store import EventStore
from notas_lave.engine.event_bus import EventBus
from notas_lave.engine.pnl import PnLService
from notas_lave.engine.lab import LabEngine

# Force import all brokers so they register
import notas_lave.execution.paper
import notas_lave.execution.delta

async def main():
    # Create dependencies
    broker_name = os.getenv("BROKER", "delta_testnet")
    broker = create_broker(broker_name)
    await broker.connect()

    balance = await broker.get_balance()

    journal = EventStore()
    bus = EventBus()
    pnl = PnLService(original_deposit=balance.total)

    # Create lab engine
    lab_engine = LabEngine(broker=broker, journal=journal, bus=bus, pnl=pnl)

    # Create container
    container = Container(
        broker=broker,
        journal=journal,
        bus=bus,
        pnl=pnl,
        lab_engine=lab_engine,
        alerter=None,  # Optional telegram alerter
    )

    # Create app
    app = create_app(container)

    # Run server
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
