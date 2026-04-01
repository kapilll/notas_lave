"""Tests for v2 domain events — frozen dataclasses.

Events are immutable facts: "a trade was opened", "a signal was generated".
They must be frozen (no mutation after creation).
"""

from datetime import datetime, timezone

import pytest


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


