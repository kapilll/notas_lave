"""Tests for v2 PaperBroker — in-memory IBroker implementation.

PaperBroker is deterministic: fills at the entry_price,
tracks positions and balance in memory. No I/O.
"""

import pytest

from notas_lave.core.models import (
    BalanceInfo, Direction, ExchangePosition, OrderResult, TradeSetup,
)
from notas_lave.core.ports import IBroker


@pytest.mark.asyncio
async def test_paper_broker_satisfies_ibroker():
    from notas_lave.execution.paper import PaperBroker

    broker = PaperBroker(initial_balance=10000.0)
    assert isinstance(broker, IBroker)


@pytest.mark.asyncio
async def test_paper_broker_name():
    from notas_lave.execution.paper import PaperBroker

    broker = PaperBroker(initial_balance=10000.0)
    assert broker.name == "paper"


@pytest.mark.asyncio
async def test_paper_broker_connect():
    from notas_lave.execution.paper import PaperBroker

    broker = PaperBroker(initial_balance=10000.0)
    assert not broker.is_connected
    result = await broker.connect()
    assert result is True
    assert broker.is_connected


@pytest.mark.asyncio
async def test_paper_broker_get_balance():
    from notas_lave.execution.paper import PaperBroker

    broker = PaperBroker(initial_balance=10000.0)
    await broker.connect()
    balance = await broker.get_balance()

    assert isinstance(balance, BalanceInfo)
    assert balance.total == 10000.0
    assert balance.available == 10000.0


@pytest.mark.asyncio
async def test_paper_broker_place_order():
    from notas_lave.execution.paper import PaperBroker

    broker = PaperBroker(initial_balance=10000.0)
    await broker.connect()

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
    assert result.filled_quantity == 0.01
    assert result.order_id != ""


@pytest.mark.asyncio
async def test_paper_broker_positions_after_order():
    from notas_lave.execution.paper import PaperBroker

    broker = PaperBroker(initial_balance=10000.0)
    await broker.connect()

    setup = TradeSetup(
        symbol="BTCUSD",
        direction=Direction.LONG,
        entry_price=85000.0,
        stop_loss=84000.0,
        take_profit=87000.0,
        position_size=0.01,
    )
    await broker.place_order(setup)

    positions = await broker.get_positions()
    assert len(positions) == 1
    assert isinstance(positions[0], ExchangePosition)
    assert positions[0].symbol == "BTCUSD"
    assert positions[0].direction == Direction.LONG
    assert positions[0].quantity == 0.01


@pytest.mark.asyncio
async def test_paper_broker_close_position():
    from notas_lave.execution.paper import PaperBroker

    broker = PaperBroker(initial_balance=10000.0)
    await broker.connect()

    setup = TradeSetup(
        symbol="BTCUSD",
        direction=Direction.LONG,
        entry_price=85000.0,
        stop_loss=84000.0,
        take_profit=87000.0,
        position_size=0.01,
    )
    await broker.place_order(setup)

    result = await broker.close_position("BTCUSD")
    assert isinstance(result, OrderResult)
    assert result.success is True

    positions = await broker.get_positions()
    assert len(positions) == 0


@pytest.mark.asyncio
async def test_paper_broker_close_nonexistent():
    from notas_lave.execution.paper import PaperBroker

    broker = PaperBroker(initial_balance=10000.0)
    await broker.connect()

    result = await broker.close_position("BTCUSD")
    assert result.success is False


@pytest.mark.asyncio
async def test_paper_broker_get_order_status():
    from notas_lave.execution.paper import PaperBroker

    broker = PaperBroker(initial_balance=10000.0)
    await broker.connect()

    setup = TradeSetup(
        symbol="BTCUSD",
        direction=Direction.LONG,
        entry_price=85000.0,
        stop_loss=84000.0,
        take_profit=87000.0,
        position_size=0.01,
    )
    order = await broker.place_order(setup)

    status = await broker.get_order_status(order.order_id)
    assert isinstance(status, OrderResult)
    assert status.success is True


@pytest.mark.asyncio
async def test_paper_broker_cancel_all_orders():
    from notas_lave.execution.paper import PaperBroker

    broker = PaperBroker(initial_balance=10000.0)
    await broker.connect()

    result = await broker.cancel_all_orders("BTCUSD")
    assert result is True


@pytest.mark.asyncio
async def test_paper_broker_multiple_positions():
    from notas_lave.execution.paper import PaperBroker

    broker = PaperBroker(initial_balance=10000.0)
    await broker.connect()

    for sym in ["BTCUSD", "ETHUSD"]:
        setup = TradeSetup(
            symbol=sym,
            direction=Direction.LONG,
            entry_price=1000.0,
            stop_loss=950.0,
            take_profit=1100.0,
            position_size=0.1,
        )
        await broker.place_order(setup)

    positions = await broker.get_positions()
    assert len(positions) == 2

    # Close one
    await broker.close_position("BTCUSD")
    positions = await broker.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "ETHUSD"


@pytest.mark.asyncio
async def test_paper_broker_disconnect():
    from notas_lave.execution.paper import PaperBroker

    broker = PaperBroker(initial_balance=10000.0)
    await broker.connect()
    assert broker.is_connected

    await broker.disconnect()
    assert not broker.is_connected


@pytest.mark.asyncio
async def test_paper_broker_registered():
    """PaperBroker should auto-register via @register_broker."""
    from notas_lave.execution.paper import PaperBroker
    from notas_lave.execution.registry import _REGISTRY

    assert "paper" in _REGISTRY
