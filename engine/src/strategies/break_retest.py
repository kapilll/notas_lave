"""
Strategy #22: Break and Retest (Multi-Timeframe).

HOW IT WORKS:
- Identify a consolidation zone (price trapped in a range for 20+ candles)
- Wait for a CONVINCING breakout: body >= 70%, closes beyond + buffer, volume >= 1.5x
- Don't chase the breakout — wait for price to come BACK to the broken level
- Enter when price retests the broken level and prints an engulfing candle
- Confirm with 200 EMA in the direction of the breakout

WHY RETEST WORKS:
- Broken resistance becomes new support (and vice versa)
- The retest confirms the breakout was real, not a fake-out
- You get a MUCH tighter stop loss (just beyond the retested level)
- R:R is typically 1:2 to 1:3 because of the tight stop

THE PSYCHOLOGY:
- After a breakout, late traders chase → price overextends
- Smart money waits for the pullback to add to their position
- The retest is where institutions "reload" — you enter WITH them

BEST FOR: All instruments. Use 4H for structure, 5M/15M for entry.
AVOID: News events (breakouts during news are unreliable for retest).
"""

from ..data.models import Candle, Signal, Direction, SignalStrength
from .base import BaseStrategy
from .ema_crossover import compute_ema


class BreakRetestStrategy(BaseStrategy):
    """
    Break and Retest — enter on retest of broken consolidation level.

    Parameters:
    - consolidation_lookback: candles to search for consolidation (50)
    - min_consolidation_candles: minimum range candles to qualify (20)
    - breakout_body_ratio: minimum body % for breakout candle (0.7)
    - volume_multiplier: breakout volume must exceed this x average (1.5)
    - retest_proximity_pct: how close price must be to retested level (0.15%)
    """

    def __init__(
        self,
        consolidation_lookback: int = 50,
        min_consolidation_candles: int = 20,
        breakout_body_ratio: float = 0.7,
        volume_multiplier: float = 1.5,
        retest_proximity_pct: float = 0.0015,
    ):
        self.consolidation_lookback = consolidation_lookback
        self.min_consolidation_candles = min_consolidation_candles
        self.breakout_body_ratio = breakout_body_ratio
        self.volume_multiplier = volume_multiplier
        self.retest_proximity_pct = retest_proximity_pct

    @property
    def name(self) -> str:
        return "break_retest"

    @property
    def category(self) -> str:
        return "breakout"

    def _find_consolidation(self, candles: list[Candle]) -> tuple[float, float, int] | None:
        """
        Find the most recent consolidation zone.

        A consolidation is where price stays within a range for min_consolidation_candles.
        Returns (range_high, range_low, num_candles_in_range) or None.
        """
        lookback = candles[-self.consolidation_lookback:]
        if len(lookback) < self.min_consolidation_candles:
            return None

        # Use a rolling window to find the tightest range with enough candles
        best_range = None
        best_count = 0

        for start_idx in range(len(lookback) - self.min_consolidation_candles):
            window = lookback[start_idx:]
            initial_high = max(c.high for c in window[:self.min_consolidation_candles])
            initial_low = min(c.low for c in window[:self.min_consolidation_candles])
            initial_range = initial_high - initial_low
            range_pct = initial_range / initial_low if initial_low > 0 else 0

            # Range should be reasonably tight (< 2% for it to be consolidation)
            if range_pct > 0.02:
                continue

            # Count how many candles stay within this range
            count = 0
            for c in window:
                if c.high <= initial_high * 1.001 and c.low >= initial_low * 0.999:
                    count += 1
                elif count >= self.min_consolidation_candles:
                    break  # Range broken after consolidation formed

            if count >= self.min_consolidation_candles and count > best_count:
                best_count = count
                best_range = (initial_high, initial_low, count)

        return best_range

    def _is_engulfing(self, candle: Candle, prev_candle: Candle) -> str | None:
        """
        Check if current candle engulfs the previous candle.
        Returns 'bullish' or 'bearish' or None.
        """
        # Bullish engulfing: current green, body covers previous red body
        if (candle.is_bullish and not prev_candle.is_bullish and
                candle.close > prev_candle.open and candle.open < prev_candle.close):
            return "bullish"
        # Bearish engulfing: current red, body covers previous green body
        if (not candle.is_bullish and prev_candle.is_bullish and
                candle.close < prev_candle.open and candle.open > prev_candle.close):
            return "bearish"
        return None

    def analyze(self, candles: list[Candle], symbol: str = "") -> Signal:
        if len(candles) < self.consolidation_lookback + 20:
            return self._no_signal("Not enough candles for consolidation detection")

        current_price = candles[-1].close
        current_candle = candles[-1]
        prev_candle = candles[-2]

        # Find consolidation zone
        consolidation = self._find_consolidation(candles[:-10])  # Exclude recent candles
        if consolidation is None:
            return self._no_signal("No consolidation zone detected")

        range_high, range_low, consol_count = consolidation
        range_size = range_high - range_low
        proximity = current_price * self.retest_proximity_pct

        # Check if breakout has occurred in recent candles (last 10)
        recent = candles[-10:]
        avg_volume = sum(c.volume for c in candles[-30:]) / 30 if candles[-30:] else 0

        # Look for breakout candle
        broke_above = False
        broke_below = False
        for c in recent:
            if (c.close > range_high and
                    c.body_ratio >= self.breakout_body_ratio and
                    (avg_volume == 0 or c.volume >= avg_volume * self.volume_multiplier)):
                broke_above = True
            if (c.close < range_low and
                    c.body_ratio >= self.breakout_body_ratio and
                    (avg_volume == 0 or c.volume >= avg_volume * self.volume_multiplier)):
                broke_below = True

        if not broke_above and not broke_below:
            return self._no_signal(
                f"No breakout from consolidation ({range_low:.2f}-{range_high:.2f})"
            )

        # 200 EMA trend confirmation
        closes = [c.close for c in candles]
        ema200 = compute_ema(closes, 200) if len(closes) >= 202 else []
        ema200_now = ema200[-1] if ema200 else None

        # Check for engulfing pattern at retest level
        engulfing = self._is_engulfing(current_candle, prev_candle)

        # --- BULLISH: Broke above, retesting range_high as support ---
        if broke_above and abs(current_price - range_high) < proximity:
            # Retest confirmation: price came back to range_high and bounced
            if not current_candle.is_bullish:
                return self._no_signal("Retesting breakout level but no bullish candle")

            # EMA 200 trend alignment is MANDATORY — reject if breaking against trend
            if ema200_now is not None and current_price < ema200_now:
                return self._no_signal("Bullish breakout rejected: price below EMA 200")

            # ATR-based SL/TP — adapts to volatility instead of fixed range multiples
            atr = self.compute_atr(candles)
            if not atr:
                return self._no_signal("Not enough data for ATR")
            stop_loss = self.atr_stop_loss(current_price, atr, "long", 2.0)
            take_profit = self.atr_take_profit(current_price, atr, "long", 2.0, abs(current_price - stop_loss))

            score_base = 55
            if engulfing == "bullish":
                score_base += 10
            score_base += 5  # EMA confirmed (mandatory now)
            score = min(85, score_base + consol_count * 0.5)

            return Signal(
                strategy_name=self.name,
                direction=Direction.LONG,
                strength=SignalStrength.STRONG if engulfing else SignalStrength.MODERATE,
                score=score,
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "range_high": round(range_high, 2),
                    "range_low": round(range_low, 2),
                    "consolidation_candles": consol_count,
                    "engulfing": engulfing or "none",
                    "ema200_confirms": True,
                    "atr": round(atr, 2),
                },
                reason=f"Break & Retest: broke above {range_high:.2f} "
                       f"({consol_count}-candle consolidation), retesting as support."
                       f"{' Engulfing candle!' if engulfing else ''}",
            )

        # --- BEARISH: Broke below, retesting range_low as resistance ---
        if broke_below and abs(current_price - range_low) < proximity:
            if current_candle.is_bullish:
                return self._no_signal("Retesting breakout level but no bearish candle")

            # EMA 200 trend alignment is MANDATORY — reject if breaking against trend
            if ema200_now is not None and current_price > ema200_now:
                return self._no_signal("Bearish breakout rejected: price above EMA 200")

            # ATR-based SL/TP — adapts to volatility instead of fixed range multiples
            atr = self.compute_atr(candles)
            if not atr:
                return self._no_signal("Not enough data for ATR")
            stop_loss = self.atr_stop_loss(current_price, atr, "short", 2.0)
            take_profit = self.atr_take_profit(current_price, atr, "short", 2.0, abs(current_price - stop_loss))

            score_base = 55
            if engulfing == "bearish":
                score_base += 10
            score_base += 5  # EMA confirmed (mandatory now)
            score = min(85, score_base + consol_count * 0.5)

            return Signal(
                strategy_name=self.name,
                direction=Direction.SHORT,
                strength=SignalStrength.STRONG if engulfing else SignalStrength.MODERATE,
                score=score,
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "range_high": round(range_high, 2),
                    "range_low": round(range_low, 2),
                    "consolidation_candles": consol_count,
                    "engulfing": engulfing or "none",
                    "ema200_confirms": True,
                    "atr": round(atr, 2),
                },
                reason=f"Break & Retest: broke below {range_low:.2f} "
                       f"({consol_count}-candle consolidation), retesting as resistance."
                       f"{' Engulfing candle!' if engulfing else ''}",
            )

        return self._no_signal(
            f"Breakout occurred but price not retesting level yet. "
            f"Range: {range_low:.2f}-{range_high:.2f}"
        )
