"""
Entry point for the Notas Lave trading engine.

Run with: python run.py
Or with: uvicorn src.api.server:app --reload --port 8000
"""

import logging
import os
import signal
import uvicorn
from src.log_config import setup_logging
from src.config import config

setup_logging()
logger = logging.getLogger(__name__)


def _handle_shutdown(signum, frame):
    """AT-40/DO-21: Graceful shutdown on SIGTERM/SIGINT.

    Saves risk state and logs shutdown. Uvicorn's lifespan handler
    takes care of stopping the traders and closing connections —
    this just ensures we don't get a dirty WAL on hard kill.
    """
    sig_name = signal.Signals(signum).name
    logger.info("Received %s — initiating graceful shutdown", sig_name)

    # Save production risk state so balance survives restart
    try:
        from src.risk.manager import risk_manager
        from src.journal.database import save_risk_state
        save_risk_state(
            risk_manager.starting_balance,
            risk_manager.current_balance,
            risk_manager.total_pnl,
            risk_manager.peak_balance,
        )
        logger.info("Risk state saved")
    except Exception as e:
        logger.error("Failed to save risk state on shutdown: %s", e)

    logger.info("Graceful shutdown complete")
    # Re-raise so uvicorn's own signal handling proceeds
    raise SystemExit(0)


if __name__ == "__main__":
    # AT-40/DO-21: Register signal handlers before starting uvicorn
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    logger.info("Starting Notas Lave Trading Engine...")
    logger.info("  Instruments: %s", config.instruments)
    logger.info("  Entry TFs:   %s", config.entry_timeframes)
    logger.info("  Context TFs: %s", config.context_timeframes)
    logger.info("  API:         http://%s:%s", config.api_host, config.api_port)
    logger.info("  Dashboard:   http://localhost:3000")

    # OPS-10: Only enable reload in dev mode. In production, reload=True
    # causes restarts on any file change, wiping in-memory positions.
    dev_mode = os.environ.get("DEV_MODE", "").lower() == "true"
    uvicorn.run(
        "src.api.server:app",
        host=config.api_host,
        port=config.api_port,
        reload=dev_mode,
    )
