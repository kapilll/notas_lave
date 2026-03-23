"""
Strategy #18: Camarilla Pivot Points.

HOW IT WORKS:
- Camarilla levels are calculated from yesterday's High, Low, Close
- They create 4 support levels (S1-S4) and 4 resistance levels (R1-R4)
- S3/R3 are the BEST reversal zones — price bounces off these ~70% of the time
- S4/R4 are breakout zones — if price blows through, momentum is very strong

RANGE MODE (most common, 70-80% of days):
- If price opens between S3 and R3, trade mean reversion
- Long at S3 (support bounce), target central pivot or R1
- Short at R3 (resistance rejection), target central pivot or S1

BREAKOUT MODE (20-30% of days):
- If price breaks above R4 with conviction → strong bullish breakout, go long
- If price breaks below S4 with conviction → strong bearish breakout, go short

WHY IT WORKS:
- Camarilla levels are self-fulfilling — institutional algorithms use them
- S3/R3 are statistically the most respected intraday levels
- They work especially well in range-bound days (which are most days)

BEST FOR: Intraday scalping, Gold, Forex. First 2-3 hours of session.
AVOID: News events (levels get blown through with no respect).
"""

from ..data.models import Candle, Signal, Direction, SignalStrength
from .base import BaseStrategy


def compute_camarilla_levels(
    prev_high: float, prev_low: float, prev_close: float
) -> dict[str, float]:
    """
    Calculate Camarilla pivot levels from previous day's H/L/C.

    The Camarilla formula uses multipliers of the previous range:
    - S3/R3: 1.1/12 of range (primary reversal zones)
    - S4/R4: 1.1/6 of range (breakout zones — 2x wider)
    - Central pivot: traditional (H+L+C)/3
    """
    range_val = prev_high - prev_low
    pivot = (prev_high + prev_low + prev_close) / 3.0

    return {
        "r4": prev_close + range_val * 1.1 / 2.0,   # Breakout buy above here
        "r3": prev_close + range_val * 1.1 / 4.0,   # Resistance — short here
        "r2": prev_close + range_val * 1.1 / 6.0,
        "r1": prev_close + range_val * 1.1 / 12.0,
        "pivot": pivot,
        "s1": prev_close - range_val * 1.1 / 12.0,
        "s2": prev_close - range_val * 1.1 / 6.0,
        "s3": prev_close - range_val * 1.1 / 4.0,   # Support — long here
        "s4": prev_close - range_val * 1.1 / 2.0,   # Breakout sell below here
    }


