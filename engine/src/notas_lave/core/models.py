"""Core domain models — the language of the trading system.

Pydantic models for ALL data that crosses system boundaries.
These are the canonical types imported by every module.

Rules:
- Pydantic at boundaries (API, config, DB serialization)
- All models are immutable (frozen=True or model_config frozen)
- No I/O, no side effects, no imports from adapters
"""

import math
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, model_validator


# -- Enums --


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class SignalStrength(str, Enum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    NONE = "NONE"


class MarketRegime(str, Enum):
    TRENDING = "TRENDING"
    RANGING = "RANGING"
    VOLATILE = "VOLATILE"
    QUIET = "QUIET"


class TradeStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


# -- Core Data Models --


class Candle(BaseModel):
    """One bar of OHLCV price data."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @model_validator(mode="after")
    def validate_ohlc(self) -> "Candle":
        for field_name in ("open", "high", "low", "close"):
            val = getattr(self, field_name)
            if math.isnan(val) or math.isinf(val):
                raise ValueError(f"Candle {field_name}={val} is NaN/Inf")
            if val <= 0:
                raise ValueError(f"Candle {field_name}={val} must be positive")
        if self.high < self.low:
            raise ValueError(f"Candle high ({self.high}) < low ({self.low})")
        if self.volume < 0:
            raise ValueError(f"Candle volume ({self.volume}) is negative")
        return self

    @property
    def body_size(self) -> float:
        return abs(self.close - self.open)

    @property
    def total_range(self) -> float:
        return self.high - self.low

    @property
    def body_ratio(self) -> float:
        if self.total_range == 0:
            return 0.0
        return self.body_size / self.total_range

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low


class Signal(BaseModel):
    """Output from a single strategy analysis."""

    strategy_name: str
    direction: Direction | None = None
    strength: SignalStrength = SignalStrength.NONE
    score: float = 0.0
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    metadata: dict = Field(default_factory=dict)
    reason: str = ""


class TradeSetup(BaseModel):
    """Complete trade setup ready for execution or risk check."""

    id: str = ""
    symbol: str
    direction: Direction
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size: float = 0.0
    risk_reward_ratio: float = 0.0
    confluence_score: float = 0.0
    claude_confidence: int = 0
    signals_snapshot: list[Signal] = Field(default_factory=list)
    regime: MarketRegime = MarketRegime.RANGING
    status: TradeStatus = TradeStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BalanceInfo(BaseModel):
    """Account balance from broker."""

    total: float
    available: float
    currency: str = "USD"


class ExchangePosition(BaseModel):
    """A position as reported by the broker."""

    symbol: str
    direction: Direction
    quantity: float
    entry_price: float
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    leverage: float = 1.0


class OrderResult(BaseModel):
    """Result of an order placement or query."""

    order_id: str = ""
    success: bool = False
    filled_price: float = 0.0
    filled_quantity: float = 0.0
    fee: float = 0.0
    error: str = ""


class OrderFlowSnapshot(BaseModel):
    """Point-in-time market microstructure data from order book, trades, and derivatives.

    This goes beyond OHLCV candles — it captures WHO is buying/selling, HOW aggressively,
    and what the derivatives market (funding, OI) says about crowd positioning.

    Used by strategies and the confluence scorer to make higher-accuracy decisions.
    """

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Order book imbalance (-1.0 = all sellers, +1.0 = all buyers)
    bid_ask_imbalance: float = 0.0
    spread_pct: float = 0.0
    bid_wall_prices: list[float] = Field(default_factory=list)
    ask_wall_prices: list[float] = Field(default_factory=list)
    book_depth_ratio: float = 1.0  # bid_vol / ask_vol for top N levels

    # Real delta from individual trades (NOT approximated from candles)
    real_delta: float = 0.0       # buy_vol - sell_vol
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    large_trade_count: int = 0    # trades > 10x average size
    large_trade_bias: int = 0     # net direction of large trades
    trade_intensity: float = 0.0  # trades per minute

    # Derivatives data
    funding_rate: float = 0.0           # current funding rate
    open_interest: float = 0.0          # total OI in USD
    oi_change_pct: float = 0.0          # OI change vs 1h ago

    # Derived sentiment
    sentiment: str = "neutral"          # extreme_greed/greed/neutral/fear/extreme_fear
    flow_direction: str = "neutral"     # buying/selling/neutral
    institutional_activity: bool = False
