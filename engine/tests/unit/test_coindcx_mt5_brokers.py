"""Tests for v2 CoinDCX and MT5 broker adapters.

Both satisfy IBroker. CoinDCX is standalone with HTTP logic.
MT5 is a stub that gracefully handles non-Windows.
"""

import pytest

from notas_lave.core.models import BalanceInfo, Direction, OrderResult, TradeSetup
from notas_lave.core.ports import IBroker


def test_coindcx_satisfies_ibroker():
    from notas_lave.execution.coindcx import CoinDCXBroker

    broker = CoinDCXBroker(api_key="fake", api_secret="fake")
    assert isinstance(broker, IBroker)


def test_coindcx_name():
    from notas_lave.execution.coindcx import CoinDCXBroker

    broker = CoinDCXBroker(api_key="fake", api_secret="fake")
    assert broker.name == "coindcx"


def test_coindcx_registered():
    from notas_lave.execution.coindcx import CoinDCXBroker
    from notas_lave.execution.registry import _REGISTRY

    assert "coindcx" in _REGISTRY


@pytest.mark.asyncio
async def test_coindcx_disconnected_balance():
    from notas_lave.execution.coindcx import CoinDCXBroker

    broker = CoinDCXBroker(api_key="fake", api_secret="fake")
    balance = await broker.get_balance()
    assert isinstance(balance, BalanceInfo)
    assert balance.total == 0


@pytest.mark.asyncio
async def test_coindcx_disconnected_rejects_order():
    from notas_lave.execution.coindcx import CoinDCXBroker

    broker = CoinDCXBroker(api_key="fake", api_secret="fake")
    setup = TradeSetup(
        symbol="BTCUSD", direction=Direction.LONG,
        entry_price=85000.0, stop_loss=84000.0,
        take_profit=87000.0, position_size=0.01,
    )
    result = await broker.place_order(setup)
    assert isinstance(result, OrderResult)
    assert result.success is False


# --- MT5 ---

def test_mt5_satisfies_ibroker():
    from notas_lave.execution.mt5 import MT5Broker

    broker = MT5Broker()
    assert isinstance(broker, IBroker)


def test_mt5_name():
    from notas_lave.execution.mt5 import MT5Broker

    broker = MT5Broker()
    assert broker.name == "mt5"


def test_mt5_registered():
    from notas_lave.execution.mt5 import MT5Broker
    from notas_lave.execution.registry import _REGISTRY

    assert "mt5" in _REGISTRY


@pytest.mark.asyncio
async def test_mt5_not_available_on_macos():
    from notas_lave.execution.mt5 import MT5Broker

    broker = MT5Broker()
    connected = await broker.connect()
    assert connected is False  # MT5 only works on Windows
    assert broker.is_connected is False


@pytest.mark.asyncio
async def test_mt5_returns_empty_when_disconnected():
    from notas_lave.execution.mt5 import MT5Broker

    broker = MT5Broker()
    balance = await broker.get_balance()
    assert isinstance(balance, BalanceInfo)
    assert balance.total == 0

    positions = await broker.get_positions()
    assert positions == []
