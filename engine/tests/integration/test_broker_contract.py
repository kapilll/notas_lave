"""Integration tests for the IBroker contract.

These tests run against ANY broker that implements IBroker.
The broker is selected by the BROKER env var (see conftest.py).

Gate: BROKER=paper pytest tests/integration/ -q  →  ALL PASS
      BROKER=binance_testnet pytest tests/integration/ -q  →  ALL PASS
      Same tests. Different broker. Zero code changes.
"""

import pytest

from notas_lave.core.models import (
    BalanceInfo,
    Direction,
    ExchangePosition,
    OrderResult,
    TradeSetup,
)
from notas_lave.core.ports import IBroker


@pytest.mark.asyncio
async def test_broker_satisfies_protocol(broker):
    """Any broker must satisfy IBroker protocol."""
    assert isinstance(broker, IBroker)


@pytest.mark.asyncio
async def test_broker_is_connected(broker):
    """After connect(), broker should be connected."""
    assert broker.is_connected


@pytest.mark.asyncio
async def test_broker_has_name(broker):
    """Every broker must have a name."""
    assert isinstance(broker.name, str)
    assert len(broker.name) > 0


@pytest.mark.asyncio
async def test_get_balance_returns_balance_info(broker):
    """get_balance must return BalanceInfo with total and available."""
    balance = await broker.get_balance()
    assert isinstance(balance, BalanceInfo)
    assert balance.total >= 0
    assert balance.available >= 0
    assert isinstance(balance.currency, str)


@pytest.mark.asyncio
async def test_get_positions_returns_list(broker):
    """get_positions must return a list (possibly empty)."""
    positions = await broker.get_positions()
    assert isinstance(positions, list)
    for pos in positions:
        assert isinstance(pos, ExchangePosition)


@pytest.mark.asyncio
async def test_place_order_returns_order_result(broker):
    """place_order must return OrderResult."""
    setup = TradeSetup(
        symbol="BTCUSD",
        direction=Direction.LONG,
        entry_price=85000.0,
        stop_loss=84000.0,
        take_profit=87000.0,
        position_size=0.001,
    )
    result = await broker.place_order(setup)
    assert isinstance(result, OrderResult)

    if result.success:
        assert result.order_id != ""
        assert result.filled_price > 0
        assert result.filled_quantity > 0

        # Cleanup: close the position we just opened
        await broker.close_position("BTCUSD")


@pytest.mark.asyncio
async def test_close_nonexistent_position(broker):
    """Closing a position that doesn't exist should not crash."""
    result = await broker.close_position("FAKECOIN999")
    assert isinstance(result, OrderResult)
    assert result.success is False


@pytest.mark.asyncio
async def test_cancel_all_orders(broker):
    """cancel_all_orders must return bool."""
    result = await broker.cancel_all_orders("BTCUSD")
    assert isinstance(result, bool)


@pytest.mark.asyncio
async def test_get_order_status(broker):
    """get_order_status must return OrderResult."""
    result = await broker.get_order_status("nonexistent_order")
    assert isinstance(result, OrderResult)


@pytest.mark.asyncio
async def test_full_trade_lifecycle(broker):
    """Open a position, verify it exists, close it, verify it's gone."""
    # 1. Open
    setup = TradeSetup(
        symbol="ETHUSD",
        direction=Direction.SHORT,
        entry_price=2000.0,
        stop_loss=2100.0,
        take_profit=1800.0,
        position_size=0.01,
    )
    open_result = await broker.place_order(setup)
    assert isinstance(open_result, OrderResult)

    if not open_result.success:
        pytest.skip("Broker rejected the order (may need credentials)")
        return

    # 2. Check position exists
    positions = await broker.get_positions()
    symbols = [p.symbol for p in positions]
    assert "ETHUSD" in symbols

    # 3. Close
    close_result = await broker.close_position("ETHUSD")
    assert isinstance(close_result, OrderResult)
    assert close_result.success is True

    # 4. Check position gone
    positions = await broker.get_positions()
    symbols = [p.symbol for p in positions]
    assert "ETHUSD" not in symbols
