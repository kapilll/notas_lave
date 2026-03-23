"""v2 Lab Engine Runner — start the lab on Binance Demo.

Usage:
    cd engine && ../.venv/bin/python lab_runner.py

Wires up the DI container with real dependencies:
- BinanceBroker (Binance Demo)
- EventStore (SQLite append-only journal)
- EventBus (pub/sub with failure policies)
- PnLService (balance - deposit)
- Telegram alerts on trade events
"""

import asyncio
import logging
import os
import sys

# Add src/ to path for notas_lave imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from notas_lave.observability.logging import setup_logging

setup_logging(json_output=False)
logger = logging.getLogger("lab_runner")

from notas_lave.engine.event_bus import EventBus, FailurePolicy
from notas_lave.engine.lab import LabEngine
from notas_lave.engine.pnl import PnLService
from notas_lave.execution.binance import BinanceBroker
from notas_lave.journal.event_store import EventStore
from notas_lave.core.events import TradeOpened, TradeClosed


async def _notify_telegram(event):
    """Send Telegram notification for trade events."""
    try:
        from notas_lave.alerts.telegram import send_telegram

        if isinstance(event, TradeOpened):
            await send_telegram(
                f"[LAB] *OPENED* {event.direction} {event.symbol}\n"
                f"Entry: `{event.entry_price}` SL: `{event.stop_loss}` "
                f"TP: `{event.take_profit}` Size: `{event.position_size}`"
            )
        elif isinstance(event, TradeClosed):
            emoji = "+" if event.pnl >= 0 else ""
            await send_telegram(
                f"[LAB] *CLOSED* {event.direction} {event.symbol}\n"
                f"P&L: `{emoji}{event.pnl:.4f}` Reason: `{event.reason}`"
            )
    except Exception as e:
        logger.warning("Telegram notification failed: %s", e)


async def main():
    # Load Binance keys from .env
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        from dotenv import load_dotenv
        load_dotenv(env_path)

    api_key = os.environ.get("BINANCE_TESTNET_KEY", "")
    api_secret = os.environ.get("BINANCE_TESTNET_SECRET", "")

    if not api_key or not api_secret:
        logger.error("Set BINANCE_TESTNET_KEY and BINANCE_TESTNET_SECRET in engine/.env")
        return

    # Wire up dependencies
    broker = BinanceBroker(api_key=api_key, api_secret=api_secret)
    journal = EventStore(os.path.join(os.path.dirname(__file__), "notas_lave_lab_v2.db"))
    bus = EventBus()
    pnl = PnLService(original_deposit=5000.0)

    # Subscribe Telegram alerts
    bus.subscribe(TradeOpened, _notify_telegram, FailurePolicy.LOG_AND_CONTINUE)
    bus.subscribe(TradeClosed, _notify_telegram, FailurePolicy.LOG_AND_CONTINUE)

    # Create and start engine
    engine = LabEngine(broker=broker, journal=journal, bus=bus, pnl=pnl)
    await engine.start()

    if not engine.is_running:
        logger.error("Lab engine failed to start")
        return

    # Print status
    status = await engine.get_status()
    logger.info("Lab running — balance=%.2f, open=%d, closed=%d",
                status["balance"], status["open_trades"], status["closed_trades"])

    # Run until interrupted
    try:
        while engine.is_running:
            await asyncio.sleep(30)
            # Periodic status
            status = await engine.get_status()
            balance_info = await broker.get_balance()
            pnl_result = pnl.calculate(balance_info.total)
            pnl.update_peak(balance_info.total)
            logger.info(
                "Status: balance=%.2f pnl=%.2f open=%d closed=%d",
                balance_info.total, pnl_result.pnl,
                status["open_trades"], status["closed_trades"],
            )
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        engine.stop()
        await broker.disconnect()
        logger.info("Lab engine shut down cleanly")


if __name__ == "__main__":
    asyncio.run(main())
