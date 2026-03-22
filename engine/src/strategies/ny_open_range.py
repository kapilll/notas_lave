"""
Strategy #15: New York Open Range Breakout.

HOW IT WORKS:
- Mark the price range from 9:26-9:30 AM EST (13:26-13:30 UTC)
- This 4-minute window is the "pre-market squeeze" before NY opens
- Look for tight, overlapping candles (consolidation) during this period
- When the first 5M candle after 9:30 breaks the range → ENTER

WHY 9:26-9:30?
- Institutional algorithms queue orders just before the NY open
- The pre-open range captures the "loaded spring" of pending orders
- The 9:30 open triggers a cascade of executions
- This creates predictable, high-momentum moves

GOLDEN HOUR: 9:30-10:30 AM EST is when 60%+ of daily volume occurs.
Most of the day's range is established in this window.

BEST FOR: Gold (extremely effective), indices, BTC. Use 5M timeframe.
AVOID: Light volume days, holidays, when range is too wide (>0.3%).
"""

from datetime import timezone
from ..data.models import Candle, Signal, Direction, SignalStrength
from .base import BaseStrategy
from .session_killzone import _to_utc_hour


class NYOpenRangeStrategy(BaseStrategy):
    """
    NY Open Range breakout (pre-market squeeze at 9:26-9:30 EST).

    Parameters:
    - range_start_hour/min: 13:26 UTC (9:26 EST)
    - range_end_hour/min: 13:30 UTC (9:30 EST)
    - min_range_pct: Minimum range to avoid tiny ranges (0.05%)
    - max_range_pct: Maximum range — too wide = no edge (0.3%)
    """

    def __init__(
        self,
        min_range_pct: float = 0.0005,   # 0.05% min range
        max_range_pct: float = 0.003,    # 0.3% max range
    ):
        self.min_range_pct = min_range_pct
        self.max_range_pct = max_range_pct
        # NY pre-open range: 13:26-13:30 UTC (9:26-9:30 EST)
        self.range_start_utc = (13, 26)
        self.range_end_utc = (13, 30)

    @property
    def name(self) -> str:
        return "ny_open_range"

    @property
    def category(self) -> str:
        return "ict"

    def _get_ny_range(self, candles: list[Candle]) -> tuple[float, float] | None:
        """
        Get NY pre-open range (13:26-13:30 UTC) for the SAME DAY
        as the latest candle. Uses candle timestamp (not wall clock)
        so this works in both live trading and backtesting.
        """
        last_ts = candles[-1].timestamp
        if last_ts.tzinfo is not None:
            last_ts = last_ts.astimezone(timezone.utc)
        today = last_ts.date()

        range_candles = []
        for c in candles:
            ts = c.timestamp
            if ts.tzinfo is not None:
                ts = ts.astimezone(timezone.utc)

            if ts.date() != today:
                continue

            # Check if candle falls in 13:26-13:30 UTC window
            candle_minutes = ts.hour * 60 + ts.minute
            start_minutes = self.range_start_utc[0] * 60 + self.range_start_utc[1]
            end_minutes = self.range_end_utc[0] * 60 + self.range_end_utc[1]

            if start_minutes <= candle_minutes < end_minutes:
                range_candles.append(c)

        if not range_candles:
            return None

        return (
            max(c.high for c in range_candles),
            min(c.low for c in range_candles),
        )

    def analyze(self, candles: list[Candle], symbol: str = "") -> Signal:
        if len(candles) < 20:
            return self._no_signal("Not enough candles")

        current_candle = candles[-1]
        current_price = current_candle.close

        # Get current time in UTC
        ts = current_candle.timestamp
        if ts.tzinfo is not None:
            ts = ts.astimezone(timezone.utc)

        current_minutes = ts.hour * 60 + ts.minute
        range_end_minutes = self.range_end_utc[0] * 60 + self.range_end_utc[1]

        # Only trade after range has formed (after 13:30 UTC / 9:30 EST)
        if current_minutes < range_end_minutes:
            return self._no_signal("NY pre-open range not complete yet")

        # Golden hour: 13:30-14:30 UTC (9:30-10:30 EST)
        if current_minutes > 14 * 60 + 30:
            return self._no_signal("Past golden hour (10:30 EST)")

        ny_range = self._get_ny_range(candles)
        if ny_range is None:
            return self._no_signal("No NY pre-open range data available")

        range_high, range_low = ny_range
        range_size = range_high - range_low
        range_pct = range_size / range_low if range_low > 0 else 0

        if range_pct < self.min_range_pct:
            return self._no_signal(f"NY range too small ({range_pct*100:.3f}%)")

        if range_pct > self.max_range_pct:
            return self._no_signal(f"NY range too wide ({range_pct*100:.3f}%) — no edge")

        # Minimum range relative to ATR — avoid trading noise
        atr = self.compute_atr(candles)
        if atr and range_size < atr * 0.3:
            return self._no_signal("Pre-open range too small")

        # Volume confirmation — NY open should have above-average volume (2x)
        if not self.check_volume(candles, multiplier=2.0):
            return self._no_signal("NY open needs strong volume")

        # --- BULLISH BREAKOUT: Price breaks above range ---
        if current_price > range_high and current_candle.is_bullish:
            # Strong breakout: body > 60% of candle range
            if current_candle.body_ratio < 0.6:
                return self._no_signal("Breakout candle weak (body ratio < 60%)")

            stop_loss = range_low  # Stop below entire range
            risk = current_price - stop_loss
            take_profit = current_price + range_size * 2.0  # 2x range height target

            # Score: smaller range = more compressed = more explosive breakout
            compression_bonus = max(0, (self.max_range_pct - range_pct) / self.max_range_pct * 15)
            score = min(80, 55 + compression_bonus + current_candle.body_ratio * 10)

            return Signal(
                strategy_name=self.name,
                direction=Direction.LONG,
                strength=SignalStrength.STRONG,
                score=score,
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "range_high": round(range_high, 2),
                    "range_low": round(range_low, 2),
                    "range_pct": round(range_pct * 100, 3),
                    "body_ratio": round(current_candle.body_ratio, 2),
                    "session": "ny_open",
                },
                reason=f"NY Open Range bullish breakout above {range_high:.2f}. "
                       f"Range: {range_size:.2f} ({range_pct*100:.3f}%). Golden hour.",
            )

        # --- BEARISH BREAKOUT: Price breaks below range ---
        if current_price < range_low and not current_candle.is_bullish:
            if current_candle.body_ratio < 0.6:
                return self._no_signal("Breakout candle weak (body ratio < 60%)")

            stop_loss = range_high
            risk = stop_loss - current_price
            take_profit = current_price - range_size * 2.0

            compression_bonus = max(0, (self.max_range_pct - range_pct) / self.max_range_pct * 15)
            score = min(80, 55 + compression_bonus + current_candle.body_ratio * 10)

            return Signal(
                strategy_name=self.name,
                direction=Direction.SHORT,
                strength=SignalStrength.STRONG,
                score=score,
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "range_high": round(range_high, 2),
                    "range_low": round(range_low, 2),
                    "range_pct": round(range_pct * 100, 3),
                    "body_ratio": round(current_candle.body_ratio, 2),
                    "session": "ny_open",
                },
                reason=f"NY Open Range bearish breakout below {range_low:.2f}. "
                       f"Range: {range_size:.2f} ({range_pct*100:.3f}%). Golden hour.",
            )

        return self._no_signal(
            f"Price inside NY range ({range_low:.2f}-{range_high:.2f}). Waiting for breakout."
        )
