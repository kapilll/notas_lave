"""
Strategy #9: Momentum Breakout + ATR.

HOW IT WORKS:
- Identify a key support/resistance level (recent swing high/low)
- Wait for a POWERFUL candle that breaks through with:
  - Range >= 1.5x ATR(14) — strong candle = institutional conviction
  - Body > 70% of total range — mostly body, small wicks = no hesitation
  - Close beyond level + 0.5x ATR buffer — confirmed, not just a wick poke
  - Volume > 1.5x average — smart money participation confirmed

ATR-BASED RISK MANAGEMENT:
- Stop loss: 1-2x ATR from entry (adapts to volatility automatically)
- Take profit: 2-3x ATR from entry
- If current ATR > ATR(20): high volatility → reduce size by 25-50%
- If current ATR < ATR(20): low volatility → normal or +25% size

WHY ATR MATTERS:
- Fixed pip stops fail because volatility changes daily
- A 20-pip stop on Gold makes sense in a quiet market but is too tight in NFP
- ATR adapts: tight stops in quiet markets, wide stops in volatile markets
- This is HOW professional traders size every trade

BEST FOR: Trending days, after consolidation. Gold, BTC, indices.
AVOID: Low-volume sessions. Never force a breakout — let it come to you.
"""

from ..data.models import Candle, Signal, Direction, SignalStrength
from .base import BaseStrategy


def compute_atr(candles: list[Candle], period: int = 14) -> float | None:
    """
    Average True Range — measures volatility.

    True Range = max of:
    1. Current high - current low (today's range)
    2. |Current high - previous close| (gap up scenario)
    3. |Current low - previous close| (gap down scenario)

    ATR = average of True Range over `period` candles.
    """
    if len(candles) < period + 1:
        return None

    true_ranges = []
    for i in range(1, len(candles)):
        tr = max(
            candles[i].high - candles[i].low,
            abs(candles[i].high - candles[i - 1].close),
            abs(candles[i].low - candles[i - 1].close),
        )
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return None

    return sum(true_ranges[-period:]) / period


