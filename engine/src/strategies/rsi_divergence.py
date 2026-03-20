"""
Strategy #12: RSI Divergence Scalping (Fast 7-Period).

HOW IT WORKS:
- RSI (Relative Strength Index) measures momentum on a 0-100 scale
- Below 30 = oversold (selling exhausted, potential bounce)
- Above 70 = overbought (buying exhausted, potential drop)
- DIVERGENCE = price makes a new extreme but RSI doesn't confirm it
  - Bullish divergence: Price makes LOWER low, RSI makes HIGHER low
    → Sellers are weakening even though price dropped. Reversal likely.
  - Bearish divergence: Price makes HIGHER high, RSI makes LOWER high
    → Buyers are weakening even though price rose. Reversal likely.

WHY IT WORKS:
- Divergence reveals hidden momentum shifts BEFORE price reverses
- It's one of the strongest leading indicators in scalping
- Combined with oversold/overbought levels, it filters out weak divergences

BEST FOR: Gold (extremely responsive), volatile crypto
PARAMETERS: RSI(7) for scalping, RSI(14) for standard
"""

from ..data.models import Candle, Signal, Direction, SignalStrength
from .base import BaseStrategy


def compute_rsi(prices: list[float], period: int = 14) -> list[float]:
    """
    Compute RSI (Relative Strength Index).

    RSI = 100 - (100 / (1 + RS))
    where RS = Average Gain / Average Loss over `period` candles.

    RSI of 70+ = overbought (too many buyers, exhaustion coming)
    RSI of 30- = oversold (too many sellers, bounce coming)
    """
    if len(prices) < period + 1:
        return []

    rsi_values = []
    gains = []
    losses = []

    # Calculate price changes
    for i in range(1, len(prices)):
        change = prices[i] - prices[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    # First RS uses simple average of first `period` changes
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    if avg_loss == 0:
        rsi_values.append(100.0)
    else:
        rs = avg_gain / avg_loss
        rsi_values.append(100 - (100 / (1 + rs)))

    # Subsequent values use smoothed (exponential) averages
    # This is the Wilder smoothing method — gives more weight to recent data
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100 - (100 / (1 + rs)))

    return rsi_values


def find_swing_lows(prices: list[float], lookback: int = 5) -> list[tuple[int, float]]:
    """
    Find swing lows — points where price dips and then rises.

    Fix #9: The last swing can be "forming" — only requires left-side confirmation.
    This means we can detect divergences up to the most recent candle, not
    always `lookback` candles behind.
    """
    swings = []
    # Confirmed swings: need both sides
    for i in range(lookback, len(prices) - lookback):
        if all(prices[i] <= prices[i - j] for j in range(1, lookback + 1)) and \
           all(prices[i] <= prices[i + j] for j in range(1, lookback + 1)):
            swings.append((i, prices[i]))

    # Forming swing at the end: only need left side confirmed
    # Check last few candles for a potential forming low
    for i in range(max(lookback, len(prices) - lookback), len(prices) - 1):
        if all(prices[i] <= prices[i - j] for j in range(1, min(lookback + 1, i + 1))):
            # Price has been rising since this point
            if prices[-1] > prices[i]:
                swings.append((i, prices[i]))
                break  # Only add the most recent forming swing

    return swings


def find_swing_highs(prices: list[float], lookback: int = 5) -> list[tuple[int, float]]:
    """Find swing highs. Fix #9: includes forming swings at the end."""
    swings = []
    for i in range(lookback, len(prices) - lookback):
        if all(prices[i] >= prices[i - j] for j in range(1, lookback + 1)) and \
           all(prices[i] >= prices[i + j] for j in range(1, lookback + 1)):
            swings.append((i, prices[i]))
    return swings


