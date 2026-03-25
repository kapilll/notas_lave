"""P&L integrity invariants — the tests that SHOULD have existed.

These verify that profitable trades are NEVER recorded as $0.
If any of these fail, we have a data-destroying bug.
"""

import pytest

from notas_lave.core.models import Direction, Signal, TradeSetup
from notas_lave.engine.event_bus import EventBus
from notas_lave.engine.pnl import PnLService
from notas_lave.execution.paper import PaperBroker
from notas_lave.journal.event_store import EventStore


def test_closed_trade_pnl_is_never_zero_when_price_moved():
    """If entry != exit, pnl must NOT be zero."""
    store = EventStore(":memory:")

    s = Signal(strategy_name="test", direction=Direction.LONG)
    tid = store.record_signal(s)
    store.record_open(tid, TradeSetup(
        symbol="BTCUSD", direction=Direction.LONG,
        entry_price=70000.0, stop_loss=69000.0,
        take_profit=72000.0, position_size=0.01,
    ))
    # Profitable close — price went up
    store.record_close(tid, exit_price=71000.0, reason="tp_hit", pnl=10.0)

    trade = store.get_closed_trades()[0]
    assert trade["pnl"] != 0, "Profitable trade recorded as $0 — data-destroying bug!"
    assert trade["pnl"] == 10.0


def test_reconcile_uses_real_pnl_not_zero():
    """When reconcile closes a trade, it must use real P&L."""
    store = EventStore(":memory:")

    s = Signal(strategy_name="test", direction=Direction.SHORT)
    tid = store.record_signal(s)
    store.record_open(tid, TradeSetup(
        symbol="BNBUSD", direction=Direction.SHORT,
        entry_price=640.0, stop_loss=660.0,
        take_profit=620.0, position_size=0.5,
    ))

    # Simulate reconcile close — position vanished from broker at price 625
    exit_price = 625.0
    entry = 640.0
    size = 0.5
    pnl = (entry - exit_price) * size  # SHORT: (640-625) * 0.5 = 7.5

    store.record_close(tid, exit_price=exit_price, reason="exchange_close", pnl=pnl)

    trade = store.get_closed_trades()[0]
    assert trade["pnl"] == 7.5, f"Expected $7.50 profit, got ${trade['pnl']}"
    assert trade["exit_price"] == 625.0
    assert trade["exit_reason"] == "exchange_close"


def test_pnl_sign_matches_direction():
    """LONG + price up = positive. SHORT + price down = positive."""
    store = EventStore(":memory:")

    # LONG trade, price went up — should be positive
    s1 = Signal(strategy_name="test", direction=Direction.LONG)
    t1 = store.record_signal(s1)
    store.record_open(t1, TradeSetup(
        symbol="BTCUSD", direction=Direction.LONG,
        entry_price=70000.0, stop_loss=69000.0,
        take_profit=72000.0, position_size=0.01,
    ))
    pnl1 = (71000.0 - 70000.0) * 0.01
    store.record_close(t1, exit_price=71000.0, reason="tp_hit", pnl=pnl1)

    # SHORT trade, price went down — should be positive
    s2 = Signal(strategy_name="test", direction=Direction.SHORT)
    t2 = store.record_signal(s2)
    store.record_open(t2, TradeSetup(
        symbol="ETHUSD", direction=Direction.SHORT,
        entry_price=2000.0, stop_loss=2100.0,
        take_profit=1900.0, position_size=1.0,
    ))
    pnl2 = (2000.0 - 1950.0) * 1.0
    store.record_close(t2, exit_price=1950.0, reason="tp_hit", pnl=pnl2)

    trades = store.get_closed_trades()
    assert trades[0]["pnl"] > 0, "SHORT + price down should be positive P&L"
    assert trades[1]["pnl"] > 0, "LONG + price up should be positive P&L"


@pytest.mark.asyncio
async def test_lab_engine_reconcile_preserves_pnl():
    """The actual reconcile code path must calculate real P&L."""
    from notas_lave.engine.lab import LabEngine

    broker = PaperBroker(initial_balance=10000.0)
    journal = EventStore(":memory:")
    bus = EventBus()
    pnl_svc = PnLService(original_deposit=10000.0)

    engine = LabEngine(broker=broker, journal=journal, bus=bus, pnl=pnl_svc)
    await broker.connect()

    # Manually create a journal entry (simulating a trade that was placed)
    s = Signal(strategy_name="test", direction=Direction.SHORT)
    tid = journal.record_signal(s)
    journal.record_open(tid, TradeSetup(
        symbol="BNBUSD", direction=Direction.SHORT,
        entry_price=640.0, stop_loss=660.0,
        take_profit=620.0, position_size=0.5,
    ))

    # Set last known price (simulating broker had this position at $625)
    engine._last_known_prices["BNBUSD"] = 625.0

    # Reconcile — BNBUSD not on broker (PaperBroker has no positions)
    # Should close with real P&L using last known price
    await engine._reconcile()

    trades = journal.get_closed_trades()
    assert len(trades) == 1
    assert trades[0]["pnl"] != 0, "Reconcile recorded pnl=0 — THIS IS THE BUG"
    assert trades[0]["pnl"] == pytest.approx(7.5, abs=0.01)  # (640-625)*0.5
    assert trades[0]["exit_reason"] == "exchange_close"
