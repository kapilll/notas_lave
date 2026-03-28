"""Tests for shared indicator functions (compute_ema, compute_rsi, compute_stochastic, compute_vwap)."""

import pytest
from datetime import datetime, timezone
from notas_lave.data.models import Candle
from notas_lave.strategies.indicators import (
    compute_ema, compute_rsi, compute_stochastic, compute_vwap,
)


def _candle(price: float, vol: float = 500.0) -> Candle:
    return Candle(
        timestamp=datetime(2026, 3, 15, 10, tzinfo=timezone.utc),
        open=price, high=price + 2, low=price - 2, close=price, volume=vol,
    )


def _candles(prices: list[float], vol: float = 500.0) -> list[Candle]:
    return [_candle(p, vol) for p in prices]


# ─── EMA ────────────────────────────────────────────────────────────────────

class TestComputeEMA:
    def test_insufficient_prices_returns_empty(self):
        assert compute_ema([100.0, 101.0], period=5) == []

    def test_exact_period_returns_one_value(self):
        prices = [100.0] * 5
        result = compute_ema(prices, period=5)
        assert len(result) == 1
        assert result[0] == 100.0

    def test_ema_follows_trend_up(self):
        prices = [float(i) for i in range(1, 30)]
        ema = compute_ema(prices, period=5)
        assert len(ema) > 0
        assert ema[-1] > ema[0]

    def test_ema_follows_trend_down(self):
        prices = [float(30 - i) for i in range(30)]
        ema = compute_ema(prices, period=5)
        assert ema[-1] < ema[0]

    def test_flat_prices_ema_is_flat(self):
        prices = [100.0] * 20
        ema = compute_ema(prices, period=5)
        assert all(abs(v - 100.0) < 0.001 for v in ema)

    def test_output_length(self):
        prices = [float(i + 1) for i in range(20)]  # 20 prices, start at 1
        ema = compute_ema(prices, period=5)
        # First EMA = SMA of first 5, then one per remaining price
        assert len(ema) == 16  # 20 - 5 + 1


# ─── RSI ────────────────────────────────────────────────────────────────────

class TestComputeRSI:
    def test_insufficient_prices_returns_empty(self):
        assert compute_rsi([100.0, 101.0], period=14) == []

    def test_all_gains_returns_100(self):
        prices = list(range(1, 30))  # Always increasing
        rsi = compute_rsi(prices, period=14)
        assert len(rsi) > 0
        assert rsi[-1] == 100.0

    def test_all_losses_returns_zero(self):
        prices = [float(30 - i) for i in range(30)]  # Always decreasing
        rsi = compute_rsi(prices, period=14)
        assert len(rsi) > 0
        # All losses → avg_loss > 0, avg_gain = 0 → RSI = 0
        assert rsi[-1] == pytest.approx(0.0, abs=1.0)

    def test_rsi_in_range(self):
        import random
        random.seed(42)
        prices = [2000.0 + random.uniform(-10, 10) for _ in range(50)]
        rsi = compute_rsi(prices, period=14)
        assert all(0.0 <= v <= 100.0 for v in rsi)

    def test_wilder_smoothing_produces_values(self):
        prices = [100.0 + (i % 5) for i in range(30)]
        rsi = compute_rsi(prices, period=7)
        assert len(rsi) > 0


# ─── Stochastic ──────────────────────────────────────────────────────────────

class TestComputeStochastic:
    def test_insufficient_candles_returns_empty(self):
        candles = _candles([100.0] * 3)
        k, d = compute_stochastic(candles, k_period=14, d_period=3)
        assert k == []
        assert d == []

    def test_returns_two_series(self):
        candles = _candles([100.0 + float(i) for i in range(30)])  # start at 100, not 0
        k, d = compute_stochastic(candles, k_period=14, d_period=3, smooth=3)
        assert len(k) > 0
        assert len(d) > 0

    def test_values_in_range(self):
        candles = _candles([100.0 + (i % 10) for i in range(50)])
        k, d = compute_stochastic(candles)
        assert all(0.0 <= v <= 100.0 for v in k)
        assert all(0.0 <= v <= 100.0 for v in d)

    def test_flat_prices_returns_50(self):
        """All prices equal → stochastic indeterminate → clamped to 50."""
        candles = _candles([100.0] * 30)
        k, d = compute_stochastic(candles, k_period=14)
        assert all(v == 50.0 for v in k)

    def test_uptrend_high_stochastic(self):
        """Strong uptrend → stochastic near 100 (price always at top of range)."""
        prices = [100.0 + i * 2.0 for i in range(30)]  # 100, 102, 104, ...
        candles = _candles(prices)
        k, d = compute_stochastic(candles, k_period=10, d_period=3)
        # Close is at top of range in uptrend → stochastic should be high (>50)
        assert k[-1] > 50.0


# ─── VWAP ────────────────────────────────────────────────────────────────────

class TestComputeVWAP:
    def test_empty_returns_empty(self):
        assert compute_vwap([]) == []

    def test_single_candle(self):
        candles = [_candle(100.0, vol=1000.0)]
        vwap = compute_vwap(candles)
        assert len(vwap) == 1
        # VWAP = (high + low + close) / 3 = (102 + 98 + 100) / 3 = 100
        assert vwap[0] == pytest.approx(100.0)

    def test_vwap_length_matches_candles(self):
        candles = _candles([100.0 + float(i) for i in range(20)])
        vwap = compute_vwap(candles)
        assert len(vwap) == 20

    def test_vwap_weighted_by_volume(self):
        """High-volume candle at higher price shifts VWAP up."""
        low_vol = _candle(100.0, vol=10.0)
        high_vol = _candle(200.0, vol=1000.0)
        vwap = compute_vwap([low_vol, high_vol])
        # VWAP should be much closer to 200 than 150
        assert vwap[-1] > 150.0

    def test_zero_volume_candle_uses_price(self):
        """Zero-volume candle doesn't divide by zero."""
        candles = [_candle(100.0, vol=0.0)]
        vwap = compute_vwap(candles)
        assert len(vwap) == 1
        assert vwap[0] == pytest.approx(100.0)
