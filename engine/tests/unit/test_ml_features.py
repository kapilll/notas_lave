"""Tests for ML feature extraction."""

import pytest
from datetime import datetime, timezone
from notas_lave.data.models import Candle, Signal, SignalStrength, Direction, MarketRegime
from notas_lave.ml.features import compute_atr, compute_rsi, extract_features, features_to_row


def _make_candles(n: int = 100, base: float = 2000.0) -> list[Candle]:
    import random
    random.seed(99)
    candles = []
    price = base
    for i in range(n):
        change = random.uniform(-5, 5)
        o, c = price, price + change
        h = max(o, c) + random.uniform(0, 2)
        l = min(o, c) - random.uniform(0, 2)
        ts = datetime(2026, 3, 15, 8 + (i % 8), i % 60, tzinfo=timezone.utc)
        candles.append(Candle(timestamp=ts, open=o, high=h, low=l, close=c,
                               volume=random.uniform(100, 1000)))
        price = c
    return candles


def _make_signal(
    strategy_name: str = "test_strategy",
    direction: Direction | None = Direction.LONG,
    score: float = 70.0,
    strength: SignalStrength = SignalStrength.STRONG,
    entry: float | None = 2000.0,
    sl: float | None = 1990.0,
    tp: float | None = 2020.0,
) -> Signal:
    return Signal(
        strategy_name=strategy_name,
        direction=direction,
        score=score,
        strength=strength,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
    )


class TestComputeATR:
    def test_returns_positive_for_valid_candles(self):
        candles = _make_candles(50)
        atr = compute_atr(candles, period=14)
        assert atr > 0

    def test_insufficient_candles_returns_zero(self):
        candles = _make_candles(5)
        atr = compute_atr(candles, period=14)
        assert atr == 0.0

    def test_period_respected(self):
        candles = _make_candles(30)
        atr14 = compute_atr(candles, period=14)
        atr7 = compute_atr(candles, period=7)
        # Both should be positive for valid candles
        assert atr14 > 0
        assert atr7 > 0


class TestComputeRSI:
    def test_returns_value_in_range(self):
        import random
        random.seed(42)
        closes = [2000.0 + random.uniform(-10, 10) for _ in range(30)]
        rsi = compute_rsi(closes, period=14)
        assert 0 <= rsi <= 100

    def test_all_gains_returns_100(self):
        closes = [float(i) for i in range(1, 20)]  # Always increasing
        rsi = compute_rsi(closes, period=14)
        assert rsi == 100.0

    def test_insufficient_closes_returns_50(self):
        closes = [100.0, 101.0]
        rsi = compute_rsi(closes, period=14)
        assert rsi == 50.0


class TestExtractFeatures:
    def test_returns_empty_for_insufficient_candles(self):
        candles = _make_candles(10)
        signal = _make_signal()
        result = extract_features(candles, signal, MarketRegime.TRENDING, "XAUUSD", "5m")
        assert result == {}

    def test_returns_dict_with_enough_candles(self):
        candles = _make_candles(100)
        signal = _make_signal()
        result = extract_features(candles, signal, MarketRegime.TRENDING, "XAUUSD", "5m")
        assert isinstance(result, dict)
        assert len(result) > 10

    def test_contains_price_action_features(self):
        candles = _make_candles(100)
        signal = _make_signal()
        result = extract_features(candles, signal, MarketRegime.RANGING, "XAUUSD", "5m")
        assert "atr_14" in result
        assert "rsi_14" in result
        assert "body_ratio" in result
        assert "volume_ratio" in result

    def test_contains_signal_features(self):
        candles = _make_candles(100)
        signal = _make_signal(score=75.0, strength=SignalStrength.STRONG)
        result = extract_features(candles, signal, MarketRegime.TRENDING, "XAUUSD", "5m")
        assert result["signal_score"] == 75.0
        assert result["signal_strength"] == 3  # STRONG = 3

    def test_contains_context_features(self):
        candles = _make_candles(100)
        signal = _make_signal()
        result = extract_features(candles, signal, MarketRegime.VOLATILE, "BTCUSD", "15m")
        assert "hour_utc" in result
        assert "day_of_week" in result
        assert "regime" in result
        assert result["timeframe_minutes"] == 15

    def test_rr_ratio_computed_when_levels_present(self):
        candles = _make_candles(100)
        signal = _make_signal(entry=2000.0, sl=1990.0, tp=2020.0)
        result = extract_features(candles, signal, MarketRegime.TRENDING, "XAUUSD", "5m")
        assert result["rr_ratio"] == pytest.approx(2.0, abs=0.01)

    def test_rr_ratio_zero_when_no_levels(self):
        candles = _make_candles(100)
        signal = _make_signal(entry=None, sl=None, tp=None)
        result = extract_features(candles, signal, MarketRegime.RANGING, "XAUUSD", "5m")
        assert result["rr_ratio"] == 0

    def test_metadata_fields_present(self):
        candles = _make_candles(100)
        signal = _make_signal()
        result = extract_features(candles, signal, MarketRegime.QUIET, "BTCUSD", "1h")
        assert "_symbol" in result
        assert "_strategy" in result
        assert result["_symbol"] == "BTCUSD"
        assert result["_outcome"] is None

    def test_long_direction_is_positive(self):
        candles = _make_candles(100)
        signal = _make_signal(direction=Direction.LONG)
        result = extract_features(candles, signal, MarketRegime.TRENDING, "XAUUSD", "5m")
        assert result["signal_direction"] == 1

    def test_short_direction_is_negative(self):
        candles = _make_candles(100)
        signal = _make_signal(direction=Direction.SHORT)
        result = extract_features(candles, signal, MarketRegime.TRENDING, "XAUUSD", "5m")
        assert result["signal_direction"] == -1

    def test_all_regimes_handled(self):
        candles = _make_candles(100)
        signal = _make_signal()
        for regime in MarketRegime:
            result = extract_features(candles, signal, regime, "XAUUSD", "5m")
            assert "regime" in result


class TestFeaturesToRow:
    def test_strips_metadata_prefix(self):
        features = {
            "atr_14": 5.0,
            "rsi_14": 55.0,
            "_symbol": "BTCUSD",
            "_outcome": None,
            "_pnl": None,
        }
        row = features_to_row(features)
        assert "atr_14" in row
        assert "rsi_14" in row
        assert "_symbol" not in row
        assert "_outcome" not in row

    def test_strips_none_values(self):
        features = {"score": 70.0, "volume_ratio": None}
        row = features_to_row(features)
        assert "score" in row
        assert "volume_ratio" not in row

    def test_returns_only_ml_features(self):
        candles = _make_candles(100)
        signal = _make_signal()
        features = extract_features(candles, signal, MarketRegime.TRENDING, "XAUUSD", "5m")
        row = features_to_row(features)
        # No metadata keys
        assert all(not k.startswith("_") for k in row.keys())
        # All values are non-None
        assert all(v is not None for v in row.values())
