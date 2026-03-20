"""
Strategy #10: Bollinger Bands Mean Reversion Scalping.

HOW IT WORKS:
- Bollinger Bands = a channel around price based on standard deviation
- Middle band = 20-period Simple Moving Average (SMA)
- Upper band = SMA + (2 x standard deviation)
- Lower band = SMA - (2 x standard deviation)
- Statistically, ~95% of price action stays within the bands
- When price touches/breaks a band and comes back inside, it tends to
  revert toward the middle band (mean reversion)

ENTRY RULES:
- BUY: Price closes below lower band, then next candle closes INSIDE bands
- SELL: Price closes above upper band, then next candle closes INSIDE bands
- The "close inside" confirmation prevents entering during strong breakouts

WHY IT WORKS:
- Price tends to oscillate around the mean (SMA)
- When it stretches too far (beyond bands), it snaps back like a rubber band
- Works beautifully in ranging markets (65-75% win rate)
- FAILS in strong trends (overbought can stay overbought)

BEST FOR: Ranging markets, Asian session, consolidation periods
AVOID: Strong trends, news events, breakout sessions
"""

from ..data.models import Candle, Signal, Direction, SignalStrength
from .base import BaseStrategy


def compute_sma(prices: list[float], period: int) -> list[float]:
    """Simple Moving Average — just the average of the last N prices."""
    if len(prices) < period:
        return []
    return [
        sum(prices[i - period:i]) / period
        for i in range(period, len(prices) + 1)
    ]


def compute_bollinger_bands(
    prices: list[float], period: int = 20, std_dev: float = 2.0
) -> tuple[list[float], list[float], list[float]]:
    """
    Compute Bollinger Bands.

    Returns: (upper_band, middle_band, lower_band)

    The standard deviation measures how "spread out" prices are.
    High std dev = volatile market = wide bands.
    Low std dev = quiet market = narrow bands (squeeze — breakout coming!).
    """
    if len(prices) < period:
        return [], [], []

    middle = []
    upper = []
    lower = []

    for i in range(period, len(prices) + 1):
        window = prices[i - period:i]
        sma = sum(window) / period

        # Standard deviation: how far prices deviate from the average
        variance = sum((p - sma) ** 2 for p in window) / period
        std = variance ** 0.5

        middle.append(sma)
        upper.append(sma + std_dev * std)
        lower.append(sma - std_dev * std)

    return upper, middle, lower


