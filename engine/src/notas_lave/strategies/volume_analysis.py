"""Volume Analysis — delta, CVD, profile, and confirmation signals.

Volume tells us WHO is in control (buyers or sellers) and HOW MUCH
conviction is behind a move. This module provides volume analysis
that other strategies and the confluence scorer use to confirm or
reject signals.

KEY CONCEPTS:
- Volume Delta: buy_vol - sell_vol (approximated from OHLCV)
- CVD: cumulative delta — divergence from price reveals hidden pressure
- Volume Profile: POC (highest-volume price), Value Area (70% of volume)
- Volume Spike: 1.5x avg = confirmed move, 3x+ = potential exhaustion

USAGE:
  Used by confluence scorer as a signal quality multiplier:
  - High volume confirmation → boost signal score by 1.25-1.5x
  - Low volume → reduce signal score by 0.5-0.8x
  - CVD divergence from price → reversal signal
"""

from dataclasses import dataclass
from ..core.models import Candle, Direction


@dataclass(frozen=True)
class VolumeAnalysis:
    """Result of volume analysis on a candle series."""
    # Delta
    delta: float                # Current candle's buy-sell delta
    cvd: float                  # Cumulative volume delta
    cvd_trend: str              # "rising", "falling", "flat"

    # Spike classification
    volume_ratio: float         # current_vol / avg_vol
    spike_level: str            # "weak", "normal", "elevated", "strong", "climax", "extreme"

    # CVD divergence
    cvd_divergence: str | None  # "bullish", "bearish", or None

    # Volume Profile (session)
    poc: float                  # Point of Control price
    vah: float                  # Value Area High
    val: float                  # Value Area Low
    price_vs_va: str            # "above_va", "below_va", "inside_va"

    # Score: 0-100, how much volume confirms a directional move
    confirmation_score: float

    # Multiplier for confluence scoring (0.5 to 1.5)
    confluence_multiplier: float


# Spike classification thresholds
SPIKE_THRESHOLDS = {
    "extreme": 4.0,    # Potential reversal at extremes
    "climax": 3.0,     # Exhaustion signal
    "spike": 2.5,      # Institutional activity
    "strong": 2.0,     # High-probability breakout confirmation
    "elevated": 1.5,   # Minimum breakout confirmation
    "normal": 1.0,     # Average volume
}


def calculate_delta(candle: Candle) -> float:
    """Weighted volume delta from a single OHLCV candle.

    Approximation: weight volume by where close sits relative to
    the candle range. If close == high, all volume is "buying".
    If close == low, all volume is "selling".

    Formula: delta = volume * (close - open) / (high - low)
    """
    if candle.high == candle.low:
        return 0.0
    return candle.volume * (candle.close - candle.open) / (candle.high - candle.low)


def calculate_cvd(candles: list[Candle]) -> list[float]:
    """Cumulative Volume Delta — running sum of per-candle deltas."""
    cvd = []
    total = 0.0
    for c in candles:
        total += calculate_delta(c)
        cvd.append(total)
    return cvd


def classify_spike(volume_ratio: float) -> str:
    """Classify volume level relative to average."""
    for level, threshold in sorted(SPIKE_THRESHOLDS.items(), key=lambda x: -x[1]):
        if volume_ratio >= threshold:
            return level
    return "weak"


def detect_cvd_divergence(
    candles: list[Candle], cvd: list[float], lookback: int = 20,
) -> str | None:
    """Detect CVD vs price divergence over lookback period.

    Bullish divergence: price makes lower low but CVD makes higher low
    → sellers exhausting, hidden buying pressure
    Bearish divergence: price makes higher high but CVD makes lower high
    → buyers exhausting, hidden selling pressure
    """
    if len(candles) < lookback or len(cvd) < lookback:
        return None

    recent_prices = [c.close for c in candles[-lookback:]]
    recent_cvd = cvd[-lookback:]

    # Find swing lows/highs in the lookback window
    mid = lookback // 2

    # Check for lower low in price
    price_low_first = min(recent_prices[:mid])
    price_low_second = min(recent_prices[mid:])
    cvd_at_first_low = recent_cvd[recent_prices[:mid].index(price_low_first)]
    cvd_at_second_low = recent_cvd[mid + recent_prices[mid:].index(price_low_second)]

    # Bullish divergence: price lower low, CVD higher low
    if price_low_second < price_low_first and cvd_at_second_low > cvd_at_first_low:
        return "bullish"

    # Check for higher high in price
    price_high_first = max(recent_prices[:mid])
    price_high_second = max(recent_prices[mid:])
    cvd_at_first_high = recent_cvd[recent_prices[:mid].index(price_high_first)]
    cvd_at_second_high = recent_cvd[mid + recent_prices[mid:].index(price_high_second)]

    # Bearish divergence: price higher high, CVD lower high
    if price_high_second > price_high_first and cvd_at_second_high < cvd_at_first_high:
        return "bearish"

    return None


