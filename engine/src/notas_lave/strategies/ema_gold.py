"""
Strategy #7: EMA 200/1000 Gold Scalping.

HOW IT WORKS:
- Uses two long EMAs: 200 (medium-term trend) and 1000 (macro trend)
- When EMA 200 > EMA 1000: confirmed uptrend — only look for LONG entries
- When EMA 200 < EMA 1000: confirmed downtrend — only look for SHORT entries
- Wait for price to pull back to the EMA 200, then enter on a bounce

THE KEY INSIGHT:
- EMA 200 acts as "institutional support/resistance" — big players defend this level
- EMA 1000 is the "mega trend" filter — ensures we're on the right side of history
- Pullbacks to EMA 200 are the BEST risk/reward entries in a confirmed trend

BEST FOR: Gold (specifically designed for it), Silver. Works on 1M/5M/15M.
AVOID: When EMAs are flat/tangled — market is ranging, no edge.

NOTE: While designed for Gold, this strategy also works for other trending instruments.
The EMA 200/1000 combination captures major institutional levels on any asset.
"""

from ..data.models import Candle, Signal, Direction, SignalStrength
from .base import BaseStrategy
from .ema_crossover import compute_ema


class EMAGoldStrategy(BaseStrategy):
    """
    EMA 200/1000 pullback entry — designed for Gold scalping.

    Parameters:
    - ema_fast: 200 (institutional support/resistance)
    - ema_slow: 1000 (macro trend direction)
    - pullback_pct: How close price must be to EMA 200 (default 0.1%)
    - min_trend_sep_pct: Minimum gap between EMA 200 and 1000 (0.3%)
    """

    def __init__(
        self,
        ema_fast: int = 200,
        ema_slow: int = 1000,
        pullback_pct: float = 0.001,      # 0.1% — price within this % of EMA 200
        min_trend_sep_pct: float = 0.003,  # 0.3% — EMAs must be this far apart
    ):
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.pullback_pct = pullback_pct
        self.min_trend_sep_pct = min_trend_sep_pct

    @property
    def name(self) -> str:
        return "ema_gold"

    @property
    def category(self) -> str:
        return "scalping"

    def analyze(self, candles: list[Candle], symbol: str = "") -> Signal:
        # Need 1000+ candles for EMA(1000) — if fewer, degrade to EMA(200) only
        min_required = self.ema_slow + 2 if len(candles) >= self.ema_slow + 2 else self.ema_fast + 2
        if len(candles) < self.ema_fast + 2:
            return self._no_signal("Not enough candles for EMA 200")

        closes = [c.close for c in candles]
        current_price = closes[-1]
        current_candle = candles[-1]

        # Volume confirmation — reject if volume is below 1.5x 20-period average
        if not self.check_volume(candles):
            return self._no_signal("Volume too low")

        # Compute ATR for dynamic SL/TP and proximity threshold
        atr = self.compute_atr(candles)
        if not atr:
            return self._no_signal("Not enough data for ATR")

        # Compute EMAs
        ema200 = compute_ema(closes, self.ema_fast)
        if not ema200 or len(ema200) < 3:
            return self._no_signal("EMA 200 calculation failed")

        ema200_now = ema200[-1]
        ema200_prev = ema200[-2]

        # EMA 1000: use if we have enough data, otherwise use EMA 200 slope as filter
        has_ema1000 = len(candles) >= self.ema_slow + 2
        if has_ema1000:
            ema1000 = compute_ema(closes, self.ema_slow)
            if not ema1000:
                return self._no_signal("EMA 1000 calculation failed")
            ema1000_now = ema1000[-1]
        else:
            # Fallback: use EMA 200 slope direction as trend filter
            ema1000_now = None

        # Determine trend direction
        if has_ema1000 and ema1000_now is not None:
            # Full mode: EMA 200 vs EMA 1000
            trend_sep = abs(ema200_now - ema1000_now) / current_price
            if trend_sep < self.min_trend_sep_pct:
                return self._no_signal(
                    f"EMA 200/1000 too close ({trend_sep*100:.2f}%). No clear trend."
                )
            is_uptrend = ema200_now > ema1000_now
        else:
            # Fallback: EMA 200 slope over last 20 candles
            if len(ema200) < 20:
                return self._no_signal("Not enough EMA 200 history for slope")
            slope = (ema200[-1] - ema200[-20]) / ema200[-20]
            if abs(slope) < 0.001:
                return self._no_signal("EMA 200 is flat — no trend")
            is_uptrend = slope > 0
            trend_sep = abs(slope)

        # Check pullback to EMA 200 — ATR-relative proximity instead of fixed percentage
        distance_to_ema = abs(current_price - ema200_now)
        proximity = atr * 0.5  # Half ATR proximity threshold
        is_near_ema200 = distance_to_ema < proximity

        if not is_near_ema200:
            return self._no_signal(
                f"Price not at EMA 200 (distance: {distance_to_ema:.2f}, threshold: {proximity:.2f})"
            )

        # Check for bounce candle in trend direction
        if is_uptrend:
            # Price pulled back to EMA 200 from above, need bullish bounce
            if not current_candle.is_bullish:
                return self._no_signal("Pullback to EMA 200 but no bullish bounce yet")

            # Confirm price was above EMA and came down to it (pullback, not breakdown)
            if current_price < ema200_now * (1 - self.pullback_pct * 2):
                return self._no_signal("Price broke below EMA 200 — not a pullback")

            # ATR-based SL/TP: 2x ATR for pullback entries (wider for trend continuation)
            stop_loss = self.atr_stop_loss(current_price, atr, "LONG", 2.0)
            risk = abs(current_price - stop_loss)
            take_profit = self.atr_take_profit(current_price, atr, "LONG", 2.0, risk)

            # Score: closer to EMA = higher score, trend separation adds confidence
            closeness_score = max(0, (proximity - distance_to_ema) / proximity * 20)
            score = min(80, 50 + closeness_score + trend_sep * 3000)

            return Signal(
                strategy_name=self.name,
                direction=Direction.LONG,
                strength=SignalStrength.STRONG if trend_sep > 0.005 else SignalStrength.MODERATE,
                score=score,
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "ema200": round(ema200_now, 2),
                    "ema1000": round(ema1000_now, 2) if ema1000_now else "N/A",
                    "distance_to_ema": round(distance_to_ema, 2),
                    "trend_sep_pct": round(trend_sep * 100, 3),
                    "trend": "UP",
                },
                reason=f"EMA 200 pullback bounce ({ema200_now:.2f}). "
                       f"Uptrend confirmed by {'EMA 1000' if has_ema1000 else 'EMA slope'}.",
            )

        else:
            # Downtrend: price pulled back UP to EMA 200, need bearish rejection
            if current_candle.is_bullish:
                return self._no_signal("Pullback to EMA 200 but no bearish rejection yet")

            if current_price > ema200_now * (1 + self.pullback_pct * 2):
                return self._no_signal("Price broke above EMA 200 — not a pullback")

            # ATR-based SL/TP: 2x ATR for pullback entries (wider for trend continuation)
            stop_loss = self.atr_stop_loss(current_price, atr, "SHORT", 2.0)
            risk = abs(current_price - stop_loss)
            take_profit = self.atr_take_profit(current_price, atr, "SHORT", 2.0, risk)

            closeness_score = max(0, (proximity - distance_to_ema) / proximity * 20)
            score = min(80, 50 + closeness_score + trend_sep * 3000)

            return Signal(
                strategy_name=self.name,
                direction=Direction.SHORT,
                strength=SignalStrength.STRONG if trend_sep > 0.005 else SignalStrength.MODERATE,
                score=score,
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "ema200": round(ema200_now, 2),
                    "ema1000": round(ema1000_now, 2) if ema1000_now else "N/A",
                    "distance_to_ema": round(distance_to_ema, 2),
                    "trend_sep_pct": round(trend_sep * 100, 3),
                    "trend": "DOWN",
                },
                reason=f"EMA 200 pullback rejection ({ema200_now:.2f}). "
                       f"Downtrend confirmed by {'EMA 1000' if has_ema1000 else 'EMA slope'}.",
            )
