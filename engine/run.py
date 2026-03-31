"""Notas Lave v2 — unified runner (API + Lab Engine).

Starts:
1. FastAPI backend on :8000 (serves dashboard API)
2. Lab engine scanning via configured broker (background task)
3. Telegram notifications on trade events

Usage:
    cd engine && ../.venv/bin/python run.py

Broker is selected via BROKER env var (default: delta_testnet).
Original deposit is fetched from the broker's actual balance on connect.
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from notas_lave.observability.logging import setup_logging

setup_logging(json_output=False)
logger = logging.getLogger("notas_lave")

import uvicorn
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from notas_lave.api.app import Container, create_app
from notas_lave.core.events import TradeClosed, TradeOpened
from notas_lave.engine.event_bus import EventBus, FailurePolicy
from notas_lave.engine.lab import LabEngine
from notas_lave.engine.pnl import PnLService
from notas_lave.execution.registry import create_broker
from notas_lave.journal.event_store import EventStore

# Import all brokers so they register themselves
import notas_lave.execution.paper  # noqa: F401
import notas_lave.execution.delta  # noqa: F401


async def _notify_telegram(event):
    try:
        from notas_lave.alerts.telegram import send_telegram

        if isinstance(event, TradeOpened):
            await send_telegram(
                f"[LAB] *OPENED* {event.direction} {event.symbol}\n"
                f"Entry: `{event.entry_price}` SL: `{event.stop_loss}` "
                f"TP: `{event.take_profit}`"
            )
        elif isinstance(event, TradeClosed):
            sign = "+" if event.pnl >= 0 else ""
            await send_telegram(
                f"[LAB] *CLOSED* {event.direction} {event.symbol}\n"
                f"P&L: `{sign}{event.pnl:.4f}` Reason: `{event.reason}`"
            )
    except Exception as e:
        logger.warning("Telegram failed: %s", e)


async def _get_deposit(broker) -> float:
    """Fetch actual balance from broker to use as original deposit."""
    balance = await broker.get_balance()
    return balance.total if balance.total > 0 else 100.0


def build_container() -> Container:
    """Wire up all dependencies from env vars. Nothing hardcoded."""
    broker_name = os.environ.get("BROKER", "delta_testnet")
    broker = create_broker(broker_name)

    db_path = os.path.join(os.path.dirname(__file__), "notas_lave_lab_v2.db")
    journal = EventStore(db_path)
    bus = EventBus()

    # Connect broker and read actual balance for deposit
    loop = asyncio.new_event_loop()
    connected = loop.run_until_complete(broker.connect())
    if connected:
        deposit = loop.run_until_complete(_get_deposit(broker))
        loop.run_until_complete(broker.disconnect())
    else:
        deposit = float(os.environ.get("INITIAL_DEPOSIT", "100"))
        logger.warning("Broker not connected at startup, using INITIAL_DEPOSIT=%s", deposit)
    loop.close()

    logger.info("Original deposit: %.2f (from broker)", deposit)
    pnl = PnLService(original_deposit=deposit)

    # Telegram alerts
    bus.subscribe(TradeOpened, _notify_telegram, FailurePolicy.LOG_AND_CONTINUE)
    bus.subscribe(TradeClosed, _notify_telegram, FailurePolicy.LOG_AND_CONTINUE)

    # Trade autopsy — post-trade AI analysis
    from notas_lave.learning.trade_autopsy import handle_trade_closed
    bus.subscribe(TradeClosed, handle_trade_closed, FailurePolicy.LOG_AND_CONTINUE)

    lab = LabEngine(broker=broker, journal=journal, bus=bus, pnl=pnl)

    return Container(
        broker=broker,
        journal=journal,
        bus=bus,
        pnl=pnl,
        lab_engine=lab,
        lab_journal=journal,
    )


if __name__ == "__main__":
    container = build_container()
    app = create_app(container)

    host = os.environ.get("API_HOST", "0.0.0.0")
    port = int(os.environ.get("API_PORT", "8000"))

    logger.info("Starting Notas Lave v2...")
    logger.info("  API:       http://%s:%d", host, port)
    logger.info("  Dashboard: http://localhost:3000")
    logger.info("  Broker:    %s", container.broker.name)

    uvicorn.run(app, host=host, port=port)
