"""
Strategy #19: Stochastic Scalping (5,3,3 Fast Settings).

HOW IT WORKS:
- Stochastic measures WHERE the current price is relative to recent range
- %K = (Close - Lowest Low) / (Highest High - Lowest Low) * 100
- %D = 3-period SMA of %K (smoother signal line)
- Above 80 = overbought (price near top of recent range)
- Below 20 = oversold (price near bottom of recent range)

ENTRY RULES:
- LONG: %K crosses ABOVE %D while both are below 20 (oversold bounce)
- SHORT: %K crosses BELOW %D while both are above 80 (overbought rejection)

WHY IT WORKS:
- In RANGING markets, price oscillates between overbought and oversold
- The crossover shows momentum shifting direction
- 70-80% win rate in ranges, but FAILS in strong trends

WARNING: In trends, overbought stays overbought. Don't fight the trend!
"""

from ..data.models import Candle, Signal, Direction, SignalStrength
from .base import BaseStrategy


def compute_stochastic(
    candles: list[Candle], k_period: int = 5, k_smooth: int = 3, d_period: int = 3
) -> tuple[list[float], list[float]]:
    """
    Compute Stochastic %K and %D.

    %K = ((Close - Lowest Low) / (Highest High - Lowest Low)) * 100
    Then %K is smoothed by k_smooth period SMA.
    %D = d_period SMA of smoothed %K.
    """
    if len(candles) < k_period + k_smooth + d_period:
        return [], []

    # Raw %K values
    raw_k = []
    for i in range(k_period - 1, len(candles)):
        window = candles[i - k_period + 1:i + 1]
        lowest = min(c.low for c in window)
        highest = max(c.high for c in window)
        if highest == lowest:
            raw_k.append(50.0)  # Flat market
        else:
            raw_k.append(((candles[i].close - lowest) / (highest - lowest)) * 100)

    # Smooth %K with SMA
    smooth_k = []
    for i in range(k_smooth - 1, len(raw_k)):
        smooth_k.append(sum(raw_k[i - k_smooth + 1:i + 1]) / k_smooth)

    # %D = SMA of smooth %K
    d_values = []
    for i in range(d_period - 1, len(smooth_k)):
        d_values.append(sum(smooth_k[i - d_period + 1:i + 1]) / d_period)

    # Align: return same-length arrays (trim smooth_k to match d)
    aligned_k = smooth_k[d_period - 1:]
    return aligned_k, d_values


class StochasticScalpingStrategy(BaseStrategy):
    """
    Stochastic crossover in overbought/oversold zones.

    Uses fast settings (5,3,3) for scalping on 1m-15m charts.
    """

    def __init__(
        self,
        k_period: int = 5,
        k_smooth: int = 3,
        d_period: int = 3,
        oversold: float = 20.0,
        overbought: float = 80.0,
    ):
        self.k_period = k_period
        self.k_smooth = k_smooth
        self.d_period = d_period
        self.oversold = oversold
        self.overbought = overbought

    @property
    def name(self) -> str:
        return "stochastic_scalping"

    @property
    def category(self) -> str:
        return "scalping"

    def analyze(self, candles: list[Candle], symbol: str = "") -> Signal:
        min_candles = self.k_period + self.k_smooth + self.d_period + 5
        if len(candles) < min_candles:
            return self._no_signal("Not enough candles for Stochastic")

        k_values, d_values = compute_stochastic(
            candles, self.k_period, self.k_smooth, self.d_period
        )

        if len(k_values) < 2 or len(d_values) < 2:
            return self._no_signal("Stochastic calculation failed")

        k_now = k_values[-1]
        k_prev = k_values[-2]
        d_now = d_values[-1]
        d_prev = d_values[-2]
        current_price = candles[-1].close

        # --- BULLISH: %K crosses above %D in oversold zone ---
        bullish_cross = k_prev <= d_prev and k_now > d_now
        in_oversold = k_now < self.oversold + 10 and d_now < self.oversold + 15

        if bullish_cross and in_oversold:
            # Stop loss at recent swing low
            recent_lows = [c.low for c in candles[-10:]]
            stop_loss = min(recent_lows) - (current_price - min(recent_lows)) * 0.2
            risk = current_price - stop_loss
            take_profit = current_price + risk * 1.5  # Stochastic uses 1.5:1 R:R (mean reversion)

            # Score: deeper oversold = higher score
            depth = max(0, self.oversold - min(k_now, d_now))
            score = min(75, 45 + depth * 1.5)

            return Signal(
                strategy_name=self.name,
                direction=Direction.LONG,
                strength=SignalStrength.STRONG if k_now < 10 else SignalStrength.MODERATE,
                score=score,
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "k": round(k_now, 1),
                    "d": round(d_now, 1),
                    "zone": "oversold",
                },
                reason=f"Stochastic bullish cross in oversold zone. %K={k_now:.1f}, %D={d_now:.1f}",
            )

        # --- BEARISH: %K crosses below %D in overbought zone ---
        bearish_cross = k_prev >= d_prev and k_now < d_now
        in_overbought = k_now > self.overbought - 10 and d_now > self.overbought - 15

        if bearish_cross and in_overbought:
            recent_highs = [c.high for c in candles[-10:]]
            stop_loss = max(recent_highs) + (max(recent_highs) - current_price) * 0.2
            risk = stop_loss - current_price
            take_profit = current_price - risk * 1.5

            depth = max(0, max(k_now, d_now) - self.overbought)
            score = min(75, 45 + depth * 1.5)

            return Signal(
                strategy_name=self.name,
                direction=Direction.SHORT,
                strength=SignalStrength.STRONG if k_now > 90 else SignalStrength.MODERATE,
                score=score,
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "k": round(k_now, 1),
                    "d": round(d_now, 1),
                    "zone": "overbought",
                },
                reason=f"Stochastic bearish cross in overbought zone. %K={k_now:.1f}, %D={d_now:.1f}",
            )

        return self._no_signal(f"No Stochastic setup. %K={k_now:.1f}, %D={d_now:.1f}")
