"""Tests for v2 domain events — frozen dataclasses.

Events are immutable facts: "a trade was opened", "a signal was generated".
They must be frozen (no mutation after creation).
"""

from datetime import datetime, timezone

import pytest


def test_signal_generated_event():
    from notas_lave.core.events import SignalGenerated

    evt = SignalGenerated(
        strategy_name="ema_crossover",
        symbol="BTCUSD",
        direction="LONG",
        score=85.0,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert evt.strategy_name == "ema_crossover"
    assert evt.symbol == "BTCUSD"
    assert evt.direction == "LONG"
    assert evt.score == 85.0


def test_signal_generated_is_frozen():
    from notas_lave.core.events import SignalGenerated

    evt = SignalGenerated(
        strategy_name="ema_crossover",
        symbol="BTCUSD",
        direction="LONG",
        score=85.0,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(AttributeError):
        evt.score = 99.0


def test_trade_opened_event():
    from notas_lave.core.events import TradeOpened

    evt = TradeOpened(
        trade_id="t001",
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=85000.0,
        position_size=0.01,
        stop_loss=84000.0,
        take_profit=87000.0,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert evt.trade_id == "t001"
    assert evt.entry_price == 85000.0
    assert evt.position_size == 0.01


def test_trade_opened_is_frozen():
    from notas_lave.core.events import TradeOpened

    evt = TradeOpened(
        trade_id="t001",
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=85000.0,
        position_size=0.01,
        stop_loss=84000.0,
        take_profit=87000.0,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(AttributeError):
        evt.entry_price = 99999.0


def test_trade_closed_event():
    from notas_lave.core.events import TradeClosed

    evt = TradeClosed(
        trade_id="t001",
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=85000.0,
        exit_price=86000.0,
        pnl=10.0,
        reason="tp_hit",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert evt.pnl == 10.0
    assert evt.reason == "tp_hit"


def test_trade_closed_is_frozen():
    from notas_lave.core.events import TradeClosed

    evt = TradeClosed(
        trade_id="t001",
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=85000.0,
        exit_price=86000.0,
        pnl=10.0,
        reason="tp_hit",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(AttributeError):
        evt.pnl = 9999.0


def test_trade_graded_event():
    from notas_lave.core.events import TradeGraded

    evt = TradeGraded(
        trade_id="t001",
        grade="A",
        lesson="Good entry timing with confluence",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert evt.grade == "A"
    assert evt.lesson == "Good entry timing with confluence"


def test_trade_graded_is_frozen():
    from notas_lave.core.events import TradeGraded

    evt = TradeGraded(
        trade_id="t001",
        grade="A",
        lesson="Good entry",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(AttributeError):
        evt.grade = "F"


def test_balance_updated_event():
    from notas_lave.core.events import BalanceUpdated

    evt = BalanceUpdated(
        broker="binance",
        total=5100.0,
        available=4800.0,
        currency="USDT",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert evt.total == 5100.0
    assert evt.broker == "binance"
