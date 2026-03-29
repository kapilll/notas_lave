"""Broker reconciliation tests — NOT self-confirming.

These test that the reconciliation engine correctly detects:
- Orphaned broker positions (broker has it, journal doesn't)
- Ghost journal entries (journal says open, broker says no)
- Double-close prevention
- 2-tick confirmation requirement before closing
"""

import os
import tempfile

import pytest

from notas_lave.core.models import Direction, Signal, TradeSetup
from notas_lave.engine.event_bus import EventBus
from notas_lave.engine.leaderboard import StrategyLeaderboard
from notas_lave.engine.pnl import PnLService
from notas_lave.execution.paper import PaperBroker
from notas_lave.journal.event_store import EventStore


def _make_engine(broker=None, journal=None):
    """Create a LabEngine with sensible defaults for reconciliation tests."""
    from notas_lave.engine.lab import LabEngine
    broker = broker or PaperBroker(initial_balance=10000.0)
    journal = journal or EventStore(":memory:")
    bus = EventBus()
    pnl = PnLService(original_deposit=10000.0)
    engine = LabEngine(broker=broker, journal=journal, bus=bus, pnl=pnl)
    engine.leaderboard = StrategyLeaderboard(persist_path=os.path.join(
        tempfile.mkdtemp(), "test_leaderboard.json"))
    return engine, broker, journal


def _open_journal_trade(journal, symbol="BTCUSD", direction=Direction.LONG,
                        entry_price=70000.0, position_size=0.01):
    """Record a signal+open in the journal, return trade_id."""
    sig = Signal(strategy_name="test", direction=direction)
    tid = journal.record_signal(sig)
    journal.record_open(tid, TradeSetup(
        symbol=symbol, direction=direction,
        entry_price=entry_price, stop_loss=entry_price * 0.98,
        take_profit=entry_price * 1.03, position_size=position_size,
    ))
    return tid


@pytest.mark.asyncio
async def test_reconcile_detects_orphaned_broker_position(caplog):
    """Position on broker but NOT in journal → must detect and log warning."""
    engine, broker, journal = _make_engine()
    await broker.connect()

    # Place position directly on broker (bypassing journal)
    await broker.place_order(TradeSetup(
        symbol="ETHUSD", direction=Direction.LONG,
        entry_price=2000.0, stop_loss=1900.0,
        take_profit=2200.0, position_size=1.0,
    ))

    # Journal has no trades — broker has ETHUSD
    assert len(journal.get_open_trades()) == 0
    assert len(await broker.get_positions()) == 1

    with caplog.at_level("WARNING"):
        await engine._reconcile()

    assert any("ORPHANED" in msg and "ETHUSD" in msg for msg in caplog.messages), (
        "Reconcile must detect and log orphaned broker positions"
    )


@pytest.mark.asyncio
async def test_reconcile_detects_ghost_journal_entry():
    """Journal has open trade, broker doesn't → must close with REAL price."""
    engine, broker, journal = _make_engine()
    await broker.connect()

    # Create trade in journal only (broker has no positions)
    tid = _open_journal_trade(journal, symbol="SOLUSD",
                              direction=Direction.SHORT,
                              entry_price=150.0, position_size=5.0)

    # Set a last known price (simulating broker had it at some point)
    engine._last_known_prices["SOLUSD"] = 145.0

    # Miss 1/2 — should NOT close yet
    await engine._reconcile()
    assert len(journal.get_closed_trades()) == 0

    # Miss 2/2 — confirmed, should close
    await engine._reconcile()

    closed = journal.get_closed_trades()
    assert len(closed) == 1
    assert closed[0]["exit_price"] == 145.0, "Must use last known broker price, not entry"
    assert closed[0]["pnl"] != 0, "P&L must not be zero when price moved"
    # SHORT: (150 - 145) * 5.0 = 25.0
    assert closed[0]["pnl"] == pytest.approx(25.0, abs=0.01)
    assert closed[0]["exit_reason"] == "exchange_close"


@pytest.mark.asyncio
async def test_reconcile_doesnt_double_close():
    """Same trade reconciled twice → only 1 close event."""
    engine, broker, journal = _make_engine()
    await broker.connect()

    tid = _open_journal_trade(journal, symbol="BTCUSD",
                              entry_price=70000.0, position_size=0.01)
    engine._last_known_prices["BTCUSD"] = 71000.0

    # Two reconcile passes to trigger close (2-miss requirement)
    await engine._reconcile()
    await engine._reconcile()

    closed = journal.get_closed_trades()
    assert len(closed) == 1, "Should close exactly once"

    # Third reconcile — trade is already closed, nothing should happen
    await engine._reconcile()
    closed = journal.get_closed_trades()
    assert len(closed) == 1, "Should still be exactly 1 closed trade after extra reconcile"


@pytest.mark.asyncio
async def test_reconcile_requires_2_ticks_before_closing():
    """First miss → no close. Second miss → close. Verifies C4 safety."""
    engine, broker, journal = _make_engine()
    await broker.connect()

    tid = _open_journal_trade(journal, symbol="ETHUSD",
                              direction=Direction.LONG,
                              entry_price=2000.0, position_size=1.0)
    engine._last_known_prices["ETHUSD"] = 2100.0

    # First reconcile — miss 1/2
    await engine._reconcile()
    assert len(journal.get_closed_trades()) == 0, "Must NOT close on first miss"
    assert len(journal.get_open_trades()) == 1, "Trade must remain open"

    # Second reconcile — miss 2/2, confirmed
    await engine._reconcile()
    closed = journal.get_closed_trades()
    assert len(closed) == 1, "Must close after 2 consecutive misses"
    assert closed[0]["pnl"] == pytest.approx(100.0, abs=0.01)  # (2100-2000)*1.0


@pytest.mark.asyncio
async def test_reconcile_resets_miss_counter_when_position_returns():
    """If position reappears on broker, miss counter resets."""
    engine, broker, journal = _make_engine()
    await broker.connect()

    tid = _open_journal_trade(journal, symbol="BTCUSD",
                              entry_price=70000.0, position_size=0.01)
    engine._last_known_prices["BTCUSD"] = 71000.0

    # Miss 1/2
    await engine._reconcile()
    assert len(journal.get_closed_trades()) == 0

    # Position reappears on broker (transient API glitch resolved)
    await broker.place_order(TradeSetup(
        symbol="BTCUSD", direction=Direction.LONG,
        entry_price=70000.0, stop_loss=69000.0,
        take_profit=72000.0, position_size=0.01,
    ))

    # Reconcile again — position is back, counter should reset
    await engine._reconcile()
    assert len(journal.get_closed_trades()) == 0, "Should NOT close when position reappears"

    # Remove broker position again — should need 2 fresh misses
    broker._positions.clear()

    await engine._reconcile()  # miss 1/2 (fresh counter)
    assert len(journal.get_closed_trades()) == 0, "Need fresh 2 misses after reset"

    await engine._reconcile()  # miss 2/2
    assert len(journal.get_closed_trades()) == 1
