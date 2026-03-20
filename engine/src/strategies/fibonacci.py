"""
Strategy #16: Fibonacci Golden Zone (50%-61.8%) Retracement.

HOW IT WORKS:
- After a strong impulse move (up or down), price often retraces
- Fibonacci ratios (derived from the Fibonacci sequence: 1,1,2,3,5,8,13...)
  predict WHERE price will retrace to before continuing
- Key levels: 23.6%, 38.2%, 50%, 61.8%, 78.6%
- The "Golden Zone" (50%-61.8%) is the highest probability reversal area
- 61.8% is the "Golden Ratio" — appears everywhere in nature and markets

ENTRY RULES:
- Find a clear swing (impulse move)
- Wait for price to retrace into the 50%-61.8% zone
- Enter when price shows a reversal candle (engulfing, hammer, etc.)
- Stop loss just beyond 78.6% level

WHY IT WORKS:
- Institutions place orders at Fibonacci levels
- The Golden Zone represents a "discount" in an uptrend
- Self-fulfilling prophecy: so many traders use it that it works

BEST FOR: All trending markets. Gold, crypto, forex during strong moves.
"""

from ..data.models import Candle, Signal, Direction, SignalStrength
from .base import BaseStrategy


def find_significant_swings(candles: list[Candle], min_move_pct: float = 0.005) -> list[tuple[int, float, str]]:
    """
    Find significant swing highs and lows.

    Returns list of (index, price, "high"|"low") tuples.
    A swing is "significant" if the move to it was at least min_move_pct.
    """
    if len(candles) < 10:
        return []

    swings = []
    lookback = 5

    for i in range(lookback, len(candles) - lookback):
        # Swing high: higher than neighbors
        is_high = all(candles[i].high >= candles[i - j].high for j in range(1, lookback + 1)) and \
                  all(candles[i].high >= candles[i + j].high for j in range(1, lookback + 1))
        if is_high:
            swings.append((i, candles[i].high, "high"))

        # Swing low: lower than neighbors
        is_low = all(candles[i].low <= candles[i - j].low for j in range(1, lookback + 1)) and \
                 all(candles[i].low <= candles[i + j].low for j in range(1, lookback + 1))
        if is_low:
            swings.append((i, candles[i].low, "low"))

    # Filter: only keep swings where the move was significant
    filtered = [swings[0]] if swings else []
    for i in range(1, len(swings)):
        move_pct = abs(swings[i][1] - swings[i - 1][1]) / swings[i - 1][1]
        if move_pct >= min_move_pct:
            filtered.append(swings[i])

    return filtered


