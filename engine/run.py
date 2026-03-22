"""
Entry point for the Notas Lave trading engine.

Run with: python run.py
Or with: uvicorn src.api.server:app --reload --port 8000
"""

import logging
import os
import uvicorn
from src.log_config import setup_logging
from src.config import config

setup_logging()
logger = logging.getLogger(__name__)

if __name__ == "__main__":
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
