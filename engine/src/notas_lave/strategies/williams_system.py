"""Strategy #13: Larry Williams Composite System.

This is NOT a single indicator — it's a complete trading system that
combines multiple Larry Williams techniques the way HE actually trades.

Larry doesn't use %R alone. He combines:
1. Williams %R for TIMING (oversold/overbought + cooldown)
2. Volatility compression for READINESS (quiet → explosive)
3. Smash Day pattern for REVERSAL CONFIRMATION
4. MACD for TREND DIRECTION filter
5. Volume for PARTICIPATION confirmation

SIGNAL TYPES (in priority order):
A. SMASH DAY + %R EXTREME: Volatile reversal candle while %R is oversold/overbought
   → Highest conviction. Two independent reversal signals agree.
B. %R RECOVERY + COMPRESSION: %R leaving extreme after volatility compression
   → Spring loaded. Mean reversion after coiled market.
C. VOLATILITY BREAKOUT + %R DIRECTION: Price breaks compressed range while %R
   confirms direction → Breakout with momentum alignment.

Every signal requires MACD alignment + volume confirmation. No cherry-picking
individual indicators — that's what separates a system from a signal.

SOURCES:
- Larry Williams, "Long-Term Secrets to Short-Term Trading"
- Williams %R, Smash Day, Volatility Breakout, MACD filter — all his techniques
- Adapted for crypto: 24/7 market, no session gaps, higher volatility
"""

from ..data.models import Candle, Signal, Direction, SignalStrength
from .base import BaseStrategy


def compute_williams_r(candles: list[Candle], period: int = 14) -> list[float]:
    """%R = (Highest_High - Close) / (Highest_High - Lowest_Low) * -100"""
    if len(candles) < period:
        return []
    values = []
    for i in range(period - 1, len(candles)):
        window = candles[i - period + 1 : i + 1]
        highest = max(c.high for c in window)
        lowest = min(c.low for c in window)
        if highest == lowest:
            values.append(-50.0)
        else:
            values.append((highest - candles[i].close) / (highest - lowest) * -100)
    return values


def compute_macd_value(closes: list[float], fast: int = 12, slow: int = 26) -> float | None:
    """MACD = fast EMA - slow EMA. Positive = bullish context."""
    if len(closes) < slow + 1:
        return None

    def _ema(data: list[float], period: int) -> float:
        mult = 2.0 / (period + 1)
        val = data[0]
        for price in data[1:]:
            val = (price - val) * mult + val
        return val

    return _ema(closes[-fast * 2 :], fast) - _ema(closes[-slow * 2 :], slow)


def detect_compression(candles: list[Candle], lookback: int = 10) -> float:
    """Ratio of shrinking ranges (0-1). > 0.6 = compressed/coiled."""
    if len(candles) < lookback:
        return 0.0
    ranges = [c.high - c.low for c in candles[-lookback:]]
    shrinking = sum(1 for i in range(1, len(ranges)) if ranges[i] < ranges[i - 1])
    return shrinking / (len(ranges) - 1)


def detect_smash_day(candle: Candle, atr: float, mult: float = 1.5) -> dict | None:
    """Check if a candle is a Smash Day.

    Smash Day = volatile candle (range > mult*ATR) that closes against its move.
    Returns dict with type ('bullish'/'bearish') and close_position, or None.
    """
    if candle.total_range < atr * mult:
        return None

    close_pos = (candle.close - candle.low) / candle.total_range if candle.total_range > 0 else 0.5

    # Bullish smash: candle went low but closed high (upper 25%)
    if close_pos >= 0.75:
        return {"type": "bullish", "close_position": close_pos}
    # Bearish smash: candle went high but closed low (lower 25%)
    if close_pos <= 0.25:
        return {"type": "bearish", "close_position": close_pos}
    return None


