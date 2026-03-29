"""Tests for v2 EventStore — append-only trade journal.

Every operation is an INSERT. Never UPDATE. State is rebuilt
by replaying events. This gives a complete audit trail.
"""

import pytest

from notas_lave.core.models import Direction, Signal, TradeSetup
from notas_lave.core.ports import ITradeJournal


def test_event_store_satisfies_ijournal():
    from notas_lave.journal.event_store import EventStore

    store = EventStore(":memory:")
    assert isinstance(store, ITradeJournal)


def test_record_signal():
    from notas_lave.journal.event_store import EventStore

    store = EventStore(":memory:")
    signal = Signal(
        strategy_name="ema_crossover",
        direction=Direction.LONG,
        score=85.0,
    )
    trade_id = store.record_signal(signal)
    assert isinstance(trade_id, int)
    assert trade_id > 0


def test_record_signal_increments_id():
    from notas_lave.journal.event_store import EventStore

    store = EventStore(":memory:")
    s = Signal(strategy_name="test")
    id1 = store.record_signal(s)
    id2 = store.record_signal(s)
    assert id2 > id1


def test_record_open():
    from notas_lave.journal.event_store import EventStore

    store = EventStore(":memory:")
    signal = Signal(strategy_name="ema_crossover", direction=Direction.LONG)
    trade_id = store.record_signal(signal)

    setup = TradeSetup(
        symbol="BTCUSD",
        direction=Direction.LONG,
        entry_price=85000.0,
        stop_loss=84000.0,
        take_profit=87000.0,
        position_size=0.01,
    )
    store.record_open(trade_id, setup)

    open_trades = store.get_open_trades()
    assert len(open_trades) == 1
    assert open_trades[0]["symbol"] == "BTCUSD"
    assert open_trades[0]["trade_id"] == trade_id


def test_record_close():
    from notas_lave.journal.event_store import EventStore

    store = EventStore(":memory:")
    signal = Signal(strategy_name="test", direction=Direction.LONG)
    trade_id = store.record_signal(signal)

    setup = TradeSetup(
        symbol="BTCUSD", direction=Direction.LONG,
        entry_price=85000.0, stop_loss=84000.0,
        take_profit=87000.0, position_size=0.01,
    )
    store.record_open(trade_id, setup)
    store.record_close(trade_id, exit_price=86000.0, reason="tp_hit", pnl=10.0)

    open_trades = store.get_open_trades()
    assert len(open_trades) == 0

    closed = store.get_closed_trades(limit=50)
    assert len(closed) == 1
    assert closed[0]["pnl"] == 10.0
    assert closed[0]["exit_reason"] == "tp_hit"


def test_record_grade():
    from notas_lave.journal.event_store import EventStore

    store = EventStore(":memory:")
    signal = Signal(strategy_name="test", direction=Direction.LONG)
    trade_id = store.record_signal(signal)

    setup = TradeSetup(
        symbol="BTCUSD", direction=Direction.LONG,
        entry_price=85000.0, stop_loss=84000.0,
        take_profit=87000.0, position_size=0.01,
    )
    store.record_open(trade_id, setup)
    store.record_close(trade_id, exit_price=86000.0, reason="tp_hit", pnl=10.0)
    store.record_grade(trade_id, grade="A", lesson="Good entry")

    closed = store.get_closed_trades(limit=50)
    assert closed[0]["outcome_grade"] == "A"
    assert closed[0]["lessons_learned"] == "Good entry"


def test_multiple_open_trades():
    from notas_lave.journal.event_store import EventStore

    store = EventStore(":memory:")

    for sym in ["BTCUSD", "ETHUSD", "SOLUSD"]:
        s = Signal(strategy_name="test", direction=Direction.LONG)
        tid = store.record_signal(s)
        setup = TradeSetup(
            symbol=sym, direction=Direction.LONG,
            entry_price=100.0, stop_loss=90.0,
            take_profit=110.0, position_size=1.0,
        )
        store.record_open(tid, setup)

    assert len(store.get_open_trades()) == 3

    # Close one
    store.record_close(1, exit_price=105.0, reason="tp_hit", pnl=5.0)
    assert len(store.get_open_trades()) == 2
    assert len(store.get_closed_trades()) == 1


def test_events_are_append_only():
    """The event table should only grow. count never decreases."""
    from notas_lave.journal.event_store import EventStore

    store = EventStore(":memory:")

    s = Signal(strategy_name="test", direction=Direction.LONG)
    tid = store.record_signal(s)
    count_after_signal = store.event_count()

    setup = TradeSetup(
        symbol="BTCUSD", direction=Direction.LONG,
        entry_price=100.0, stop_loss=90.0,
        take_profit=110.0, position_size=1.0,
    )
    store.record_open(tid, setup)
    count_after_open = store.event_count()

    store.record_close(tid, exit_price=105.0, reason="tp_hit", pnl=5.0)
    count_after_close = store.event_count()

    store.record_grade(tid, grade="B", lesson="OK trade")
    count_after_grade = store.event_count()

    assert count_after_signal < count_after_open
    assert count_after_open < count_after_close
    assert count_after_close < count_after_grade


def test_get_closed_trades_limit():
    from notas_lave.journal.event_store import EventStore

    store = EventStore(":memory:")

    for i in range(10):
        s = Signal(strategy_name="test")
        tid = store.record_signal(s)
        setup = TradeSetup(
            symbol="BTCUSD", direction=Direction.LONG,
            entry_price=100.0, stop_loss=90.0,
            take_profit=110.0, position_size=1.0,
        )
        store.record_open(tid, setup)
        store.record_close(tid, exit_price=105.0, reason="tp_hit", pnl=5.0)

    assert len(store.get_closed_trades(limit=5)) == 5
    assert len(store.get_closed_trades(limit=50)) == 10


def test_closed_trade_has_all_fields():
    from notas_lave.journal.event_store import EventStore

    store = EventStore(":memory:")
    s = Signal(strategy_name="ema", direction=Direction.SHORT, score=75.0)
    tid = store.record_signal(s)

    setup = TradeSetup(
        symbol="ETHUSD", direction=Direction.SHORT,
        entry_price=2000.0, stop_loss=2100.0,
        take_profit=1800.0, position_size=0.5,
    )
    store.record_open(tid, setup)
    store.record_close(tid, exit_price=1850.0, reason="tp_hit", pnl=75.0)
    store.record_grade(tid, grade="A", lesson="Clean short")

    trade = store.get_closed_trades()[0]
    assert trade["trade_id"] == tid
    assert trade["symbol"] == "ETHUSD"
    assert trade["direction"] == "SHORT"
    assert trade["entry_price"] == 2000.0
    assert trade["exit_price"] == 1850.0
    assert trade["pnl"] == 75.0
    assert trade["exit_reason"] == "tp_hit"
    assert trade["outcome_grade"] == "A"
    assert trade["lessons_learned"] == "Clean short"
