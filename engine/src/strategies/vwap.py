"""
Strategy #11: VWAP Scalping.

HOW IT WORKS:
- VWAP = Volume-Weighted Average Price — the average price weighted by volume
- Institutions use VWAP as a benchmark: "did we buy above or below VWAP?"
- Price ABOVE VWAP = bullish bias (buyers in control)
- Price BELOW VWAP = bearish bias (sellers in control)

ENTRY RULES:
- LONG: Price is above VWAP, pulls back TO VWAP, bounces with volume
- SHORT: Price is below VWAP, rallies TO VWAP, rejects with volume
- Think of VWAP as a magnet — price gets pulled toward it, then bounces

WHY IT WORKS:
- VWAP represents the "fair value" based on actual trading volume
- Big institutions execute around VWAP — it creates real support/resistance
- Best during first 1-2 hours of a session (most reliable)

BEST FOR: Indices, liquid forex, Gold during London/NY sessions
"""

from ..data.models import Candle, Signal, Direction, SignalStrength
from .base import BaseStrategy


def compute_vwap(candles: list[Candle]) -> list[float]:
    """
    Calculate VWAP: cumulative(price * volume) / cumulative(volume).

    Typical price = (High + Low + Close) / 3
    Each candle contributes its typical price weighted by its volume.
    High-volume candles have MORE influence on VWAP than low-volume ones.
    """
    if not candles:
        return []

    vwap_values = []
    cum_vol = 0.0
    cum_tp_vol = 0.0

    for c in candles:
        typical_price = (c.high + c.low + c.close) / 3.0
        cum_vol += c.volume
        cum_tp_vol += typical_price * c.volume
        vwap_values.append(cum_tp_vol / cum_vol if cum_vol > 0 else typical_price)

    return vwap_values


class VWAPScalpingStrategy(BaseStrategy):
    """
    VWAP bounce/rejection scalping.

    Looks for price to pull back to VWAP and bounce in the trend direction.
    """

    def __init__(
        self,
        proximity_pct: float = 0.002,  # Price must be within 0.2% of VWAP
        volume_multiplier: float = 1.5,  # Bounce candle volume must be 1.5x avg
        lookback: int = 20,  # Candles to compute average volume
    ):
        self.proximity_pct = proximity_pct
        self.volume_multiplier = volume_multiplier
        self.lookback = lookback

    @property
    def name(self) -> str:
        return "vwap_scalping"

    @property
    def category(self) -> str:
        return "volume"

    def analyze(self, candles: list[Candle], symbol: str = "") -> Signal:
        if len(candles) < 50:
            return self._no_signal("Not enough candles for VWAP")

        vwap = compute_vwap(candles)
        current_price = candles[-1].close
        current_vwap = vwap[-1]
        prev_close = candles[-2].close
        prev_vwap = vwap[-2]

        # Check proximity: is price near VWAP?
        distance_pct = abs(current_price - current_vwap) / current_vwap

        # Average volume for comparison
        recent_vols = [c.volume for c in candles[-self.lookback:]]
        avg_vol = sum(recent_vols) / len(recent_vols) if recent_vols else 1
        current_vol = candles[-1].volume
        vol_ratio = current_vol / avg_vol if avg_vol > 0 else 0

        # Determine bias: which side of VWAP is price on?
        # Use the last 10 candles to determine dominant side
        above_count = sum(1 for c, v in zip(candles[-10:], vwap[-10:]) if c.close > v)
        bias_bullish = above_count >= 6  # 6+ of last 10 above VWAP = bullish
        bias_bearish = above_count <= 4  # 4 or fewer = bearish

        # --- BULLISH SETUP: Price above VWAP, pulls back to VWAP, bounces ---
        # Previous candle was near/touching VWAP, current candle bounced up
        prev_near_vwap = abs(prev_close - prev_vwap) / prev_vwap < self.proximity_pct
        bounced_up = current_price > prev_close and candles[-1].is_bullish

        if bias_bullish and prev_near_vwap and bounced_up and vol_ratio >= self.volume_multiplier:
            # ATR-based SL/TP — adapts to current volatility
            atr = self.compute_atr(candles)
            if not atr:
                return self._no_signal("Not enough data for ATR")
            stop_loss = self.atr_stop_loss(current_price, atr, "long", 1.5)
            take_profit = self.atr_take_profit(current_price, atr, "long", 2.0, abs(current_price - stop_loss))

            score = min(80, 45 + vol_ratio * 10 + (10 - above_count) * 2)

            return Signal(
                strategy_name=self.name,
                direction=Direction.LONG,
                strength=SignalStrength.STRONG if vol_ratio > 2.0 else SignalStrength.MODERATE,
                score=score,
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "vwap": round(current_vwap, 2),
                    "distance_pct": round(distance_pct * 100, 3),
                    "volume_ratio": round(vol_ratio, 2),
                    "atr": round(atr, 2),
                    "bias": "bullish",
                },
                reason=f"VWAP bounce: price pulled back to VWAP ({current_vwap:.2f}) and bounced with {vol_ratio:.1f}x volume",
            )

        # --- BEARISH SETUP: Price below VWAP, rallies to VWAP, rejects ---
        bounced_down = current_price < prev_close and not candles[-1].is_bullish

        if bias_bearish and prev_near_vwap and bounced_down and vol_ratio >= self.volume_multiplier:
            # ATR-based SL/TP — adapts to current volatility
            atr = self.compute_atr(candles)
            if not atr:
                return self._no_signal("Not enough data for ATR")
            stop_loss = self.atr_stop_loss(current_price, atr, "short", 1.5)
            take_profit = self.atr_take_profit(current_price, atr, "short", 2.0, abs(current_price - stop_loss))

            score = min(80, 45 + vol_ratio * 10 + above_count * 2)

            return Signal(
                strategy_name=self.name,
                direction=Direction.SHORT,
                strength=SignalStrength.STRONG if vol_ratio > 2.0 else SignalStrength.MODERATE,
                score=score,
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "vwap": round(current_vwap, 2),
                    "distance_pct": round(distance_pct * 100, 3),
                    "volume_ratio": round(vol_ratio, 2),
                    "atr": round(atr, 2),
                    "bias": "bearish",
                },
                reason=f"VWAP rejection: price rallied to VWAP ({current_vwap:.2f}) and rejected with {vol_ratio:.1f}x volume",
            )

        return self._no_signal(
            f"No VWAP setup. Price: {current_price:.2f}, VWAP: {current_vwap:.2f}, Distance: {distance_pct*100:.2f}%"
        )
