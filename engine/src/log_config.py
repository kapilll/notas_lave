"""
Centralized logging configuration for Notas Lave.

OPS-03 FIX: Replace 125+ print() statements with structured logging.
All modules should use: import logging; logger = logging.getLogger(__name__)
"""

import logging
import sys
import os


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with console + optional file output."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Format: timestamp [level] module - message
    fmt = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(fmt, datefmt))

    # DO-19: RotatingFileHandler — prevents unbounded log growth.
    # 10MB max per file, 5 backups = 60MB max total disk usage for logs.
    # Creates the data/ directory if it doesn't exist.
    handlers: list[logging.Handler] = [console]
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    os.makedirs(log_dir, exist_ok=True)
    if os.path.isdir(log_dir):
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, "notas_lave.log"),
            maxBytes=10_000_000,  # 10MB
            backupCount=5,        # 5 backup files (DO-19)
        )
        file_handler.setFormatter(logging.Formatter(fmt, datefmt))
        handlers.append(file_handler)

    logging.basicConfig(level=log_level, handlers=handlers, force=True)

    # Suppress noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("ccxt").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger for a module. Usage: logger = get_logger(__name__)"""
    return logging.getLogger(name)
