"""Tests for v2 BinanceBroker adapter.

The adapter wraps the existing BinanceTestnetBroker and translates
to v2 IBroker types. Tests use a mock inner broker to avoid network calls.
"""

import pytest

from notas_lave.core.models import (
    BalanceInfo, Direction, ExchangePosition, OrderResult, TradeSetup,
)
from notas_lave.core.ports import IBroker


def test_binance_broker_satisfies_ibroker():
    from notas_lave.execution.binance import BinanceBroker

    broker = BinanceBroker.__new__(BinanceBroker)
    assert isinstance(broker, IBroker)


def test_binance_broker_name():
    from notas_lave.execution.binance import BinanceBroker

    broker = BinanceBroker.__new__(BinanceBroker)
    assert broker.name == "binance_testnet"


def test_binance_broker_uses_instrument_registry():
    """Symbol mapping should come from InstrumentRegistry, not SYMBOL_MAP."""
    from notas_lave.core.instruments import get_instrument

    btc = get_instrument("BTCUSD")
    assert btc.exchange_symbol("binance") == "BTCUSDT"


def test_binance_broker_registered():
    """BinanceBroker should auto-register via @register_broker."""
    from notas_lave.execution.binance import BinanceBroker
    from notas_lave.execution.registry import _REGISTRY

    assert "binance_testnet" in _REGISTRY


@pytest.mark.asyncio
async def test_binance_broker_get_balance_returns_balance_info():
    """get_balance must return BalanceInfo, not dict."""
    from notas_lave.execution.binance import BinanceBroker

    class MockInner:
        _connected = True

        @property
        def is_connected(self):
            return self._connected

        async def connect(self):
            return True

        async def get_balance(self):
            return {"currency": "USDT", "available": 4500.0, "total": 5000.0}

    broker = BinanceBroker.__new__(BinanceBroker)
    broker._inner = MockInner()

    balance = await broker.get_balance()
    assert isinstance(balance, BalanceInfo)
    assert balance.total == 5000.0
    assert balance.available == 4500.0
    assert balance.currency == "USDT"


@pytest.mark.asyncio
async def test_binance_broker_get_positions_returns_exchange_positions():
    """get_positions must return list[ExchangePosition]."""
    from notas_lave.execution.binance import BinanceBroker

    class MockInnerPos:
        symbol = "BTCUSDT"
        side = type("S", (), {"value": "BUY"})()
        quantity = 0.01
        entry_price = 85000.0
        current_price = 86000.0
        unrealized_pnl = 10.0
        leverage = 5.0

    class MockInner:
        _connected = True

        @property
        def is_connected(self):
            return self._connected

        async def get_positions(self):
            return [MockInnerPos()]

    broker = BinanceBroker.__new__(BinanceBroker)
    broker._inner = MockInner()

    positions = await broker.get_positions()
    assert len(positions) == 1
    assert isinstance(positions[0], ExchangePosition)
    assert positions[0].symbol == "BTCUSDT"
    assert positions[0].direction == Direction.LONG


@pytest.mark.asyncio
async def test_binance_broker_place_order_returns_order_result():
    """place_order must accept TradeSetup and return OrderResult."""
    from notas_lave.execution.binance import BinanceBroker

    class MockOrder:
        broker_order_id = "12345"
        status = type("S", (), {"value": "FILLED"})()
        filled_price = 85000.0
        filled_quantity = 0.01
        fee = 0.34

    class MockInner:
        _connected = True

        @property
        def is_connected(self):
            return self._connected

        async def place_order(self, **kwargs):
            return MockOrder()

    broker = BinanceBroker.__new__(BinanceBroker)
    broker._inner = MockInner()

    setup = TradeSetup(
        symbol="BTCUSD",
        direction=Direction.LONG,
        entry_price=85000.0,
        stop_loss=84000.0,
        take_profit=87000.0,
        position_size=0.01,
    )
    result = await broker.place_order(setup)

    assert isinstance(result, OrderResult)
    assert result.success is True
    assert result.filled_price == 85000.0
    assert result.order_id == "12345"
