"""Tests for v2 core models — Pydantic domain objects.

TDD: These tests are written FIRST. They define the contract
that core/models.py must satisfy.
"""

import math
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError


# --- Candle ---

def test_candle_valid():
    from notas_lave.core.models import Candle

    c = Candle(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        open=100.0, high=110.0, low=90.0, close=105.0, volume=1000.0,
    )
    assert c.open == 100.0
    assert c.high == 110.0
    assert c.close == 105.0
    assert c.volume == 1000.0


def test_candle_rejects_nan():
    from notas_lave.core.models import Candle

    with pytest.raises(ValidationError):
        Candle(
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            open=float("nan"), high=110.0, low=90.0, close=105.0,
        )


def test_candle_rejects_negative_price():
    from notas_lave.core.models import Candle

    with pytest.raises(ValidationError):
        Candle(
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            open=-1.0, high=110.0, low=90.0, close=105.0,
        )


def test_candle_rejects_high_below_low():
    from notas_lave.core.models import Candle

    with pytest.raises(ValidationError):
        Candle(
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            open=100.0, high=80.0, low=90.0, close=105.0,
        )


def test_candle_properties():
    from notas_lave.core.models import Candle

    c = Candle(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        open=100.0, high=110.0, low=90.0, close=105.0,
    )
    assert c.body_size == 5.0
    assert c.total_range == 20.0
    assert c.body_ratio == 0.25
    assert c.is_bullish is True


# --- Direction / Enums ---

def test_direction_enum():
    from notas_lave.core.models import Direction

    assert Direction.LONG == "LONG"
    assert Direction.SHORT == "SHORT"


def test_signal_strength_enum():
    from notas_lave.core.models import SignalStrength

    assert SignalStrength.STRONG == "STRONG"
    assert SignalStrength.NONE == "NONE"


def test_trade_status_enum():
    from notas_lave.core.models import TradeStatus

    assert TradeStatus.OPEN == "OPEN"
    assert TradeStatus.CLOSED == "CLOSED"


def test_market_regime_enum():
    from notas_lave.core.models import MarketRegime

    assert MarketRegime.TRENDING == "TRENDING"
    assert MarketRegime.RANGING == "RANGING"


# --- Signal ---

def test_signal_defaults():
    from notas_lave.core.models import Signal, SignalStrength

    s = Signal(strategy_name="test_strat")
    assert s.direction is None
    assert s.strength == SignalStrength.NONE
    assert s.score == 0.0
    assert s.metadata == {}


def test_signal_with_values():
    from notas_lave.core.models import Signal, Direction, SignalStrength

    s = Signal(
        strategy_name="ema_crossover",
        direction=Direction.LONG,
        strength=SignalStrength.STRONG,
        score=85.0,
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        reason="EMA 9 crossed above EMA 21",
    )
    assert s.direction == Direction.LONG
    assert s.score == 85.0


# --- TradeSetup ---

def test_trade_setup_creation():
    from notas_lave.core.models import TradeSetup, Direction

    setup = TradeSetup(
        symbol="BTCUSD",
        direction=Direction.LONG,
        entry_price=85000.0,
        stop_loss=84000.0,
        take_profit=87000.0,
        position_size=0.01,
    )
    assert setup.symbol == "BTCUSD"
    assert setup.direction == Direction.LONG
    assert setup.position_size == 0.01


def test_trade_setup_risk_reward():
    from notas_lave.core.models import TradeSetup, Direction

    setup = TradeSetup(
        symbol="BTCUSD",
        direction=Direction.LONG,
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=115.0,
        risk_reward_ratio=3.0,
    )
    assert setup.risk_reward_ratio == 3.0


# --- BalanceInfo ---

def test_balance_info():
    from notas_lave.core.models import BalanceInfo

    b = BalanceInfo(total=5000.0, available=4500.0, currency="USDT")
    assert b.total == 5000.0
    assert b.available == 4500.0
    assert b.currency == "USDT"


# --- ExchangePosition ---

def test_exchange_position():
    from notas_lave.core.models import ExchangePosition, Direction

    p = ExchangePosition(
        symbol="BTCUSDT",
        direction=Direction.LONG,
        quantity=0.01,
        entry_price=85000.0,
        current_price=86000.0,
        unrealized_pnl=10.0,
    )
    assert p.symbol == "BTCUSDT"
    assert p.unrealized_pnl == 10.0


# --- OrderResult ---

def test_order_result_filled():
    from notas_lave.core.models import OrderResult

    r = OrderResult(
        order_id="abc123",
        success=True,
        filled_price=85000.0,
        filled_quantity=0.01,
        fee=0.34,
    )
    assert r.success is True
    assert r.filled_price == 85000.0


def test_order_result_rejected():
    from notas_lave.core.models import OrderResult

    r = OrderResult(
        order_id="",
        success=False,
        error="Insufficient margin",
    )
    assert r.success is False
    assert r.error == "Insufficient margin"