def calculate_volume_profile(
    candles: list[Candle], bins: int = 50,
) -> tuple[float, float, float]:
    """Calculate POC, VAH, VAL from candle data.

    POC = price level with highest volume (market's "fair value")
    VA = range containing 70% of volume (consensus zone)
    VAH/VAL = upper/lower bounds of value area

    Returns (poc, vah, val).
    """
    if not candles:
        return 0.0, 0.0, 0.0

    price_min = min(c.low for c in candles)
    price_max = max(c.high for c in candles)
    if price_max == price_min:
        return price_min, price_max, price_min

    bin_size = (price_max - price_min) / bins
    volume_at_price = [0.0] * bins

    for c in candles:
        typical_price = (c.high + c.low + c.close) / 3
        bin_idx = min(int((typical_price - price_min) / bin_size), bins - 1)
        volume_at_price[bin_idx] += c.volume

    # POC = bin with highest volume
    poc_idx = volume_at_price.index(max(volume_at_price))
    poc = price_min + (poc_idx + 0.5) * bin_size

    # Value Area: expand from POC until 70% of total volume
    total_vol = sum(volume_at_price)
    if total_vol == 0:
        return poc, price_max, price_min

    target_vol = total_vol * 0.70
    accumulated = volume_at_price[poc_idx]
    lower_idx = poc_idx
    upper_idx = poc_idx

    while accumulated < target_vol:
        vol_below = volume_at_price[lower_idx - 1] if lower_idx > 0 else 0
        vol_above = volume_at_price[upper_idx + 1] if upper_idx < bins - 1 else 0

        if vol_above >= vol_below and upper_idx < bins - 1:
            upper_idx += 1
            accumulated += vol_above
        elif lower_idx > 0:
            lower_idx -= 1
            accumulated += vol_below
        else:
            break

    vah = price_min + (upper_idx + 1) * bin_size
    val = price_min + lower_idx * bin_size

    return poc, vah, val


def analyze_volume(candles: list[Candle], lookback: int = 20) -> VolumeAnalysis:
    """Full volume analysis on a candle series.

    This is the main entry point. Returns a VolumeAnalysis with:
    - Delta and CVD
    - Spike classification
    - CVD divergence detection
    - Volume profile (POC, VA)
    - Confirmation score (0-100) and confluence multiplier (0.5-1.5)
    """
    if len(candles) < lookback + 2:
        return VolumeAnalysis(
            delta=0, cvd=0, cvd_trend="flat", volume_ratio=0,
            spike_level="weak", cvd_divergence=None, poc=0, vah=0, val=0,
            price_vs_va="inside_va", confirmation_score=0,
            confluence_multiplier=1.0,
        )

    # Delta and CVD
    cvd_values = calculate_cvd(candles)
    current_delta = calculate_delta(candles[-2])  # Last completed candle
    current_cvd = cvd_values[-1]

    # CVD trend (last 5 values)
    if len(cvd_values) >= 5:
        cvd_slope = cvd_values[-1] - cvd_values[-5]
        cvd_trend = "rising" if cvd_slope > 0 else "falling" if cvd_slope < 0 else "flat"
    else:
        cvd_trend = "flat"

    # Volume ratio (completed candle vs average)
    completed_vol = candles[-2].volume
    avg_vol = sum(c.volume for c in candles[-lookback - 2:-2] if c.volume > 0)
    vol_count = sum(1 for c in candles[-lookback - 2:-2] if c.volume > 0)
    avg_vol = avg_vol / vol_count if vol_count > 0 else 1.0
    volume_ratio = completed_vol / avg_vol if avg_vol > 0 else 0.0

    spike_level = classify_spike(volume_ratio)

    # CVD divergence
    cvd_divergence = detect_cvd_divergence(candles, cvd_values, lookback)

    # Volume profile (use last 96 candles for 24h on 15m chart)
    profile_candles = candles[-96:] if len(candles) >= 96 else candles
    poc, vah, val = calculate_volume_profile(profile_candles)

    # Price vs value area
    current_price = candles[-1].close
    if current_price > vah:
        price_vs_va = "above_va"
    elif current_price < val:
        price_vs_va = "below_va"
    else:
        price_vs_va = "inside_va"

    # Confirmation score (0-100)
    score = 0.0

    # Volume level (0-30 points)
    if volume_ratio >= 2.0:
        score += 30
    elif volume_ratio >= 1.5:
        score += 20
    elif volume_ratio >= 1.0:
        score += 10

    # CVD alignment with price direction (0-25 points)
    price_direction = candles[-1].close - candles[-5].close if len(candles) >= 5 else 0
    if (price_direction > 0 and cvd_trend == "rising") or \
       (price_direction < 0 and cvd_trend == "falling"):
        score += 25  # CVD confirms price direction
    elif cvd_divergence:
        score += 15  # Divergence is also informative (reversal signal)

    # Volume trend (0-25 points)
    if vol_count >= 5:
        recent_avg = sum(c.volume for c in candles[-7:-2]) / 5
        older_avg = avg_vol
        if recent_avg > older_avg * 1.2:
            score += 25  # Rising volume trend
        elif recent_avg > older_avg:
            score += 10

    # Exhaustion at extremes (0-20 points)
    if volume_ratio >= 3.0:
        recent_highs = [c.high for c in candles[-lookback:]]
        recent_lows = [c.low for c in candles[-lookback:]]
        at_high = current_price >= max(recent_highs) * 0.99
        at_low = current_price <= min(recent_lows) * 1.01
        if at_high or at_low:
            score += 20  # Exhaustion signal

    score = min(score, 100)

    # Confluence multiplier
    if score >= 80:
        multiplier = 1.5
    elif score >= 60:
        multiplier = 1.25
    elif score >= 40:
        multiplier = 1.0
    elif score >= 20:
        multiplier = 0.8
    else:
        multiplier = 0.6

    return VolumeAnalysis(
        delta=round(current_delta, 2),
        cvd=round(current_cvd, 2),
        cvd_trend=cvd_trend,
        volume_ratio=round(volume_ratio, 2),
        spike_level=spike_level,
        cvd_divergence=cvd_divergence,
        poc=round(poc, 4),
        vah=round(vah, 4),
        val=round(val, 4),
        price_vs_va=price_vs_va,
        confirmation_score=round(score, 1),
        confluence_multiplier=round(multiplier, 2),
    )
