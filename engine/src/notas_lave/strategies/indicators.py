"""Shared indicator functions used by composite strategies.

These were originally inside individual strategy files. Moved here
when the 12 single-indicator strategies were replaced by 6 composites.
"""

from ..data.models import Candle


def compute_ema(prices: list[float], period: int) -> list[float]:
    """Exponential Moving Average."""
    if len(prices) < period:
        return []
    multiplier = 2 / (period + 1)
    ema_values = [sum(prices[:period]) / period]
    for price in prices[period:]:
        ema_values.append((price - ema_values[-1]) * multiplier + ema_values[-1])
    return ema_values


def compute_rsi(prices: list[float], period: int = 14) -> list[float]:
    """Relative Strength Index (Wilder smoothing)."""
    if len(prices) < period + 1:
        return []

    rsi_values = []
    gains = []
    losses = []

    for i in range(1, len(prices)):
        change = prices[i] - prices[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    if avg_loss == 0:
        rsi_values.append(100.0)
    else:
        rs = avg_gain / avg_loss
        rsi_values.append(100 - (100 / (1 + rs)))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100 - (100 / (1 + rs)))

    return rsi_values


def compute_stochastic(
    candles: list[Candle], k_period: int = 14, d_period: int = 3, smooth: int = 3,
) -> tuple[list[float], list[float]]:
    """Stochastic Oscillator (%K and %D)."""
    if len(candles) < k_period + smooth:
        return [], []

    raw_k = []
    for i in range(k_period - 1, len(candles)):
        window = candles[i - k_period + 1 : i + 1]
        highest = max(c.high for c in window)
        lowest = min(c.low for c in window)
        if highest == lowest:
            raw_k.append(50.0)
        else:
            raw_k.append((candles[i].close - lowest) / (highest - lowest) * 100)

    # Smooth %K
    if len(raw_k) < smooth:
        return raw_k, raw_k
    smoothed_k = []
    for i in range(smooth - 1, len(raw_k)):
        smoothed_k.append(sum(raw_k[i - smooth + 1 : i + 1]) / smooth)

    # %D = SMA of smoothed %K
    if len(smoothed_k) < d_period:
        return smoothed_k, smoothed_k
    d_values = []
    for i in range(d_period - 1, len(smoothed_k)):
        d_values.append(sum(smoothed_k[i - d_period + 1 : i + 1]) / d_period)

    return smoothed_k, d_values


def compute_vwap(candles: list[Candle]) -> list[float]:
    """Volume-Weighted Average Price."""
    if not candles:
        return []
    vwap_values = []
    cum_vol = 0.0
    cum_tp_vol = 0.0
    for c in candles:
        tp = (c.high + c.low + c.close) / 3
        cum_vol += c.volume
        cum_tp_vol += tp * c.volume
        vwap_values.append(cum_tp_vol / cum_vol if cum_vol > 0 else tp)
    return vwap_values
