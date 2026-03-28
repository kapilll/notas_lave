"""Startup smoke tests — catch config/wiring bugs before deploy.

These tests validate that the engine can actually start with the
configured environment. The deploy failure (v1.0.0) happened because
BROKER=binance_testnet was in the VM's .env but the Binance broker
was removed from code. CI tests passed because they use defaults.

Rule: If you remove a broker, strategy, or config field, add a test
here that verifies the system still starts.
"""

import os
import pytest

# Import brokers so they register themselves (same as run.py does)
import notas_lave.execution.paper  # noqa: F401
import notas_lave.execution.delta  # noqa: F401
from notas_lave.execution.registry import create_broker, list_brokers


def test_default_broker_exists():
    """The default BROKER value must be a registered broker."""
    from notas_lave.config import config
    default_broker = config.broker
    available = list_brokers()
    assert default_broker in available, (
        f"Default broker '{default_broker}' not registered. "
        f"Available: {available}. "
        f"Check config.py broker default and execution/ imports in run.py"
    )


def test_all_registered_brokers_instantiate():
    """Every registered broker must be instantiable (no import errors)."""
    for name in list_brokers():
        broker = create_broker(name)
        assert broker.name == name


def test_env_broker_if_set():
    """If BROKER env var is set, it must be a registered broker."""
    broker_name = os.environ.get("BROKER")
    if broker_name is None:
        pytest.skip("BROKER env var not set")
    available = list_brokers()
    assert broker_name in available, (
        f"BROKER={broker_name} is not registered. "
        f"Available: {available}. "
        f"Update .env on the VM."
    )


def test_config_loads_without_error():
    """Config must load without validation errors."""
    from notas_lave.config import TradingConfig
    cfg = TradingConfig()
    assert cfg.api_port == 8000


def test_no_inr_in_config():
    """Config must not have INR-related fields (USD only)."""
    from notas_lave.config import TradingConfig
    cfg = TradingConfig()
    assert not hasattr(cfg, "initial_balance_inr")
    assert not hasattr(cfg, "usd_inr_rate")
    assert not hasattr(cfg, "currency_symbol")