class RSIDivergenceStrategy(BaseStrategy):
    """
    RSI Divergence detector for scalping.

    Looks for price/RSI divergence in oversold/overbought zones.
    Uses fast RSI (7-period) for scalping, with configurable thresholds.
    """

    def __init__(
        self,
        rsi_period: int = 7,            # Fast RSI for scalping (default 14 is slower)
        oversold: float = 30.0,         # RSI below this = oversold
        overbought: float = 70.0,       # RSI above this = overbought
        swing_lookback: int = 3,        # How many candles to check for swing detection
        min_divergence_rsi: float = 3.0,  # Minimum RSI difference to count as divergence
    ):
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought
        self.swing_lookback = swing_lookback
        self.min_divergence_rsi = min_divergence_rsi

    @property
    def name(self) -> str:
        return "rsi_divergence"

    @property
    def category(self) -> str:
        return "scalping"

    def analyze(self, candles: list[Candle], symbol: str = "") -> Signal:
        if len(candles) < self.rsi_period + 20:
            return self._no_signal("Not enough candles for RSI divergence")

        closes = [c.close for c in candles]
        lows = [c.low for c in candles]
        highs = [c.high for c in candles]

        # Compute RSI
        rsi_values = compute_rsi(closes, self.rsi_period)
        if len(rsi_values) < 20:
            return self._no_signal("RSI calculation produced too few values")

        current_rsi = rsi_values[-1]
        current_price = closes[-1]

        # Align RSI with price data
        # RSI starts at index `rsi_period` of the price array
        rsi_offset = len(closes) - len(rsi_values)

        # --- Check for BULLISH divergence ---
        # Price makes lower low, RSI makes higher low (in oversold zone)
        if current_rsi < self.oversold + 15:  # Check when RSI is near oversold
            price_swings = find_swing_lows(lows, self.swing_lookback)
            if len(price_swings) >= 2:
                # Get last two swing lows
                prev_swing = price_swings[-2]
                curr_swing = price_swings[-1]

                # Price made lower low?
                price_lower_low = curr_swing[1] < prev_swing[1]

                if price_lower_low:
                    # Get RSI at those same points
                    prev_rsi_idx = prev_swing[0] - rsi_offset
                    curr_rsi_idx = curr_swing[0] - rsi_offset

                    if 0 <= prev_rsi_idx < len(rsi_values) and 0 <= curr_rsi_idx < len(rsi_values):
                        prev_rsi = rsi_values[prev_rsi_idx]
                        curr_rsi_at_swing = rsi_values[curr_rsi_idx]

                        # RSI made higher low? (divergence!)
                        rsi_higher_low = curr_rsi_at_swing > prev_rsi + self.min_divergence_rsi

                        if rsi_higher_low and curr_rsi_at_swing < self.oversold + 10:
                            # Bullish divergence found!
                            stop_loss = curr_swing[1] - (current_price - curr_swing[1]) * 0.3
                            risk = current_price - stop_loss
                            take_profit = current_price + risk * 2.0

                            divergence_strength = curr_rsi_at_swing - prev_rsi
                            score = min(90, 50 + divergence_strength * 3)

                            return Signal(
                                strategy_name=self.name,
                                direction=Direction.LONG,
                                strength=SignalStrength.STRONG if divergence_strength > 10 else SignalStrength.MODERATE,
                                score=score,
                                entry_price=current_price,
                                stop_loss=round(stop_loss, 2),
                                take_profit=round(take_profit, 2),
                                metadata={
                                    "rsi_current": round(current_rsi, 1),
                                    "rsi_at_divergence": round(curr_rsi_at_swing, 1),
                                    "rsi_previous_low": round(prev_rsi, 1),
                                    "divergence_points": round(divergence_strength, 1),
                                    "price_swing_low": round(curr_swing[1], 2),
                                },
                                reason=f"Bullish RSI divergence: price lower low but RSI higher low ({divergence_strength:.1f} pts). RSI at {curr_rsi_at_swing:.1f}",
                            )

        # --- Check for BEARISH divergence ---
        # Price makes higher high, RSI makes lower high (in overbought zone)
        if current_rsi > self.overbought - 15:
            price_swings = find_swing_highs(highs, self.swing_lookback)
            if len(price_swings) >= 2:
                prev_swing = price_swings[-2]
                curr_swing = price_swings[-1]

                price_higher_high = curr_swing[1] > prev_swing[1]

                if price_higher_high:
                    prev_rsi_idx = prev_swing[0] - rsi_offset
                    curr_rsi_idx = curr_swing[0] - rsi_offset

                    if 0 <= prev_rsi_idx < len(rsi_values) and 0 <= curr_rsi_idx < len(rsi_values):
                        prev_rsi = rsi_values[prev_rsi_idx]
                        curr_rsi_at_swing = rsi_values[curr_rsi_idx]

                        rsi_lower_high = curr_rsi_at_swing < prev_rsi - self.min_divergence_rsi

                        if rsi_lower_high and curr_rsi_at_swing > self.overbought - 10:
                            stop_loss = curr_swing[1] + (curr_swing[1] - current_price) * 0.3
                            risk = stop_loss - current_price
                            take_profit = current_price - risk * 2.0

                            divergence_strength = prev_rsi - curr_rsi_at_swing
                            score = min(90, 50 + divergence_strength * 3)

                            return Signal(
                                strategy_name=self.name,
                                direction=Direction.SHORT,
                                strength=SignalStrength.STRONG if divergence_strength > 10 else SignalStrength.MODERATE,
                                score=score,
                                entry_price=current_price,
                                stop_loss=round(stop_loss, 2),
                                take_profit=round(take_profit, 2),
                                metadata={
                                    "rsi_current": round(current_rsi, 1),
                                    "rsi_at_divergence": round(curr_rsi_at_swing, 1),
                                    "rsi_previous_high": round(prev_rsi, 1),
                                    "divergence_points": round(divergence_strength, 1),
                                    "price_swing_high": round(curr_swing[1], 2),
                                },
                                reason=f"Bearish RSI divergence: price higher high but RSI lower high ({divergence_strength:.1f} pts). RSI at {curr_rsi_at_swing:.1f}",
                            )

        return self._no_signal(f"No divergence detected. RSI: {current_rsi:.1f}")
