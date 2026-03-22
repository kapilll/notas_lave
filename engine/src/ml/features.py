"""
ML Feature Extraction — turns trading signals into structured data.

Every signal gets 20+ features extracted. These features are stored
alongside trade outcomes so ML models can learn what predicts wins.

Features are grouped into 4 categories:
1. Price Action (from candles): volatility, momentum, structure
2. Signal Quality (from strategy output): score, strength, agreement
3. Market Context (time, regime, spread): when and where
4. Historical Performance: how this strategy has done recently
"""

import logging
import math
from datetime import datetime, timezone
from ..data.models import Candle, Signal, MarketRegime

logger = logging.getLogger(__name__)


def compute_atr(candles: list[Candle], period: int = 14) -> float:
    """Calculate Average True Range."""
    if len(candles) < period + 1:
        return 0.0
    true_ranges = []
    for i in range(1, len(candles)):
        tr = max(
            candles[i].high - candles[i].low,
            abs(candles[i].high - candles[i-1].close),
            abs(candles[i].low - candles[i-1].close),
        )
        true_ranges.append(tr)
    return sum(true_ranges[-period:]) / period


def compute_rsi(closes: list[float], period: int = 14) -> float:
    """Calculate RSI for the most recent value."""
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i-1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def extract_features(
    candles: list[Candle],
    signal: Signal,
    regime: MarketRegime,
    symbol: str,
    timeframe: str,
) -> dict:
    """
    Extract ~25 features from a trading signal and its context.

    Returns a flat dict of feature_name -> value.
    All values are numeric (float/int) for ML compatibility.
    """
    if len(candles) < 50:
        return {}

    features = {}
    current = candles[-1]
    closes = [c.close for c in candles]

    # === PRICE ACTION FEATURES ===

    # Volatility
    atr_14 = compute_atr(candles, 14)
    atr_50 = compute_atr(candles, 50) if len(candles) >= 51 else atr_14
    features["atr_14"] = round(atr_14, 6)
    features["atr_ratio"] = round(atr_14 / atr_50, 4) if atr_50 > 0 else 1.0
    features["atr_pct"] = round(atr_14 / current.close * 100, 4) if current.close > 0 else 0

    # Momentum
    features["rsi_14"] = round(compute_rsi(closes, 14), 2)
    features["rsi_7"] = round(compute_rsi(closes, 7), 2)

    # Price vs moving averages
    ema_20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else current.close
    ema_50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else current.close
    features["price_vs_ema20"] = round((current.close - ema_20) / ema_20 * 100, 4) if ema_20 > 0 else 0
    features["price_vs_ema50"] = round((current.close - ema_50) / ema_50 * 100, 4) if ema_50 > 0 else 0

    # Candle structure
    features["body_ratio"] = round(current.body_ratio, 4)
    features["upper_wick_ratio"] = round(current.upper_wick / current.total_range, 4) if current.total_range > 0 else 0
    features["lower_wick_ratio"] = round(current.lower_wick / current.total_range, 4) if current.total_range > 0 else 0
    features["is_bullish"] = 1 if current.is_bullish else 0

    # Volume
    volumes = [c.volume for c in candles[-20:] if c.volume > 0]
    avg_vol = sum(volumes) / len(volumes) if volumes else 0
    features["volume_ratio"] = round(current.volume / avg_vol, 4) if avg_vol > 0 else 1.0

    # Recent price action (last 5 candles)
    recent = candles[-5:]
    features["recent_range_pct"] = round(
        (max(c.high for c in recent) - min(c.low for c in recent)) / current.close * 100, 4
    ) if current.close > 0 else 0
    features["recent_direction"] = 1 if closes[-1] > closes[-5] else -1 if len(closes) >= 5 else 0

    # === SIGNAL QUALITY FEATURES ===

    features["signal_score"] = round(signal.score, 2)
    features["signal_strength"] = {"STRONG": 3, "MODERATE": 2, "WEAK": 1, "NONE": 0}.get(
        signal.strength.value if signal.strength else "NONE", 0
    )
    features["signal_direction"] = 1 if signal.direction and signal.direction.value == "LONG" else -1

    # R:R ratio
    if signal.entry_price and signal.stop_loss and signal.take_profit:
        risk = abs(signal.entry_price - signal.stop_loss)
        reward = abs(signal.take_profit - signal.entry_price)
        features["rr_ratio"] = round(reward / risk, 4) if risk > 0 else 0
        features["risk_pct"] = round(risk / signal.entry_price * 100, 4) if signal.entry_price > 0 else 0
    else:
        features["rr_ratio"] = 0
        features["risk_pct"] = 0

    # === CONTEXT FEATURES ===

    features["hour_utc"] = current.timestamp.hour if current.timestamp else 0
    features["day_of_week"] = current.timestamp.weekday() if current.timestamp else 0
    features["regime"] = {"TRENDING": 0, "RANGING": 1, "VOLATILE": 2, "QUIET": 3}.get(
        regime.value if regime else "RANGING", 1
    )

    # Spread as percentage of risk
    try:
        from ..data.instruments import get_instrument
        spec = get_instrument(symbol)
        spread = spec.get_spread(
            features["hour_utc"],
            features["day_of_week"],
        )
        features["spread_pct"] = round(spread / current.close * 100, 6) if current.close > 0 else 0
        if signal.stop_loss and signal.entry_price:
            sl_dist = abs(signal.entry_price - signal.stop_loss)
            features["spread_vs_risk"] = round(spread / sl_dist, 4) if sl_dist > 0 else 0
        else:
            features["spread_vs_risk"] = 0
    except Exception:
        features["spread_pct"] = 0
        features["spread_vs_risk"] = 0

    # Timeframe as numeric
    tf_map = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
    features["timeframe_minutes"] = tf_map.get(timeframe, 5)

    # === METADATA (not for ML, for tracking) ===
    features["_symbol"] = symbol
    features["_timeframe"] = timeframe
    features["_strategy"] = signal.strategy_name
    features["_timestamp"] = current.timestamp.isoformat() if current.timestamp else ""

    # === TARGET (filled after trade closes) ===
    features["_outcome"] = None  # WIN / LOSS / BREAKEVEN
    features["_pnl"] = None
    features["_pnl_r_multiple"] = None  # P&L as multiple of risk

    return features


def features_to_row(features: dict) -> dict:
    """Convert features dict to a flat row suitable for DataFrame/CSV.
    Strips metadata prefixed with '_' for ML training."""
    return {k: v for k, v in features.items() if not k.startswith("_") and v is not None}
