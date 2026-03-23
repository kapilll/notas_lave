"""Tests for v2 projections — rebuild analytics from events.

Projections are read-only views computed from the event store.
They can be rebuilt at any time from the append-only events.
"""

import pytest

from notas_lave.core.models import Direction, Signal, TradeSetup


def _make_store():
    from notas_lave.journal.event_store import EventStore
    return EventStore(":memory:")


def _open_trade(store, symbol="BTCUSD", direction=Direction.LONG,
                entry=85000.0, sl=84000.0, tp=87000.0, size=0.01):
    s = Signal(strategy_name="test", direction=direction)
    tid = store.record_signal(s)
    setup = TradeSetup(
        symbol=symbol, direction=direction,
        entry_price=entry, stop_loss=sl,
        take_profit=tp, position_size=size,
    )
    store.record_open(tid, setup)
    return tid


def test_trade_summary_empty():
    from notas_lave.journal.projections import trade_summary

    store = _make_store()
    summary = trade_summary(store)
    assert summary["total_trades"] == 0
    assert summary["open_trades"] == 0
    assert summary["win_rate"] == 0.0


def test_trade_summary_with_trades():
    from notas_lave.journal.projections import trade_summary

    store = _make_store()

    # 3 winners
    for _ in range(3):
        tid = _open_trade(store)
        store.record_close(tid, exit_price=86000.0, reason="tp_hit", pnl=10.0)

    # 2 losers
    for _ in range(2):
        tid = _open_trade(store)
        store.record_close(tid, exit_price=84000.0, reason="sl_hit", pnl=-10.0)

    # 1 still open
    _open_trade(store)

    summary = trade_summary(store)
    assert summary["total_trades"] == 5
    assert summary["wins"] == 3
    assert summary["losses"] == 2
    assert summary["win_rate"] == pytest.approx(60.0)
    assert summary["total_pnl"] == pytest.approx(10.0)
    assert summary["open_trades"] == 1


def test_replay_produces_same_state():
    """Key invariant: replaying events from the same store produces identical state."""
    from notas_lave.journal.projections import trade_summary

    store = _make_store()

    tid1 = _open_trade(store, symbol="BTCUSD")
    store.record_close(tid1, exit_price=86000.0, reason="tp_hit", pnl=10.0)
    store.record_grade(tid1, grade="A", lesson="Good")

    tid2 = _open_trade(store, symbol="ETHUSD")
    store.record_close(tid2, exit_price=1900.0, reason="sl_hit", pnl=-5.0)

    _open_trade(store, symbol="SOLUSD")

    # First read
    summary1 = trade_summary(store)
    open1 = store.get_open_trades()
    closed1 = store.get_closed_trades()

    # Second read (same store, same events)
    summary2 = trade_summary(store)
    open2 = store.get_open_trades()
    closed2 = store.get_closed_trades()

    assert summary1 == summary2
    assert len(open1) == len(open2)
    assert len(closed1) == len(closed2)


def test_strategy_performance():
    from notas_lave.journal.projections import strategy_performance
    from notas_lave.journal.event_store import EventStore

    store = EventStore(":memory:")

    # EMA crossover: 2 wins, 1 loss
    for pnl in [10.0, 15.0, -5.0]:
        s = Signal(strategy_name="ema_crossover", direction=Direction.LONG, score=80.0)
        tid = store.record_signal(s)
        setup = TradeSetup(
            symbol="BTCUSD", direction=Direction.LONG,
            entry_price=100.0, stop_loss=90.0,
            take_profit=110.0, position_size=1.0,
        )
        store.record_open(tid, setup)
        store.record_close(tid, exit_price=110.0 if pnl > 0 else 90.0,
                           reason="tp_hit" if pnl > 0 else "sl_hit", pnl=pnl)

    perf = strategy_performance(store)
    assert "ema_crossover" in perf
    assert perf["ema_crossover"]["wins"] == 2
    assert perf["ema_crossover"]["losses"] == 1
    assert perf["ema_crossover"]["total_pnl"] == pytest.approx(20.0)


def test_get_trade_by_id():
    from notas_lave.journal.projections import get_trade_by_id

    store = _make_store()
    tid = _open_trade(store, symbol="ETHUSD")
    store.record_close(tid, exit_price=2100.0, reason="tp_hit", pnl=50.0)
    store.record_grade(tid, grade="B", lesson="Decent trade")

    trade = get_trade_by_id(store, tid)
    assert trade is not None
    assert trade["symbol"] == "ETHUSD"
    assert trade["pnl"] == 50.0
    assert trade["grade"] == "B"


def test_get_trade_by_id_not_found():
    from notas_lave.journal.projections import get_trade_by_id

    store = _make_store()
    trade = get_trade_by_id(store, 9999)
    assert trade is None
