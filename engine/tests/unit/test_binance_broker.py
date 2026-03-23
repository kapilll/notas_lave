"""Tests for v2 BinanceBroker — standalone implementation.

Tests verify the broker satisfies IBroker, uses InstrumentRegistry,
and handles disconnected state correctly. No network calls.
"""

import pytest

from notas_lave.core.models import (
    BalanceInfo, Direction, ExchangePosition, OrderResult, TradeSetup,
)
from notas_lave.core.ports import IBroker


def test_binance_broker_satisfies_ibroker():
    from notas_lave.execution.binance import BinanceBroker

    broker = BinanceBroker(api_key="fake", api_secret="fake")
    assert isinstance(broker, IBroker)


def test_binance_broker_name():
    from notas_lave.execution.binance import BinanceBroker

    broker = BinanceBroker(api_key="fake", api_secret="fake")
    assert broker.name == "binance_testnet"


def test_binance_broker_uses_instrument_registry():
    from notas_lave.execution.binance import BinanceBroker

    broker = BinanceBroker(api_key="fake", api_secret="fake")
    assert broker._exchange_symbol("BTCUSD") == "BTCUSDT"
    assert broker._exchange_symbol("ETHUSD") == "ETHUSDT"
    assert broker._exchange_symbol("SOLUSD") == "SOLUSDT"
    # Pass-through for already-mapped
    assert broker._exchange_symbol("BTCUSDT") == "BTCUSDT"


def test_binance_broker_registered():
    from notas_lave.execution.binance import BinanceBroker
    from notas_lave.execution.registry import _REGISTRY

    assert "binance_testnet" in _REGISTRY


@pytest.mark.asyncio
async def test_binance_disconnected_returns_empty_balance():
    from notas_lave.execution.binance import BinanceBroker

    broker = BinanceBroker(api_key="fake", api_secret="fake")
    # Not connected
    balance = await broker.get_balance()
    assert isinstance(balance, BalanceInfo)
    assert balance.total == 0


@pytest.mark.asyncio
async def test_binance_disconnected_returns_empty_positions():
    from notas_lave.execution.binance import BinanceBroker

    broker = BinanceBroker(api_key="fake", api_secret="fake")
    positions = await broker.get_positions()
    assert positions == []


@pytest.mark.asyncio
async def test_binance_disconnected_rejects_order():
    from notas_lave.execution.binance import BinanceBroker

    broker = BinanceBroker(api_key="fake", api_secret="fake")
    setup = TradeSetup(
        symbol="BTCUSD", direction=Direction.LONG,
        entry_price=85000.0, stop_loss=84000.0,
        take_profit=87000.0, position_size=0.01,
    )
    result = await broker.place_order(setup)
    assert isinstance(result, OrderResult)
    assert result.success is False
    assert "Not connected" in result.error
