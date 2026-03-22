"""
Strategy #8: Triple EMA Crossover (9/21/50) with 200 EMA Filter.

HOW IT WORKS:
- Uses 4 Exponential Moving Averages: 9 (fast), 21 (medium), 50 (slow), 200 (trend filter)
- BUY when: 9 EMA crosses ABOVE 21 EMA, AND all EMAs are stacked bullish (9 > 21 > 50 > 200)
- SELL when: 9 EMA crosses BELOW 21 EMA, AND all EMAs are stacked bearish (9 < 21 < 50 < 200)
- The 200 EMA acts as a trend filter — we only trade in the direction of the big trend

WHY IT WORKS:
- Moving averages smooth out noise and show the underlying trend
- When fast MA crosses slow MA, it means momentum is shifting
- Requiring ALL EMAs to be aligned filters out choppy/ranging markets
- This is one of the simplest strategies to automate with clear rules

BEST FOR: Trending markets (Gold, BTC during strong moves)
AVOID: Ranging/sideways markets (will whipsaw and lose money)
"""

from ..data.models import Candle, Signal, Direction, SignalStrength
from .base import BaseStrategy
import numpy as np


def compute_ema(prices: list[float], period: int) -> list[float]:
    """
    Compute Exponential Moving Average.

    EMA gives more weight to recent prices than SMA (Simple Moving Average).
    This makes it react faster to price changes — important for scalping.

    The multiplier determines how much weight goes to the latest price:
    multiplier = 2 / (period + 1)
    For EMA(9): multiplier = 0.2 (20% weight on latest price)
    For EMA(200): multiplier = 0.01 (1% weight — very slow, stable)
    """
    if len(prices) < period:
        return []

    ema_values = []
    # First EMA value = simple average of first `period` prices
    sma = sum(prices[:period]) / period
    ema_values.append(sma)

    # Multiplier: how much weight the latest price gets
    multiplier = 2.0 / (period + 1)

    # Each subsequent EMA = (Price - Previous EMA) * multiplier + Previous EMA
    for i in range(period, len(prices)):
        ema = (prices[i] - ema_values[-1]) * multiplier + ema_values[-1]
        ema_values.append(ema)

    return ema_values


class EMAcrossoverStrategy(BaseStrategy):
    """
    Triple EMA Crossover with trend filter.

    Parameters:
    - fast_period: 9 (reacts quickly to price changes)
    - medium_period: 21 (confirms short-term trend)
    - slow_period: 50 (confirms medium-term trend)
    - trend_period: 200 (the big picture trend filter)
    - min_separation_pct: minimum % gap between EMAs to avoid choppy signals
    """

    def __init__(
        self,
        fast_period: int = 9,
        medium_period: int = 21,
        slow_period: int = 50,
        trend_period: int = 200,
        min_separation_pct: float = 0.001,  # 0.1% minimum gap between EMAs
    ):
        self.fast_period = fast_period
        self.medium_period = medium_period
        self.slow_period = slow_period
        self.trend_period = trend_period
        self.min_separation_pct = min_separation_pct

    @property
    def name(self) -> str:
        return "ema_crossover"

    @property
    def category(self) -> str:
        return "scalping"

    def analyze(self, candles: list[Candle], symbol: str = "") -> Signal:
        # Need at least 200+1 candles for EMA(200) + crossover detection
        if len(candles) < self.trend_period + 2:
            return self._no_signal("Not enough candles for EMA calculation")

        closes = [c.close for c in candles]

        # Compute all 4 EMAs
        ema_fast = compute_ema(closes, self.fast_period)
        ema_medium = compute_ema(closes, self.medium_period)
        ema_slow = compute_ema(closes, self.slow_period)
        ema_trend = compute_ema(closes, self.trend_period)

        if not ema_fast or not ema_medium or not ema_slow or not ema_trend:
            return self._no_signal("EMA calculation failed")

        # Get current and previous values (for crossover detection)
        # We need the LATEST value and the one before it
        fast_now = ema_fast[-1]
        fast_prev = ema_fast[-2]
        medium_now = ema_medium[-1]
        medium_prev = ema_medium[-2]
        slow_now = ema_slow[-1]
        trend_now = ema_trend[-1]
        current_price = closes[-1]

        # Check for crossover: fast EMA crosses medium EMA
        # Bullish cross: fast was below medium, now above
        bullish_cross = fast_prev <= medium_prev and fast_now > medium_now
        # Bearish cross: fast was above medium, now below
        bearish_cross = fast_prev >= medium_prev and fast_now < medium_now

        if not bullish_cross and not bearish_cross:
            return self._no_signal("No EMA crossover detected")

        # Check EMA alignment (stacking)
        # Bullish stack: 9 > 21 > 50 > 200 (all moving averages agree on uptrend)
        bullish_stack = fast_now > medium_now > slow_now > trend_now
        # Bearish stack: 9 < 21 < 50 < 200
        bearish_stack = fast_now < medium_now < slow_now < trend_now

        # Check minimum separation to avoid choppy signals
        # If EMAs are too close together, the market is ranging — avoid
        separation = abs(fast_now - medium_now) / current_price
        if separation < self.min_separation_pct:
            return self._no_signal(
                f"EMA separation too small ({separation:.4f} < {self.min_separation_pct})"
            )

        # Volume confirmation — reject if volume is below 1.5x 20-period average
        if not self.check_volume(candles):
            return self._no_signal("Volume too low")

        # Compute ATR for dynamic SL/TP
        atr = self.compute_atr(candles)
        if not atr:
            return self._no_signal("Not enough data for ATR")

        # Determine signal
        if bullish_cross and bullish_stack:
            direction = Direction.LONG
            # ATR-based stop loss and take profit (1.5 ATR risk, 2:1 R:R)
            stop_loss = self.atr_stop_loss(current_price, atr, "LONG", 1.5)
            take_profit = self.atr_take_profit(current_price, atr, "LONG", 2.0, abs(current_price - stop_loss))
            strength = SignalStrength.STRONG if separation > 0.003 else SignalStrength.MODERATE
            score = min(85, 50 + separation * 10000)  # Higher separation = higher score

        elif bearish_cross and bearish_stack:
            direction = Direction.SHORT
            # ATR-based stop loss and take profit (1.5 ATR risk, 2:1 R:R)
            stop_loss = self.atr_stop_loss(current_price, atr, "SHORT", 1.5)
            take_profit = self.atr_take_profit(current_price, atr, "SHORT", 2.0, abs(current_price - stop_loss))
            strength = SignalStrength.STRONG if separation > 0.003 else SignalStrength.MODERATE
            score = min(85, 50 + separation * 10000)

        else:
            # Crossover happened but EMAs not fully aligned — weak signal
            return self._no_signal("EMA crossover without full alignment")

        return Signal(
            strategy_name=self.name,
            direction=direction,
            strength=strength,
            score=score,
            entry_price=current_price,
            stop_loss=round(stop_loss, 2),
            take_profit=round(take_profit, 2),
            metadata={
                "ema_fast": round(fast_now, 2),
                "ema_medium": round(medium_now, 2),
                "ema_slow": round(slow_now, 2),
                "ema_trend": round(trend_now, 2),
                "separation_pct": round(separation * 100, 4),
            },
            reason=f"EMA {self.fast_period}/{self.medium_period} {'bullish' if direction == Direction.LONG else 'bearish'} cross with full stack alignment",
        )
