"""
Core data models used across the entire trading engine.

These are the building blocks — every module speaks this language.
Candle = one bar of price data (OHLCV).
Signal = one strategy's output ("buy here, stop there").
TradeSetup = the final recommendation after confluence scoring.
"""

from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


# -- Enums --

class Direction(str, Enum):
    """Trade direction. LONG = buy expecting price to go up."""
    LONG = "LONG"
    SHORT = "SHORT"


class SignalStrength(str, Enum):
    """How strong is this strategy's signal?"""
    STRONG = "STRONG"      # High confidence, clear pattern
    MODERATE = "MODERATE"  # Decent setup, some confirmation
    WEAK = "WEAK"          # Pattern exists but not ideal
    NONE = "NONE"          # No signal detected


class MarketRegime(str, Enum):
    """What type of market are we in? Determines strategy weights."""
    TRENDING = "TRENDING"    # Clear direction, strong moves
    RANGING = "RANGING"      # Sideways, mean-reverting
    VOLATILE = "VOLATILE"    # Big swings, uncertain direction
    QUIET = "QUIET"          # Low volatility, small moves


class TradeStatus(str, Enum):
    """Lifecycle of a trade."""
    PENDING = "PENDING"      # Signal generated, not yet executed
    OPEN = "OPEN"            # Position is active
    CLOSED = "CLOSED"        # Position closed (profit or loss)
    CANCELLED = "CANCELLED"  # Blocked by risk manager or user


# -- Core Data Models --

class Candle(BaseModel):
    """
    One bar of price data. This is the fundamental unit of market data.
    Every strategy receives a list of Candles and returns Signals.
    """
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def body_size(self) -> float:
        """Size of the candle body (absolute). Big body = strong conviction."""
        return abs(self.close - self.open)

    @property
    def total_range(self) -> float:
        """Full range from high to low. Includes wicks."""
        return self.high - self.low

    @property
    def body_ratio(self) -> float:
        """Body as percentage of total range. >0.7 = strong momentum candle."""
        if self.total_range == 0:
            return 0.0
        return self.body_size / self.total_range

    @property
    def is_bullish(self) -> bool:
        """Green candle — close above open."""
        return self.close > self.open

    @property
    def upper_wick(self) -> float:
        """Upper shadow/wick size. Big upper wick = rejection from highs."""
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        """Lower shadow/wick size. Big lower wick = rejection from lows (buying pressure)."""
        return min(self.open, self.close) - self.low


class Signal(BaseModel):
    """
    Output from a single strategy. Each strategy scans candles and produces
    a Signal telling us what it sees.

    Example: RSI strategy might say "LONG, MODERATE strength, RSI at 28.4"
    """
    strategy_name: str                          # e.g., "rsi_divergence"
    direction: Direction | None = None          # LONG, SHORT, or None (no signal)
    strength: SignalStrength = SignalStrength.NONE
    score: float = 0.0                          # 0-100 score for this strategy
    entry_price: float | None = None            # Suggested entry
    stop_loss: float | None = None              # Suggested stop loss
    take_profit: float | None = None            # Suggested take profit
    metadata: dict = Field(default_factory=dict) # Strategy-specific data (RSI value, EMA levels, etc.)
    reason: str = ""                            # Human-readable explanation


class ConfluenceResult(BaseModel):
    """
    The combined result after all strategies are scored and weighted.
    This is what gets sent to Claude for final evaluation.
    """
    symbol: str
    timeframe: str
    direction: Direction | None = None
    composite_score: float = 0.0       # 0-10 weighted score
    signals: list[Signal] = Field(default_factory=list)
    regime: MarketRegime = MarketRegime.RANGING
    agreeing_strategies: int = 0       # How many strategies agree on direction
    total_strategies: int = 0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ClaudeDecision(BaseModel):
    """
    Claude's structured response. Forced JSON schema — no free-form hallucination.
    Claude can ONLY output these fields. Everything is validated.
    """
    action: str = "SKIP"          # "BUY", "SELL", or "SKIP"
    confidence: int = 0           # 1-10 scale
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    reasoning: str = ""           # For logging — not used in decisions
    risk_warnings: list[str] = Field(default_factory=list)


class TradeSetup(BaseModel):
    """
    A complete trade setup ready for execution (or rejection by risk manager).
    This is the final output before a trade happens.
    """
    id: str = ""
    symbol: str
    timeframe: str
    direction: Direction
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size: float = 0.0
    risk_reward_ratio: float = 0.0
    confluence_score: float = 0.0
    claude_confidence: int = 0
    claude_reasoning: str = ""
    signals_snapshot: list[Signal] = Field(default_factory=list)
    regime: MarketRegime = MarketRegime.RANGING
    status: TradeStatus = TradeStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TradeRecord(BaseModel):
    """
    A completed trade stored in the journal. Contains everything needed
    for the learning engine to analyze what worked and what didn't.
    """
    id: str
    setup: TradeSetup
    actual_entry: float = 0.0
    actual_exit: float = 0.0
    actual_pnl: float = 0.0
    actual_pnl_pct: float = 0.0
    duration_seconds: int = 0
    max_favorable_excursion: float = 0.0   # Best unrealized P&L during trade
    max_adverse_excursion: float = 0.0     # Worst unrealized P&L during trade
    exit_reason: str = ""                  # "tp_hit", "sl_hit", "manual", "time"
    outcome_grade: str = ""                # A/B/C/D/F (assigned by learning engine)
    lessons_learned: str = ""              # Claude's post-trade analysis
    opened_at: datetime = Field(default_factory=datetime.utcnow)
    closed_at: datetime | None = None