class MomentumBreakoutStrategy(BaseStrategy):
    """
    Momentum Breakout with ATR-based stops and targets.

    Parameters:
    - atr_period: ATR lookback (14)
    - min_candle_atr_mult: breakout candle must be >= this x ATR (1.5)
    - min_body_ratio: body must be >= this % of candle range (0.7)
    - atr_buffer_mult: close must be beyond level + this x ATR (0.5)
    - volume_mult: volume must be >= this x average (1.5)
    - stop_atr_mult: stop loss = this x ATR from entry (1.5)
    - target_atr_mult: take profit = this x ATR from entry (3.0)
    """

    def __init__(
        self,
        atr_period: int = 14,
        min_candle_atr_mult: float = 1.5,  # Lowered from 2.0 for more signals (volume filter catches weak ones)
        min_body_ratio: float = 0.7,
        atr_buffer_mult: float = 0.5,
        volume_mult: float = 1.5,
        stop_atr_mult: float = 1.5,
        target_atr_mult: float = 3.0,
    ):
        self.atr_period = atr_period
        self.min_candle_atr_mult = min_candle_atr_mult
        self.min_body_ratio = min_body_ratio
        self.atr_buffer_mult = atr_buffer_mult
        self.volume_mult = volume_mult
        self.stop_atr_mult = stop_atr_mult
        self.target_atr_mult = target_atr_mult

    @property
    def name(self) -> str:
        return "momentum_breakout"

    @property
    def category(self) -> str:
        return "breakout"

    def _find_swing_levels(self, candles: list[Candle], lookback: int = 30) -> tuple[float, float]:
        """
        Find recent swing high and swing low as S/R levels.

        A swing high: candle where the high is higher than 3 candles on each side.
        A swing low: candle where the low is lower than 3 candles on each side.

        Falls back to simple max high / min low if no swings found.
        """
        recent = candles[-lookback:]

        swing_highs = []
        swing_lows = []

        for i in range(3, len(recent) - 3):
            # Swing high: higher than 3 candles on each side
            if all(recent[i].high >= recent[i + j].high for j in range(-3, 4) if j != 0):
                swing_highs.append(recent[i].high)
            # Swing low: lower than 3 candles on each side
            if all(recent[i].low <= recent[i + j].low for j in range(-3, 4) if j != 0):
                swing_lows.append(recent[i].low)

        # Use most recent swing, or fall back to simple H/L
        resistance = swing_highs[-1] if swing_highs else max(c.high for c in recent[:-1])
        support = swing_lows[-1] if swing_lows else min(c.low for c in recent[:-1])

        return resistance, support

    def analyze(self, candles: list[Candle], symbol: str = "") -> Signal:
        if len(candles) < 50:
            return self._no_signal("Not enough candles for ATR + S/R detection")

        current_candle = candles[-1]
        current_price = current_candle.close

        # Compute ATR
        atr = compute_atr(candles, self.atr_period)
        if atr is None or atr == 0:
            return self._no_signal("ATR calculation failed")

        # Longer-term ATR for volatility comparison
        atr_long = compute_atr(candles, 20) or atr
        vol_ratio = atr / atr_long  # >1 = expanding vol, <1 = contracting

        # Find S/R levels (excluding current candle)
        resistance, support = self._find_swing_levels(candles[:-1])

        # Current candle metrics
        candle_range = current_candle.total_range
        body_ratio = current_candle.body_ratio

        # Volume check
        avg_volume = sum(c.volume for c in candles[-20:]) / 20 if candles[-20:] else 0
        vol_confirmed = (avg_volume == 0 or
                         current_candle.volume >= avg_volume * self.volume_mult)

        atr_buffer = atr * self.atr_buffer_mult

        # --- BULLISH BREAKOUT: Candle smashes through resistance ---
        if (current_candle.is_bullish and
                current_price > resistance + atr_buffer and
                candle_range >= atr * self.min_candle_atr_mult and
                body_ratio >= self.min_body_ratio):

            if not vol_confirmed:
                return self._no_signal("Breakout candle without volume confirmation")

            # ATR-based stops
            stop_loss = current_price - atr * self.stop_atr_mult
            take_profit = current_price + atr * self.target_atr_mult

            # Score: candle size relative to ATR + volume + body ratio
            atr_mult = candle_range / atr
            score = min(85, 50 + atr_mult * 5 + body_ratio * 10 +
                        (5 if vol_confirmed else 0))

            # Volatility note: if ATR expanding, flag for size reduction
            vol_note = ""
            if vol_ratio > 1.3:
                vol_note = " HIGH VOL: Consider reducing position size 25-50%."

            return Signal(
                strategy_name=self.name,
                direction=Direction.LONG,
                strength=SignalStrength.STRONG if atr_mult > 2.5 else SignalStrength.MODERATE,
                score=score,
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "resistance": round(resistance, 2),
                    "atr": round(atr, 2),
                    "candle_atr_mult": round(atr_mult, 2),
                    "body_ratio": round(body_ratio, 2),
                    "vol_ratio": round(vol_ratio, 2),
                    "volume_confirmed": vol_confirmed,
                },
                reason=f"Momentum breakout above {resistance:.2f}. "
                       f"Candle = {atr_mult:.1f}x ATR, body {body_ratio*100:.0f}%. "
                       f"ATR-based SL/TP.{vol_note}",
            )

        # --- BEARISH BREAKOUT: Candle smashes through support ---
        if (not current_candle.is_bullish and
                current_price < support - atr_buffer and
                candle_range >= atr * self.min_candle_atr_mult and
                body_ratio >= self.min_body_ratio):

            if not vol_confirmed:
                return self._no_signal("Breakout candle without volume confirmation")

            stop_loss = current_price + atr * self.stop_atr_mult
            take_profit = current_price - atr * self.target_atr_mult

            atr_mult = candle_range / atr
            score = min(85, 50 + atr_mult * 5 + body_ratio * 10 +
                        (5 if vol_confirmed else 0))

            vol_note = ""
            if vol_ratio > 1.3:
                vol_note = " HIGH VOL: Consider reducing position size 25-50%."

            return Signal(
                strategy_name=self.name,
                direction=Direction.SHORT,
                strength=SignalStrength.STRONG if atr_mult > 2.5 else SignalStrength.MODERATE,
                score=score,
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "support": round(support, 2),
                    "atr": round(atr, 2),
                    "candle_atr_mult": round(atr_mult, 2),
                    "body_ratio": round(body_ratio, 2),
                    "vol_ratio": round(vol_ratio, 2),
                    "volume_confirmed": vol_confirmed,
                },
                reason=f"Momentum breakdown below {support:.2f}. "
                       f"Candle = {atr_mult:.1f}x ATR, body {body_ratio*100:.0f}%. "
                       f"ATR-based SL/TP.{vol_note}",
            )

        return self._no_signal(
            f"No momentum breakout. S={support:.2f}, R={resistance:.2f}, "
            f"ATR={atr:.2f}, candle range={candle_range:.2f}"
        )
