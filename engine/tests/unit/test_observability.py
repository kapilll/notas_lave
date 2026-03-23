"""Tests for v2 structured logging setup."""

import json
import logging


def test_setup_logging():
    from notas_lave.observability.logging import setup_logging

    setup_logging()

    import structlog
    log = structlog.get_logger("test")
    assert log is not None


def test_get_logger():
    from notas_lave.observability.logging import get_logger

    log = get_logger("test_component")
    assert log is not None


def test_log_output_is_structured(capsys):
    from notas_lave.observability.logging import setup_logging, get_logger

    setup_logging(json_output=False)
    log = get_logger("test")
    log.info("test_message", trade_id="t001", symbol="BTCUSD")

    # structlog should produce structured output (not crash)
    # The exact format depends on configuration
