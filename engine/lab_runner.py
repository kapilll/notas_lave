"""
Lab Engine Entry Point -- run alongside production.

Usage:
    cd engine && ../.venv/bin/python lab_runner.py

The Lab trades aggressively on Binance Demo to generate learning data.
It uses a SEPARATE database (notas_lave_lab.db) so lab trades don't
contaminate production analysis.
"""

import asyncio
from src.log_config import setup_logging

setup_logging()

from src.lab.lab_trader import LabTrader

lab_trader = LabTrader()


async def main():
    """Run the lab engine as a standalone async loop."""
    await lab_trader.start()

    # Keep running until interrupted
    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, asyncio.CancelledError):
        lab_trader.stop()
        print("\nLab Engine stopped.")


if __name__ == "__main__":
    asyncio.run(main())