class CamarillaPivotsStrategy(BaseStrategy):
    """
    Camarilla Pivot Points — range reversal at S3/R3, breakout at S4/R4.

    Parameters:
    - proximity_pct: How close price must be to a level to trigger (default 0.1%)
    - breakout_buffer_pct: How far beyond R4/S4 for breakout confirmation (0.05%)
    """

    def __init__(
        self,
        proximity_pct: float = 0.001,       # 0.1% proximity to level
        breakout_buffer_pct: float = 0.0005, # 0.05% beyond R4/S4
    ):
        self.proximity_pct = proximity_pct
        self.breakout_buffer_pct = breakout_buffer_pct

    @property
    def name(self) -> str:
        return "camarilla_pivots"

    @property
    def category(self) -> str:
        return "scalping"

    def _get_previous_day_hlc(self, candles: list[Candle]) -> tuple[float, float, float] | None:
        """
        Extract previous day's High, Low, Close from candle data.

        We find the most recent full day of data that isn't today,
        then take the H/L/C from that day.
        """
        if len(candles) < 20:
            return None

        # Get today's date from latest candle
        today = candles[-1].timestamp.date()

        # Collect previous day candles (the day before today)
        prev_day_candles = []
        for c in reversed(candles):
            candle_date = c.timestamp.date()
            if candle_date < today:
                if not prev_day_candles or prev_day_candles[0].timestamp.date() == candle_date:
                    prev_day_candles.append(c)
                else:
                    break  # Reached an even older day

        if not prev_day_candles:
            return None

        prev_high = max(c.high for c in prev_day_candles)
        prev_low = min(c.low for c in prev_day_candles)
        # Close = the close of the last candle of that day (most recent by time)
        prev_close = prev_day_candles[0].close  # reversed order, so [0] is latest

        return prev_high, prev_low, prev_close

    def analyze(self, candles: list[Candle], symbol: str = "") -> Signal:
        if len(candles) < 50:
            return self._no_signal("Not enough candles for Camarilla calculation")

        prev_hlc = self._get_previous_day_hlc(candles)
        if prev_hlc is None:
            return self._no_signal("Cannot determine previous day H/L/C")

        prev_high, prev_low, prev_close = prev_hlc
        levels = compute_camarilla_levels(prev_high, prev_low, prev_close)

        current_price = candles[-1].close
        current_candle = candles[-1]
        proximity = current_price * self.proximity_pct

        # Volume confirmation — reject if volume is below 1.5x 20-period average
        if not self.check_volume(candles):
            return self._no_signal("Volume too low")

        # --- BREAKOUT MODE: Price beyond R4 or S4 ---
        r4_break = current_price > levels["r4"] + current_price * self.breakout_buffer_pct
        s4_break = current_price < levels["s4"] - current_price * self.breakout_buffer_pct

        if r4_break and current_candle.is_bullish:
            # Strong bullish breakout above R4
            stop_loss = levels["r3"]  # Stop at R3
            risk = current_price - stop_loss
            take_profit = current_price + risk * 2.0

            # ATR sanity check — if SL is too wide, pivot levels may be invalid
            atr = self.compute_atr(candles)
            if atr and risk > atr * 3:
                return self._no_signal("SL too wide — pivots may be invalid")

            return Signal(
                strategy_name=self.name,
                direction=Direction.LONG,
                strength=SignalStrength.STRONG,
                score=min(80, 60 + (current_price - levels["r4"]) / current_price * 10000),
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "mode": "breakout",
                    "r4": round(levels["r4"], 2),
                    "r3": round(levels["r3"], 2),
                    "pivot": round(levels["pivot"], 2),
                },
                reason=f"Camarilla breakout above R4 ({levels['r4']:.2f}). Strong bullish momentum.",
            )

        if s4_break and not current_candle.is_bullish:
            # Strong bearish breakout below S4
            stop_loss = levels["s3"]
            risk = stop_loss - current_price
            take_profit = current_price - risk * 2.0

            # ATR sanity check — if SL is too wide, pivot levels may be invalid
            atr = self.compute_atr(candles)
            if atr and risk > atr * 3:
                return self._no_signal("SL too wide — pivots may be invalid")

            return Signal(
                strategy_name=self.name,
                direction=Direction.SHORT,
                strength=SignalStrength.STRONG,
                score=min(80, 60 + (levels["s4"] - current_price) / current_price * 10000),
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "mode": "breakout",
                    "s4": round(levels["s4"], 2),
                    "s3": round(levels["s3"], 2),
                    "pivot": round(levels["pivot"], 2),
                },
                reason=f"Camarilla breakout below S4 ({levels['s4']:.2f}). Strong bearish momentum.",
            )

        # --- RANGE MODE: Reversal at S3 or R3 ---
        # Long at S3: price near S3 and showing a bullish rejection candle
        near_s3 = abs(current_price - levels["s3"]) < proximity
        if near_s3 and current_candle.is_bullish and current_price > levels["s4"]:
            # Bullish bounce from S3 support
            stop_loss = levels["s4"]  # Stop at S4
            take_profit = levels["pivot"]  # Target central pivot

            risk = current_price - stop_loss
            reward = take_profit - current_price
            if risk <= 0 or reward <= 0:
                return self._no_signal("Invalid risk/reward at S3")

            # ATR sanity check — if SL is too wide, pivot levels may be invalid
            atr = self.compute_atr(candles)
            if atr and risk > atr * 3:
                return self._no_signal("SL too wide — pivots may be invalid")

            return Signal(
                strategy_name=self.name,
                direction=Direction.LONG,
                strength=SignalStrength.MODERATE,
                score=min(75, 55 + (levels["s3"] - current_price + proximity) / proximity * 10),
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "mode": "range_reversal",
                    "s3": round(levels["s3"], 2),
                    "s4": round(levels["s4"], 2),
                    "pivot": round(levels["pivot"], 2),
                    "r3": round(levels["r3"], 2),
                },
                reason=f"Camarilla S3 bounce ({levels['s3']:.2f}). Range mode — targeting pivot.",
            )

        # Short at R3: price near R3 and showing a bearish rejection candle
        near_r3 = abs(current_price - levels["r3"]) < proximity
        if near_r3 and not current_candle.is_bullish and current_price < levels["r4"]:
            # Bearish rejection from R3 resistance
            stop_loss = levels["r4"]
            take_profit = levels["pivot"]

            risk = stop_loss - current_price
            reward = current_price - take_profit
            if risk <= 0 or reward <= 0:
                return self._no_signal("Invalid risk/reward at R3")

            # ATR sanity check — if SL is too wide, pivot levels may be invalid
            atr = self.compute_atr(candles)
            if atr and risk > atr * 3:
                return self._no_signal("SL too wide — pivots may be invalid")

            return Signal(
                strategy_name=self.name,
                direction=Direction.SHORT,
                strength=SignalStrength.MODERATE,
                score=min(75, 55 + (current_price - levels["r3"] + proximity) / proximity * 10),
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "mode": "range_reversal",
                    "r3": round(levels["r3"], 2),
                    "r4": round(levels["r4"], 2),
                    "pivot": round(levels["pivot"], 2),
                    "s3": round(levels["s3"], 2),
                },
                reason=f"Camarilla R3 rejection ({levels['r3']:.2f}). Range mode — targeting pivot.",
            )

        return self._no_signal(
            f"Price ({current_price:.2f}) not at key Camarilla level. "
            f"S3={levels['s3']:.2f}, R3={levels['r3']:.2f}"
        )
