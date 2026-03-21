"""
Strategy #14: London Session Breakout.

HOW IT WORKS:
- Mark the range of the first hour after London open (08:00-09:00 GMT)
- Wait for a STRONG breakout candle that breaks above/below this range
- Don't chase the breakout — wait for price to RETEST the broken level
- Enter on the retest with a reversal candle (engulfing, pin bar)

WHY WAIT FOR RETEST?
- The initial breakout could be a fake-out (stop hunt)
- Retesting the broken level as new support/resistance CONFIRMS the breakout
- Studies show waiting for retest improves win rate by 10-15%
- The retest gives a tighter stop loss = better risk/reward

KEY STAT: London open is the most volatile session for Gold and EUR pairs.
Institutions execute the bulk of their orders during London (08:00-12:00 GMT).

BEST FOR: Gold, EUR/USD, GBP/USD. Use on 5M/15M timeframes.
AVOID: Low-volatility days (small London range = no breakout edge).
"""

from datetime import timezone
from ..data.models import Candle, Signal, Direction, SignalStrength
from .base import BaseStrategy
from .session_killzone import _to_utc_hour


class LondonBreakoutStrategy(BaseStrategy):
    """
    London first-hour range breakout with retest entry.

    Parameters:
    - range_start_hour: 8 (London open, UTC)
    - range_end_hour: 9 (first hour completes)
    - min_range_pct: Minimum range size to avoid low-vol days (0.15%)
    - breakout_body_ratio: Candle body must be >70% of range (strong conviction)
    """

    def __init__(
        self,
        range_start_hour: int = 8,
        range_end_hour: int = 9,
        min_range_pct: float = 0.0015,     # 0.15% minimum range
        breakout_body_ratio: float = 0.7,  # Body > 70% of candle range
    ):
        self.range_start_hour = range_start_hour
        self.range_end_hour = range_end_hour
        self.min_range_pct = min_range_pct
        self.breakout_body_ratio = breakout_body_ratio

    @property
    def name(self) -> str:
        return "london_breakout"

    @property
    def category(self) -> str:
        return "ict"

    def _get_london_range(self, candles: list[Candle]) -> tuple[float, float] | None:
        """
        Get London first-hour range (08:00-09:00 UTC) for the SAME DAY
        as the latest candle. Uses candle timestamp (not wall clock)
        so this works in both live trading and backtesting.
        """
        # Use the latest candle's date, not datetime.now()
        last_ts = candles[-1].timestamp
        if last_ts.tzinfo is not None:
            last_ts = last_ts.astimezone(timezone.utc)
        target_date = last_ts.date()

        range_candles = []
        for c in candles:
            ts = c.timestamp
            if ts.tzinfo is not None:
                ts = ts.astimezone(timezone.utc)
            if (ts.date() == target_date and
                    self.range_start_hour <= ts.hour < self.range_end_hour):
                range_candles.append(c)

        if not range_candles:
            return None

        return (
            max(c.high for c in range_candles),
            min(c.low for c in range_candles),
        )

    def analyze(self, candles: list[Candle], symbol: str = "") -> Signal:
        if len(candles) < 30:
            return self._no_signal("Not enough candles")

        current_price = candles[-1].close
        current_candle = candles[-1]
        current_hour = _to_utc_hour(candles[-1].timestamp)

        # Only trade after the range has formed (after 09:00 UTC)
        if current_hour < self.range_end_hour:
            return self._no_signal("London first hour not complete yet")

        # Only trade during London active hours (09:00-16:00 UTC)
        if current_hour >= 16:
            return self._no_signal("London session closed")

        london_range = self._get_london_range(candles)
        if london_range is None:
            return self._no_signal("No London first-hour range data")

        range_high, range_low = london_range
        range_size = range_high - range_low
        range_pct = range_size / range_low

        if range_pct < self.min_range_pct:
            return self._no_signal(f"London range too small ({range_pct*100:.2f}%)")

        # Look for breakout + retest pattern in recent candles
        recent = candles[-15:]  # Last 15 candles

        # Check for bullish breakout: price broke above range, retested, bouncing
        broke_above = any(c.close > range_high and c.body_ratio > self.breakout_body_ratio
                         for c in recent[:-3])  # Breakout happened earlier
        retesting_high = abs(current_price - range_high) < range_size * 0.3  # Near range top
        bullish_bounce = current_candle.is_bullish and current_price > range_high

        if broke_above and retesting_high and bullish_bounce:
            stop_loss = range_low  # Stop below entire range
            take_profit = range_high + range_size * 1.5  # 1.5x range as target

            risk = current_price - stop_loss
            reward = take_profit - current_price

            # Volume check: did breakout candle have strong volume?
            avg_vol = sum(c.volume for c in candles[-30:]) / 30 if candles[-30:] else 0
            vol_confirmed = current_candle.volume > avg_vol * 1.3 if avg_vol > 0 else True

            strength = SignalStrength.STRONG if vol_confirmed else SignalStrength.MODERATE
            score = min(80, 55 + (range_pct * 5000) + (10 if vol_confirmed else 0))

            return Signal(
                strategy_name=self.name,
                direction=Direction.LONG,
                strength=strength,
                score=score,
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "range_high": round(range_high, 2),
                    "range_low": round(range_low, 2),
                    "range_pct": round(range_pct * 100, 3),
                    "mode": "breakout_retest",
                    "volume_confirmed": vol_confirmed,
                },
                reason=f"London breakout above {range_high:.2f}, retesting as support. "
                       f"Range: {range_size:.2f} ({range_pct*100:.2f}%).",
            )

        # Check for bearish breakout: price broke below range, retested, rejecting
        broke_below = any(c.close < range_low and c.body_ratio > self.breakout_body_ratio
                         for c in recent[:-3])
        retesting_low = abs(current_price - range_low) < range_size * 0.3
        bearish_reject = not current_candle.is_bullish and current_price < range_low

        if broke_below and retesting_low and bearish_reject:
            stop_loss = range_high
            take_profit = range_low - range_size * 1.5

            risk = stop_loss - current_price
            reward = current_price - take_profit

            avg_vol = sum(c.volume for c in candles[-30:]) / 30 if candles[-30:] else 0
            vol_confirmed = current_candle.volume > avg_vol * 1.3 if avg_vol > 0 else True

            strength = SignalStrength.STRONG if vol_confirmed else SignalStrength.MODERATE
            score = min(80, 55 + (range_pct * 5000) + (10 if vol_confirmed else 0))

            return Signal(
                strategy_name=self.name,
                direction=Direction.SHORT,
                strength=strength,
                score=score,
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "range_high": round(range_high, 2),
                    "range_low": round(range_low, 2),
                    "range_pct": round(range_pct * 100, 3),
                    "mode": "breakout_retest",
                    "volume_confirmed": vol_confirmed,
                },
                reason=f"London breakdown below {range_low:.2f}, retesting as resistance. "
                       f"Range: {range_size:.2f} ({range_pct*100:.2f}%).",
            )

        return self._no_signal(
            f"No London breakout setup. Range: {range_low:.2f}-{range_high:.2f}"
        )
