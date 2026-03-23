"""Notas Lave v2 — unified runner (API + Lab Engine).

Starts:
1. FastAPI backend on :8000 (serves dashboard API)
2. Lab engine scanning on Binance Demo (background task)
3. Telegram notifications on trade events

Usage:
    cd engine && ../.venv/bin/python run.py
"""

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
from notas_lave.execution.binance import BinanceBroker
from notas_lave.journal.event_store import EventStore


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


def build_container() -> Container:
    """Wire up all dependencies."""
    api_key = os.environ.get("BINANCE_TESTNET_KEY", "")
    api_secret = os.environ.get("BINANCE_TESTNET_SECRET", "")

    broker = BinanceBroker(api_key=api_key, api_secret=api_secret)
    db_path = os.path.join(os.path.dirname(__file__), "notas_lave_lab_v2.db")
    journal = EventStore(db_path)
    bus = EventBus()
    pnl = PnLService(original_deposit=5000.0)

    # Telegram alerts
    bus.subscribe(TradeOpened, _notify_telegram, FailurePolicy.LOG_AND_CONTINUE)
    bus.subscribe(TradeClosed, _notify_telegram, FailurePolicy.LOG_AND_CONTINUE)

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

    logger.info("Starting Notas Lave v2...")
    logger.info("  API:       http://127.0.0.1:8000")
    logger.info("  Dashboard: http://localhost:3000")
    logger.info("  Broker:    %s", container.broker.name)

    uvicorn.run(app, host="127.0.0.1", port=8000)
