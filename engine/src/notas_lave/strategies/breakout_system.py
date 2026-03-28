"""Composite Strategy: Breakout System.

Replaces: London Breakout, NY Open Range, Break & Retest, Momentum Breakout

HOW REAL TRADERS COMBINE BREAKOUT ELEMENTS:
A breakout alone is just price moving past a level. Most breakouts fail.
What separates real breakouts from fakeouts is MULTIPLE CONFIRMATIONS:
1. S/R level clearly defined (swing high/low, session range boundary)
2. COMPRESSION before breakout (ranges shrinking = stored energy)
3. VOLUME SURGE on the breakout candle (institutional participation)
4. CANDLE QUALITY (big body, small wicks = conviction, not wick-poke)
5. ATR EXPANSION (volatility expanding from quiet period)
6. SESSION CONTEXT (London/NY open = highest-probability breakout windows)
7. RETEST of broken level (optional but increases win rate 10-15%)

SIGNAL LOGIC:
1. LEVEL: Identify clear S/R (swing highs/lows over lookback period)
2. COMPRESSION: Range contraction before breakout (Williams' insight)
3. BREAKOUT CANDLE: Range > 1.5x ATR, body > 60% of range, beyond level
4. VOLUME: Must be > 1.5x average (confirms institutional participation)
5. SESSION: Bonus during London (08-12 UTC) or NY (13-17 UTC) hours
6. RETEST: If price comes back to test broken level as new S/R = higher score

SOURCES:
- Momentum breakout with ATR: existing system logic, enhanced
- London/NY session breakout: existing system, combined instead of separate
- Compression → breakout: Larry Williams' volatility cycle insight
- Retest confirmation: institutional execution technique
"""

from datetime import datetime, timezone
from ..data.models import Candle, Signal, Direction, SignalStrength
from .base import BaseStrategy


def _to_utc_hour(ts: datetime) -> int:
    """Extract UTC hour from timestamp."""
    if ts.tzinfo is None:
        return ts.hour
    return ts.astimezone(timezone.utc).hour


def detect_compression(candles: list[Candle], lookback: int = 10) -> float:
    """Ratio of shrinking ranges (0-1). > 0.6 = compressed."""
    if len(candles) < lookback:
        return 0.0
    ranges = [c.high - c.low for c in candles[-lookback:]]
    shrinking = sum(1 for i in range(1, len(ranges)) if ranges[i] < ranges[i - 1])
    return shrinking / (len(ranges) - 1)


def find_swing_levels(candles: list[Candle], lookback: int = 30) -> tuple[float, float]:
    """Find nearest swing high (resistance) and swing low (support)."""
    recent = candles[-lookback:]
    swing_highs = []
    swing_lows = []

    for i in range(3, len(recent) - 3):
        if all(recent[i].high >= recent[i + j].high for j in range(-3, 4) if j != 0):
            swing_highs.append(recent[i].high)
        if all(recent[i].low <= recent[i + j].low for j in range(-3, 4) if j != 0):
            swing_lows.append(recent[i].low)

    resistance = swing_highs[-1] if swing_highs else max(c.high for c in recent[:-1])
    support = swing_lows[-1] if swing_lows else min(c.low for c in recent[:-1])
    return resistance, support


