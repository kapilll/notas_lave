"""
Strategy #3/#13: ICT Kill Zone + Session Range Breakout.

HOW IT WORKS:
- Markets have specific "kill zones" — time windows when institutions trade
- Asian session (00:00-08:00 GMT): Price consolidates, builds a range
- London session (08:00-12:00 GMT): Breaks the Asian range, establishes direction
- New York session (13:00-17:00 GMT): Continues or reverses London's move

THE ICT INSIGHT: Price sweeps liquidity (stops above/below ranges) then reverses.
Smart money hunts retail stops before making the real move.

ENTRY RULES:
- Mark the Asian session range (high and low)
- At London open, watch for a liquidity sweep (price breaks range then reverses)
- Enter AFTER the sweep reverses, not on the initial breakout
- The first breakout is often FAKE (a trap to grab stops)

WHY IT WORKS:
- Asian session = accumulation (institutions build positions quietly)
- London = distribution (they push price to trigger stops and get fills)
- By waiting for the sweep + reversal, you enter WITH smart money

BEST FOR: Gold (responds extremely well), GBPUSD, EURUSD
"""

from datetime import datetime, timezone
from ..data.models import Candle, Signal, Direction, SignalStrength
from .base import BaseStrategy


# Kill zone times in UTC hours
KILL_ZONES = {
    "asian":  (0, 8),    # 00:00-08:00 UTC
    "london": (8, 12),   # 08:00-12:00 UTC (most powerful)
    "ny":     (13, 17),  # 13:00-17:00 UTC
}


def get_current_killzone(candles: list[Candle]) -> str | None:
    """Determine which kill zone we're in based on the latest candle."""
    if not candles:
        return None
    hour = candles[-1].timestamp.hour
    for zone, (start, end) in KILL_ZONES.items():
        if start <= hour < end:
            return zone
    return None


def get_session_range(candles: list[Candle], start_hour: int, end_hour: int) -> tuple[float, float] | None:
    """
    Get the high/low of candles within a time window.
    Returns (session_high, session_low) or None.
    """
    session_candles = [
        c for c in candles
        if start_hour <= c.timestamp.hour < end_hour
    ]
    if not session_candles:
        return None
    return (
        max(c.high for c in session_candles),
        min(c.low for c in session_candles),
    )


class SessionKillZoneStrategy(BaseStrategy):
    """
    ICT Kill Zone strategy with Asian range liquidity sweep detection.

    Looks for price to sweep the Asian range during London/NY,
    then reverse — entering with smart money after the trap.
    """

    def __init__(
        self,
        sweep_buffer_pct: float = 0.001,  # How far price must go beyond range (0.1%)
        min_range_pct: float = 0.002,  # Minimum Asian range size (0.2%)
    ):
        self.sweep_buffer_pct = sweep_buffer_pct
        self.min_range_pct = min_range_pct

    @property
    def name(self) -> str:
        return "session_killzone"

    @property
    def category(self) -> str:
        return "ict"

    def analyze(self, candles: list[Candle], symbol: str = "") -> Signal:
        if len(candles) < 50:
            return self._no_signal("Not enough candles")

        current_kz = get_current_killzone(candles)
        current_price = candles[-1].close
        current_candle = candles[-1]

        # Only trade during London or NY kill zones
        if current_kz not in ("london", "ny"):
            return self._no_signal(f"Outside kill zone (current: {current_kz or 'none'})")

        # Get Asian session range
        asian_range = get_session_range(candles, 0, 8)
        if asian_range is None:
            return self._no_signal("No Asian session data available")

        asian_high, asian_low = asian_range
        range_size = asian_high - asian_low
        range_pct = range_size / asian_low

        if range_pct < self.min_range_pct:
            return self._no_signal(f"Asian range too small ({range_pct*100:.2f}%)")

        sweep_buffer = current_price * self.sweep_buffer_pct

        # Check recent candles for a sweep pattern
        # We look at the last 10 candles for the sweep + reversal
        recent = candles[-10:]

        # --- BULLISH: Price swept below Asian low, then reversed up ---
        swept_below = any(c.low < asian_low - sweep_buffer for c in recent)
        reversed_up = current_candle.is_bullish and current_price > asian_low

        if swept_below and reversed_up:
            # Find the sweep candle (lowest low in recent)
            sweep_low = min(c.low for c in recent)

            stop_loss = sweep_low - range_size * 0.15
            take_profit = asian_high + range_size * 0.5  # Target above Asian high

            risk = current_price - stop_loss
            reward = take_profit - current_price
            rr = reward / risk if risk > 0 else 0

            score = min(85, 55 + (asian_low - sweep_low) / current_price * 10000)

            return Signal(
                strategy_name=self.name,
                direction=Direction.LONG,
                strength=SignalStrength.STRONG if current_kz == "london" else SignalStrength.MODERATE,
                score=score,
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "asian_high": round(asian_high, 2),
                    "asian_low": round(asian_low, 2),
                    "sweep_low": round(sweep_low, 2),
                    "kill_zone": current_kz,
                    "range_pct": round(range_pct * 100, 2),
                    "risk_reward": round(rr, 2),
                },
                reason=f"Liquidity sweep below Asian low ({asian_low:.2f}), reversed in {current_kz} KZ. Sweep depth: {asian_low - sweep_low:.2f}",
            )

        # --- BEARISH: Price swept above Asian high, then reversed down ---
        swept_above = any(c.high > asian_high + sweep_buffer for c in recent)
        reversed_down = not current_candle.is_bullish and current_price < asian_high

        if swept_above and reversed_down:
            sweep_high = max(c.high for c in recent)

            stop_loss = sweep_high + range_size * 0.15
            take_profit = asian_low - range_size * 0.5

            risk = stop_loss - current_price
            reward = current_price - take_profit
            rr = reward / risk if risk > 0 else 0

            score = min(85, 55 + (sweep_high - asian_high) / current_price * 10000)

            return Signal(
                strategy_name=self.name,
                direction=Direction.SHORT,
                strength=SignalStrength.STRONG if current_kz == "london" else SignalStrength.MODERATE,
                score=score,
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "asian_high": round(asian_high, 2),
                    "asian_low": round(asian_low, 2),
                    "sweep_high": round(sweep_high, 2),
                    "kill_zone": current_kz,
                    "range_pct": round(range_pct * 100, 2),
                    "risk_reward": round(rr, 2),
                },
                reason=f"Liquidity sweep above Asian high ({asian_high:.2f}), reversed in {current_kz} KZ. Sweep depth: {sweep_high - asian_high:.2f}",
            )

        return self._no_signal(f"No sweep detected in {current_kz} KZ. Asian range: {asian_low:.2f}-{asian_high:.2f}")