class WilliamsSystemStrategy(BaseStrategy):
    """Larry Williams composite trading system.

    Combines %R timing + compression readiness + Smash Day reversal
    + MACD direction + volume confirmation. Only fires when multiple
    elements align — no single-indicator signals.

    Parameters:
    - wr_period: Williams %R lookback (14)
    - cooldown_bars: bars between %R extreme and entry signal (5)
    - compression_lookback: candles for compression detection (10)
    - smash_volatility_mult: Smash Day range must be > this x ATR (1.5)
    - breakout_range_mult: volatility breakout distance multiplier (0.25)
    """

    def __init__(
        self,
        wr_period: int = 14,
        cooldown_bars: int = 5,
        compression_lookback: int = 10,
        smash_volatility_mult: float = 1.5,
        breakout_range_mult: float = 0.25,
    ):
        self.wr_period = wr_period
        self.cooldown_bars = cooldown_bars
        self.compression_lookback = compression_lookback
        self.smash_volatility_mult = smash_volatility_mult
        self.breakout_range_mult = breakout_range_mult

    @property
    def name(self) -> str:
        return "williams_system"

    @property
    def category(self) -> str:
        return "scalping"

    def analyze(self, candles: list[Candle], symbol: str = "") -> Signal:
        min_candles = max(self.wr_period + self.cooldown_bars + 10, 50)
        if len(candles) < min_candles:
            return self._no_signal("Not enough candles for Williams System")

        current = candles[-1]
        completed = candles[-2]
        current_price = current.close
        closes = [c.close for c in candles]

        # --- Compute all indicators ---
        atr = self.compute_atr(candles)
        if not atr or atr == 0:
            return self._no_signal("ATR calculation failed")

        wr_values = compute_williams_r(candles, self.wr_period)
        if len(wr_values) < self.cooldown_bars + 5:
            return self._no_signal("Not enough %R values")

        current_wr = wr_values[-1]
        recent_wr = wr_values[-self.cooldown_bars - 1 : -1]
        macd = compute_macd_value(closes)
        compression = detect_compression(candles[:-1], self.compression_lookback)
        smash = detect_smash_day(completed, atr, self.smash_volatility_mult)

        # Volume gate — no signal without volume
        if not self.check_volume(candles):
            return self._no_signal("Volume too low for Williams System")

        # --- Count confirmation factors for LONG ---
        long_factors = []
        short_factors = []

        # Factor 1: %R at oversold extreme recently → recovering
        wr_oversold = any(v <= -95 for v in recent_wr) and current_wr > -85
        wr_overbought = any(v >= -5 for v in recent_wr) and current_wr < -15
        if wr_oversold:
            long_factors.append("wr_oversold_recovery")
        if wr_overbought:
            short_factors.append("wr_overbought_reversal")

        # Factor 2: MACD direction alignment
        if macd is not None:
            if macd > 0:
                long_factors.append("macd_bullish")
            elif macd < 0:
                short_factors.append("macd_bearish")

        # Factor 3: Compression (coiled spring)
        if compression > 0.6:
            long_factors.append("compressed")
            short_factors.append("compressed")

        # Factor 4: Smash Day reversal pattern
        if smash:
            if smash["type"] == "bullish":
                long_factors.append("smash_day_bullish")
            elif smash["type"] == "bearish":
                short_factors.append("smash_day_bearish")

        # Factor 5: Volatility breakout (price exceeding prior range * 0.25)
        prior_range = completed.high - completed.low
        breakout_dist = prior_range * self.breakout_range_mult
        if breakout_dist > 0:
            if current_price > current.open + breakout_dist:
                long_factors.append("volatility_breakout")
            elif current_price < current.open - breakout_dist:
                short_factors.append("volatility_breakdown")

        # Factor 6: %R momentum failure (failed to re-reach extreme)
        if len(wr_values) >= self.cooldown_bars * 2:
            earlier_wr = wr_values[-self.cooldown_bars * 2 : -self.cooldown_bars]
            if earlier_wr and recent_wr:
                if min(recent_wr) > min(earlier_wr) + 3 and current_wr > -80:
                    long_factors.append("momentum_failure")
                if max(recent_wr) < max(earlier_wr) - 3 and current_wr < -20:
                    short_factors.append("momentum_failure")

        # --- SIGNAL: Require minimum 2 factors + MACD alignment ---

        # LONG signal
        if len(long_factors) >= 2 and "macd_bullish" in long_factors:
            stop_loss = self.atr_stop_loss(current_price, atr, "LONG", 1.5)
            risk = abs(current_price - stop_loss)

            # R:R based on how many factors align
            rr = 2.0 + (len(long_factors) - 2) * 0.5  # More factors = wider target
            take_profit = self.atr_take_profit(current_price, atr, "LONG", rr, risk)

            # Score: base 50 + 10 per factor, capped at 90
            score = min(90, 50 + len(long_factors) * 10)

            # Strength: 4+ factors = STRONG, else MODERATE
            strength = SignalStrength.STRONG if len(long_factors) >= 4 else SignalStrength.MODERATE

            return Signal(
                strategy_name=self.name,
                direction=Direction.LONG,
                strength=strength,
                score=score,
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "williams_r": round(current_wr, 1),
                    "macd": round(macd, 4) if macd else None,
                    "compression": round(compression, 2),
                    "smash_day": smash["type"] if smash else None,
                    "factors": long_factors,
                    "factor_count": len(long_factors),
                },
                reason=f"Williams System LONG: {len(long_factors)} factors aligned — "
                + ", ".join(long_factors)
                + f". %R={current_wr:.0f}",
            )

        # SHORT signal
        if len(short_factors) >= 2 and "macd_bearish" in short_factors:
            stop_loss = self.atr_stop_loss(current_price, atr, "SHORT", 1.5)
            risk = abs(current_price - stop_loss)
            rr = 2.0 + (len(short_factors) - 2) * 0.5
            take_profit = self.atr_take_profit(current_price, atr, "SHORT", rr, risk)

            score = min(90, 50 + len(short_factors) * 10)
            strength = SignalStrength.STRONG if len(short_factors) >= 4 else SignalStrength.MODERATE

            return Signal(
                strategy_name=self.name,
                direction=Direction.SHORT,
                strength=strength,
                score=score,
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "williams_r": round(current_wr, 1),
                    "macd": round(macd, 4) if macd else None,
                    "compression": round(compression, 2),
                    "smash_day": smash["type"] if smash else None,
                    "factors": short_factors,
                    "factor_count": len(short_factors),
                },
                reason=f"Williams System SHORT: {len(short_factors)} factors aligned — "
                + ", ".join(short_factors)
                + f". %R={current_wr:.0f}",
            )

        # No signal — report what's partially aligned for debugging
        all_factors = set(long_factors + short_factors)
        return self._no_signal(
            f"Williams System: insufficient alignment. "
            f"Long={len(long_factors)} ({', '.join(long_factors) or 'none'}), "
            f"Short={len(short_factors)} ({', '.join(short_factors) or 'none'}). "
            f"%R={current_wr:.0f}, MACD={'pos' if macd and macd > 0 else 'neg' if macd else '?'}"
        )