class BreakoutSystem(BaseStrategy):
    """Multi-factor breakout — only fires on confirmed, high-quality breaks.

    Combines S/R detection + compression + volume + candle quality + session.
    """

    def __init__(
        self,
        min_candle_atr_mult: float = 1.3,
        min_body_ratio: float = 0.6,
        volume_mult: float = 1.5,
        compression_lookback: int = 10,
        swing_lookback: int = 30,
    ):
        self.min_candle_atr_mult = min_candle_atr_mult
        self.min_body_ratio = min_body_ratio
        self.volume_mult = volume_mult
        self.compression_lookback = compression_lookback
        self.swing_lookback = swing_lookback

    @property
    def name(self) -> str:
        return "breakout_system"

    @property
    def category(self) -> str:
        return "breakout"

    def analyze(self, candles: list[Candle], symbol: str = "") -> Signal:
        if len(candles) < max(self.swing_lookback, 50) + 10:
            return self._no_signal("Not enough candles for Breakout System")

        current = candles[-1]
        current_price = current.close

        atr = self.compute_atr(candles)
        if not atr or atr == 0:
            return self._no_signal("ATR calculation failed")

        # --- Compute all factors ---
        resistance, support = find_swing_levels(candles[:-1], self.swing_lookback)
        compression = detect_compression(candles[:-1], self.compression_lookback)
        candle_range = current.total_range
        body_ratio = current.body_ratio

        # ATR expansion check
        atr_long = self.compute_atr(candles, period=20) or atr
        atr_expansion = atr / atr_long if atr_long > 0 else 1.0

        # Session detection
        utc_hour = _to_utc_hour(current.timestamp)
        in_london = 8 <= utc_hour <= 12
        in_ny = 13 <= utc_hour <= 17
        in_active_session = in_london or in_ny

        # Volume check
        vol_confirmed = self.check_volume(candles, multiplier=self.volume_mult)

        long_factors = []
        short_factors = []

        # --- BULLISH BREAKOUT above resistance ---
        if current_price > resistance and current.is_bullish:
            long_factors.append("broke_resistance")

            # Quality checks
            if candle_range >= atr * self.min_candle_atr_mult:
                long_factors.append("strong_candle")
            if body_ratio >= self.min_body_ratio:
                long_factors.append("clean_body")
            if vol_confirmed:
                long_factors.append("volume_confirmed")
            if compression > 0.6:
                long_factors.append("compression_release")
            if in_active_session:
                long_factors.append(f"{'london' if in_london else 'ny'}_session")
            if atr_expansion > 1.3:
                long_factors.append("atr_expanding")

            # Retest detection: did price come back and bounce off resistance?
            if len(candles) >= 5:
                # Check if any of the last 3 candles touched resistance from above
                for c in candles[-4:-1]:
                    if c.low <= resistance * 1.002 and c.close > resistance:
                        long_factors.append("retest_confirmed")
                        break

        # --- BEARISH BREAKOUT below support ---
        if current_price < support and not current.is_bullish:
            short_factors.append("broke_support")

            if candle_range >= atr * self.min_candle_atr_mult:
                short_factors.append("strong_candle")
            if body_ratio >= self.min_body_ratio:
                short_factors.append("clean_body")
            if vol_confirmed:
                short_factors.append("volume_confirmed")
            if compression > 0.6:
                short_factors.append("compression_release")
            if in_active_session:
                short_factors.append(f"{'london' if in_london else 'ny'}_session")
            if atr_expansion > 1.3:
                short_factors.append("atr_expanding")

            if len(candles) >= 5:
                for c in candles[-4:-1]:
                    if c.high >= support * 0.998 and c.close < support:
                        short_factors.append("retest_confirmed")
                        break

        # --- SIGNAL: broke level + minimum 3 total factors ---
        min_required = 3

        if len(long_factors) >= min_required and "broke_resistance" in long_factors:
            stop_loss = self.atr_stop_loss(current_price, atr, "LONG", 1.5)
            risk = abs(current_price - stop_loss)
            rr = 2.5 if "compression_release" in long_factors else 2.0
            take_profit = self.atr_take_profit(current_price, atr, "LONG", rr, risk)

            score = min(90, 40 + len(long_factors) * 10)
            strength = SignalStrength.STRONG if len(long_factors) >= 5 else SignalStrength.MODERATE

            return Signal(
                strategy_name=self.name,
                direction=Direction.LONG,
                strength=strength,
                score=score,
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "factors": long_factors,
                    "factor_count": len(long_factors),
                    "resistance": round(resistance, 2),
                    "compression": round(compression, 2),
                    "body_ratio": round(body_ratio, 2),
                    "atr_expansion": round(atr_expansion, 2),
                    "session": "london" if in_london else "ny" if in_ny else "other",
                },
                reason=f"Breakout LONG above {resistance:.2f}: "
                f"{len(long_factors)} factors — " + ", ".join(long_factors),
            )

        if len(short_factors) >= min_required and "broke_support" in short_factors:
            stop_loss = self.atr_stop_loss(current_price, atr, "SHORT", 1.5)
            risk = abs(current_price - stop_loss)
            rr = 2.5 if "compression_release" in short_factors else 2.0
            take_profit = self.atr_take_profit(current_price, atr, "SHORT", rr, risk)

            score = min(90, 40 + len(short_factors) * 10)
            strength = SignalStrength.STRONG if len(short_factors) >= 5 else SignalStrength.MODERATE

            return Signal(
                strategy_name=self.name,
                direction=Direction.SHORT,
                strength=strength,
                score=score,
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "factors": short_factors,
                    "factor_count": len(short_factors),
                    "support": round(support, 2),
                    "compression": round(compression, 2),
                    "body_ratio": round(body_ratio, 2),
                    "atr_expansion": round(atr_expansion, 2),
                    "session": "london" if in_london else "ny" if in_ny else "other",
                },
                reason=f"Breakout SHORT below {support:.2f}: "
                f"{len(short_factors)} factors — " + ", ".join(short_factors),
            )

        return self._no_signal(
            f"No breakout. S={support:.2f}, R={resistance:.2f}, "
            f"Compression={compression:.0%}"
        )