class BollingerBandsStrategy(BaseStrategy):
    """
    Bollinger Bands mean reversion with confirmation candle.

    Waits for price to break a band, then re-enter — this avoids
    entering during strong breakouts that would keep going.
    """

    def __init__(
        self,
        period: int = 20,          # SMA period (9 for fast scalping, 20 standard)
        std_dev: float = 2.0,      # Standard deviation multiplier
        use_rsi_filter: bool = True,  # Require RSI confirmation
        rsi_period: int = 14,
    ):
        self.period = period
        self.std_dev = std_dev
        self.use_rsi_filter = use_rsi_filter
        self.rsi_period = rsi_period

    @property
    def name(self) -> str:
        return "bollinger_bands"

    @property
    def category(self) -> str:
        return "scalping"

    def analyze(self, candles: list[Candle], symbol: str = "") -> Signal:
        if len(candles) < self.period + 5:
            return self._no_signal("Not enough candles for Bollinger Bands")

        closes = [c.close for c in candles]

        # Compute Bollinger Bands
        upper, middle, lower = compute_bollinger_bands(
            closes, self.period, self.std_dev
        )

        if len(upper) < 3:
            return self._no_signal("BB calculation produced too few values")

        # Current and previous values
        current_price = closes[-1]
        prev_close = closes[-2]
        two_ago_close = closes[-3]

        # BB values (aligned to end of price array)
        bb_offset = len(closes) - len(upper)
        upper_now = upper[-1]
        middle_now = middle[-1]
        lower_now = lower[-1]
        upper_prev = upper[-2]
        lower_prev = lower[-2]

        # Band width as percentage of price — narrow bands = squeeze (low volatility)
        band_width = (upper_now - lower_now) / middle_now
        is_squeeze = band_width < 0.02  # Less than 2% bandwidth

        # --- BULLISH SETUP ---
        # Previous candle closed BELOW lower band, current candle closed INSIDE
        prev_below_lower = prev_close < lower_prev
        current_inside = current_price > lower_now

        if prev_below_lower and current_inside:
            # Optional RSI filter: RSI should be oversold (<30)
            if self.use_rsi_filter:
                from .rsi_divergence import compute_rsi
                rsi_values = compute_rsi(closes, self.rsi_period)
                if rsi_values and rsi_values[-1] > 40:
                    return self._no_signal(f"BB bullish setup but RSI too high ({rsi_values[-1]:.1f})")
                rsi_val = rsi_values[-1] if rsi_values else None
            else:
                rsi_val = None

            # Entry at current price, target middle band, stop below lower band
            stop_loss = lower_now - (middle_now - lower_now) * 0.1
            take_profit = middle_now  # Mean reversion target

            risk = current_price - stop_loss
            reward = take_profit - current_price
            rr = reward / risk if risk > 0 else 0

            # Score based on distance from band and band width
            distance_from_band = (lower_now - prev_close) / current_price * 100
            score = min(80, 45 + distance_from_band * 10)

            return Signal(
                strategy_name=self.name,
                direction=Direction.LONG,
                strength=SignalStrength.STRONG if distance_from_band > 0.3 else SignalStrength.MODERATE,
                score=score,
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "upper_band": round(upper_now, 2),
                    "middle_band": round(middle_now, 2),
                    "lower_band": round(lower_now, 2),
                    "band_width_pct": round(band_width * 100, 2),
                    "is_squeeze": is_squeeze,
                    "rsi": round(rsi_val, 1) if rsi_val else None,
                    "risk_reward": round(rr, 2),
                },
                reason=f"Price bounced off lower BB. Target: middle band ({middle_now:.2f}). Band width: {band_width*100:.1f}%",
            )

        # --- BEARISH SETUP ---
        prev_above_upper = prev_close > upper_prev
        current_inside_from_above = current_price < upper_now

        if prev_above_upper and current_inside_from_above:
            if self.use_rsi_filter:
                from .rsi_divergence import compute_rsi
                rsi_values = compute_rsi(closes, self.rsi_period)
                if rsi_values and rsi_values[-1] < 60:
                    return self._no_signal(f"BB bearish setup but RSI too low ({rsi_values[-1]:.1f})")
                rsi_val = rsi_values[-1] if rsi_values else None
            else:
                rsi_val = None

            stop_loss = upper_now + (upper_now - middle_now) * 0.1
            take_profit = middle_now

            risk = stop_loss - current_price
            reward = current_price - take_profit
            rr = reward / risk if risk > 0 else 0

            distance_from_band = (prev_close - upper_now) / current_price * 100
            score = min(80, 45 + distance_from_band * 10)

            return Signal(
                strategy_name=self.name,
                direction=Direction.SHORT,
                strength=SignalStrength.STRONG if distance_from_band > 0.3 else SignalStrength.MODERATE,
                score=score,
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
                metadata={
                    "upper_band": round(upper_now, 2),
                    "middle_band": round(middle_now, 2),
                    "lower_band": round(lower_now, 2),
                    "band_width_pct": round(band_width * 100, 2),
                    "is_squeeze": is_squeeze,
                    "rsi": round(rsi_val, 1) if rsi_val else None,
                    "risk_reward": round(rr, 2),
                },
                reason=f"Price rejected from upper BB. Target: middle band ({middle_now:.2f}). Band width: {band_width*100:.1f}%",
            )

        return self._no_signal(
            f"No BB setup. Price: {current_price:.2f}, Upper: {upper_now:.2f}, Lower: {lower_now:.2f}"
        )
