"""Domain events — immutable facts about what happened.

All events are frozen dataclasses. Once created, they cannot be modified.
This prevents handlers from corrupting shared event data.

Usage:
    await bus.publish(TradeClosed(trade_id="t001", ...))
    # Subscribers react independently
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SignalGenerated:
    strategy_name: str
    symbol: str
    direction: str
    score: float
    timestamp: datetime


@dataclass(frozen=True)
class TradeOpened:
    trade_id: str
    symbol: str
    direction: str
    entry_price: float
    position_size: float
    stop_loss: float
    take_profit: float
    timestamp: datetime


@dataclass(frozen=True)
class TradeClosed:
    trade_id: str
    symbol: str
    direction: str
    entry_price: float
    exit_price: float
    pnl: float
    reason: str
    timestamp: datetime


@dataclass(frozen=True)
class TradeGraded:
    trade_id: str
    grade: str
    lesson: str
    timestamp: datetime


@dataclass(frozen=True)
class BalanceUpdated:
    broker: str
    total: float
    available: float
    currency: str
    timestamp: datetime
