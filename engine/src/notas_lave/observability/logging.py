"""Structured logging with structlog.

Every log line has: timestamp, level, component, and structured data.
JSON output for production, human-readable for development.

Usage:
    from notas_lave.observability.logging import setup_logging, get_logger

    setup_logging()  # Call once at startup
    log = get_logger("engine.lab")
    log.info("trade_opened", symbol="BTCUSD", trade_id="t001", price=85000.0)
"""

import logging
import sys

import structlog


def setup_logging(
    level: int = logging.INFO,
    json_output: bool = True,
) -> None:
    """Configure structlog for the application.

    Args:
        level: Log level (default INFO).
        json_output: True for JSON (production), False for console (dev).
    """
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if json_output:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structured logger for a component."""
    return structlog.get_logger(name)
