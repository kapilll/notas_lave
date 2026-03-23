"""Tests for v2 LabEngine — slim lab with DI.

The lab engine takes all dependencies via constructor.
No globals, no use_db(), no direct broker imports.
"""

import pytest

from notas_lave.core.models import Direction, Signal, TradeSetup
from notas_lave.engine.event_bus import EventBus
from notas_lave.engine.pnl import PnLService
from notas_lave.execution.paper import PaperBroker
from notas_lave.journal.event_store import EventStore


def _make_lab():
    from notas_lave.engine.lab import LabEngine

    broker = PaperBroker(initial_balance=5000.0)
    journal = EventStore(":memory:")
    bus = EventBus()
    pnl = PnLService(original_deposit=5000.0)

    engine = LabEngine(broker=broker, journal=journal, bus=bus, pnl=pnl)
    return engine


@pytest.mark.asyncio
async def test_lab_engine_creation():
    engine = _make_lab()
    assert engine is not None
    assert engine.is_running is False


@pytest.mark.asyncio
async def test_lab_engine_open_trade():
    engine = _make_lab()
    await engine.broker.connect()

    setup = TradeSetup(
        symbol="BTCUSD",
        direction=Direction.LONG,
        entry_price=85000.0,
        stop_loss=84000.0,
        take_profit=87000.0,
        position_size=0.01,
    )
    trade_id = await engine.execute_trade(setup)
    assert trade_id > 0

    # Should be in journal as open
    open_trades = engine.journal.get_open_trades()
    assert len(open_trades) == 1
    assert open_trades[0]["symbol"] == "BTCUSD"

    # Should be on broker
    positions = await engine.broker.get_positions()
    assert len(positions) == 1


@pytest.mark.asyncio
async def test_lab_engine_close_trade():
    engine = _make_lab()
    await engine.broker.connect()

    setup = TradeSetup(
        symbol="BTCUSD",
        direction=Direction.LONG,
        entry_price=85000.0,
        stop_loss=84000.0,
        take_profit=87000.0,
        position_size=0.01,
    )
    trade_id = await engine.execute_trade(setup)
    await engine.close_trade(trade_id, exit_price=86000.0, reason="tp_hit")

    # Should be closed in journal
    assert len(engine.journal.get_open_trades()) == 0
    closed = engine.journal.get_closed_trades()
    assert len(closed) == 1
    assert closed[0]["exit_reason"] == "tp_hit"


@pytest.mark.asyncio
async def test_lab_engine_emits_events():
    from notas_lave.core.events import TradeOpened, TradeClosed

    engine = _make_lab()
    await engine.broker.connect()

    opened_events = []
    closed_events = []

    engine.bus.subscribe(TradeOpened, lambda e: opened_events.append(e))
    engine.bus.subscribe(TradeClosed, lambda e: closed_events.append(e))

    setup = TradeSetup(
        symbol="ETHUSD",
        direction=Direction.SHORT,
        entry_price=2000.0,
        stop_loss=2100.0,
        take_profit=1800.0,
        position_size=0.5,
    )
    trade_id = await engine.execute_trade(setup)
    assert len(opened_events) == 1
    assert opened_events[0].symbol == "ETHUSD"

    await engine.close_trade(trade_id, exit_price=1850.0, reason="tp_hit")
    assert len(closed_events) == 1
    assert closed_events[0].pnl == pytest.approx(75.0, abs=1.0)


@pytest.mark.asyncio
async def test_lab_engine_status():
    engine = _make_lab()
    await engine.broker.connect()

    status = await engine.get_status()
    assert status["open_trades"] == 0
    assert status["balance"] == 5000.0

    setup = TradeSetup(
        symbol="BTCUSD", direction=Direction.LONG,
        entry_price=85000.0, stop_loss=84000.0,
        take_profit=87000.0, position_size=0.01,
    )
    await engine.execute_trade(setup)

    status = await engine.get_status()
    assert status["open_trades"] == 1


@pytest.mark.asyncio
async def test_lab_engine_pnl():
    engine = _make_lab()
    pnl = engine.get_pnl(current_balance=5200.0)
    assert pnl.pnl == 200.0
    assert pnl.pnl_pct == pytest.approx(4.0)
