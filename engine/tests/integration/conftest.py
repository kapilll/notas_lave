"""Integration test fixtures — broker selection via BROKER env var.

Usage:
    BROKER=paper pytest tests/integration/ -q
    BROKER=binance_testnet pytest tests/integration/ -q

Same tests, different broker, zero code changes.
"""

import os

import pytest

from notas_lave.core.ports import IBroker


@pytest.fixture
async def broker() -> IBroker:
    """Create a broker based on BROKER env var. Defaults to 'paper'."""
    broker_name = os.environ.get("BROKER", "paper")

    if broker_name == "paper":
        from notas_lave.execution.paper import PaperBroker
        b = PaperBroker(initial_balance=10000.0)
    elif broker_name == "binance_testnet":
        from notas_lave.execution.binance import BinanceBroker
        b = BinanceBroker()
    else:
        pytest.skip(f"Unknown broker: {broker_name}")
        return

    connected = await b.connect()
    if not connected:
        pytest.skip(f"Could not connect to {broker_name}")
        return

    yield b

    await b.disconnect()