class FibonacciGoldenZoneStrategy(BaseStrategy):
    """
    Fibonacci retracement to the Golden Zone (50%-61.8%).

    Detects impulse moves, draws Fibonacci levels, and looks for
    price to enter the Golden Zone with a reversal candle.
    """

    def __init__(
        self,
        golden_zone_low: float = 0.50,   # 50% retracement
        golden_zone_high: float = 0.618,  # 61.8% retracement
        invalidation_level: float = 0.786,  # Beyond this = setup invalid
        min_swing_pct: float = 0.008,  # Minimum 0.8% swing to draw fibs
    ):
        self.golden_zone_low = golden_zone_low
        self.golden_zone_high = golden_zone_high
        self.invalidation_level = invalidation_level
        self.min_swing_pct = min_swing_pct

    @property
    def name(self) -> str:
        return "fibonacci_golden_zone"

    @property
    def category(self) -> str:
        return "fibonacci"

    def analyze(self, candles: list[Candle], symbol: str = "") -> Signal:
        if len(candles) < 30:
            return self._no_signal("Not enough candles for Fibonacci")

        swings = find_significant_swings(candles, self.min_swing_pct)
        if len(swings) < 2:
            return self._no_signal("No significant swings found")

        current_price = candles[-1].close
        current_candle = candles[-1]
        prev_candle = candles[-2]

        # Get the last two swings to determine the impulse move
        last_swing = swings[-1]
        prev_swing = swings[-2]

        swing_range = abs(last_swing[1] - prev_swing[1])
        swing_pct = swing_range / min(last_swing[1], prev_swing[1])

        if swing_pct < self.min_swing_pct:
            return self._no_signal(f"Swing too small ({swing_pct*100:.2f}%)")

        # --- BULLISH SETUP: Swing Low → Swing High, price retracing down ---
        if prev_swing[2] == "low" and last_swing[2] == "high":
            swing_low = prev_swing[1]
            swing_high = last_swing[1]

            # Calculate Fibonacci levels (retracement FROM the high)
            fib_50 = swing_high - swing_range * self.golden_zone_low
            fib_618 = swing_high - swing_range * self.golden_zone_high
            fib_786 = swing_high - swing_range * self.invalidation_level

            # Is price in the Golden Zone?
            in_golden_zone = fib_618 <= current_price <= fib_50

            if in_golden_zone:
                # Look for bullish reversal candle
                is_bullish_reversal = (
                    current_candle.is_bullish and
                    (current_candle.lower_wick > current_candle.body_size * 0.5  # Hammer/pin bar
                     or (current_candle.close > prev_candle.high))  # Engulfing
                )

                if is_bullish_reversal:
                    stop_loss = fib_786 - swing_range * 0.02
                    take_profit_1 = swing_high  # 100% - back to swing high
                    take_profit_ext = swing_high + swing_range * 0.272  # 127.2% extension

                    risk = current_price - stop_loss
                    reward = take_profit_1 - current_price
                    rr = reward / risk if risk > 0 else 0

                    # Score based on how deep in golden zone + reversal quality
                    zone_depth = (fib_50 - current_price) / (fib_50 - fib_618)  # 0=top, 1=bottom
                    score = min(85, 50 + zone_depth * 20 + (10 if current_candle.lower_wick > current_candle.body_size else 0))

                    return Signal(
                        strategy_name=self.name,
                        direction=Direction.LONG,
                        strength=SignalStrength.STRONG if zone_depth > 0.5 else SignalStrength.MODERATE,
                        score=score,
                        entry_price=current_price,
                        stop_loss=round(stop_loss, 2),
                        take_profit=round(take_profit_1, 2),
                        metadata={
                            "swing_low": round(swing_low, 2),
                            "swing_high": round(swing_high, 2),
                            "fib_50": round(fib_50, 2),
                            "fib_618": round(fib_618, 2),
                            "fib_786": round(fib_786, 2),
                            "zone_depth": round(zone_depth, 2),
                            "risk_reward": round(rr, 2),
                            "extension_target": round(take_profit_ext, 2),
                        },
                        reason=f"Bullish Fibonacci Golden Zone ({zone_depth*100:.0f}% depth). Reversal candle at {current_price:.2f}, target {take_profit_1:.2f}",
                    )

        # --- BEARISH SETUP: Swing High → Swing Low, price retracing up ---
        if prev_swing[2] == "high" and last_swing[2] == "low":
            swing_high = prev_swing[1]
            swing_low = last_swing[1]

            fib_50 = swing_low + swing_range * self.golden_zone_low
            fib_618 = swing_low + swing_range * self.golden_zone_high
            fib_786 = swing_low + swing_range * self.invalidation_level

            in_golden_zone = fib_50 <= current_price <= fib_618

            if in_golden_zone:
                is_bearish_reversal = (
                    not current_candle.is_bullish and
                    (current_candle.upper_wick > current_candle.body_size * 0.5
                     or (current_candle.close < prev_candle.low))
                )

                if is_bearish_reversal:
                    stop_loss = fib_786 + swing_range * 0.02
                    take_profit_1 = swing_low

                    risk = stop_loss - current_price
                    reward = current_price - take_profit_1
                    rr = reward / risk if risk > 0 else 0

                    zone_depth = (current_price - fib_50) / (fib_618 - fib_50)
                    score = min(85, 50 + zone_depth * 20 + (10 if current_candle.upper_wick > current_candle.body_size else 0))

                    return Signal(
                        strategy_name=self.name,
                        direction=Direction.SHORT,
                        strength=SignalStrength.STRONG if zone_depth > 0.5 else SignalStrength.MODERATE,
                        score=score,
                        entry_price=current_price,
                        stop_loss=round(stop_loss, 2),
                        take_profit=round(take_profit_1, 2),
                        metadata={
                            "swing_low": round(swing_low, 2),
                            "swing_high": round(swing_high, 2),
                            "fib_50": round(fib_50, 2),
                            "fib_618": round(fib_618, 2),
                            "fib_786": round(fib_786, 2),
                            "zone_depth": round(zone_depth, 2),
                            "risk_reward": round(rr, 2),
                        },
                        reason=f"Bearish Fibonacci Golden Zone ({zone_depth*100:.0f}% depth). Reversal candle at {current_price:.2f}, target {take_profit_1:.2f}",
                    )

        return self._no_signal("No Fibonacci Golden Zone setup")
