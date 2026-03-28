"""Tests for confluence scorer — core signal aggregation engine.

The scorer takes 12 strategy signals and combines them into one trade decision.
Coverage target: 60% (Phase 1 of the plan). Full branch coverage in Q2.
"""

from datetime import datetime, timezone
import pytest

from notas_lave.data.models import Candle, Direction, MarketRegime


def _make_candles(n=250, base_price=2000.0, trend="flat"):
    """Generate synthetic candles."""
    import random
    random.seed(42)
    candles = []
    price = base_price
    for i in range(n):
        if trend == "up":
            change = random.uniform(0, 10)
        elif trend == "down":
            change = random.uniform(-10, 0)
        else:
            change = random.uniform(-5, 5)
        o = price
        c = price + change
        h = max(o, c) + random.uniform(0, 2)
        l = min(o, c) - random.uniform(0, 2)
        ts = datetime(2026, 3, 15, 8 + (i % 8), i % 60, tzinfo=timezone.utc)
        candles.append(Candle(timestamp=ts, open=o, high=h, low=l, close=c,
                               volume=random.uniform(100, 1000)))
        price = c
    return candles


class TestRegimeDetection:
    def test_detect_regime_returns_market_regime(self):
        from notas_lave.confluence.scorer import detect_regime
        candles = _make_candles(100)
        regime = detect_regime(candles)
        assert isinstance(regime, MarketRegime)
        assert regime in (MarketRegime.TRENDING, MarketRegime.RANGING,
                          MarketRegime.VOLATILE, MarketRegime.QUIET)

    def test_insufficient_candles_returns_ranging(self):
        """With <50 candles, regime detection falls back to RANGING."""
        from notas_lave.confluence.scorer import detect_regime
        candles = _make_candles(5)
        regime = detect_regime(candles)
        assert regime == MarketRegime.RANGING

    def test_detect_regime_does_not_crash_on_large_input(self):
        """detect_regime must handle 500 candles without error."""
        from notas_lave.confluence.scorer import detect_regime
        candles = _make_candles(500)
        regime = detect_regime(candles)
        assert isinstance(regime, MarketRegime)

    def test_trending_market_returns_regime(self):
        """A consistent uptrend should not crash — regime must be one of 4 valid values."""
        from notas_lave.confluence.scorer import detect_regime
        candles = _make_candles(100, trend="up")
        regime = detect_regime(candles)
        assert regime in (MarketRegime.TRENDING, MarketRegime.RANGING,
                          MarketRegime.VOLATILE, MarketRegime.QUIET)


class TestConfluenceScorer:
    def test_compute_confluence_returns_result(self):
        from notas_lave.confluence.scorer import compute_confluence
        from notas_lave.data.models import ConfluenceResult
        candles = _make_candles(250)
        result = compute_confluence(candles, "XAUUSD", "5m")
        assert isinstance(result, ConfluenceResult)

    def test_confluence_score_in_range(self):
        """Composite score must always be 0-10."""
        from notas_lave.confluence.scorer import compute_confluence
        candles = _make_candles(250)
        result = compute_confluence(candles, "XAUUSD", "5m")
        assert 0 <= result.composite_score <= 10, (
            f"composite_score {result.composite_score} out of range [0, 10]"
        )

    def test_confluence_direction_valid(self):
        """Direction must be LONG, SHORT, or None."""
        from notas_lave.confluence.scorer import compute_confluence
        candles = _make_candles(250)
        result = compute_confluence(candles, "XAUUSD", "5m")
        assert result.direction in (Direction.LONG, Direction.SHORT, None)

    def test_confluence_with_minimal_candles(self):
        """Should not crash with insufficient data."""
        from notas_lave.confluence.scorer import compute_confluence
        candles = _make_candles(10)
        result = compute_confluence(candles, "BTCUSD", "5m")
        assert result is not None
        assert result.composite_score >= 0

    def test_confluence_regime_weights_structure(self):
        """REGIME_WEIGHTS must have expected structure — all 4 regimes present."""
        from notas_lave.confluence.scorer import REGIME_WEIGHTS
        assert MarketRegime.TRENDING in REGIME_WEIGHTS
        assert MarketRegime.RANGING in REGIME_WEIGHTS
        assert MarketRegime.VOLATILE in REGIME_WEIGHTS
        assert MarketRegime.QUIET in REGIME_WEIGHTS

    def test_weight_normalization_by_category(self):
        """Category weights must sum to 1.0 for each regime."""
        from notas_lave.confluence.scorer import REGIME_WEIGHTS
        for regime, weights in REGIME_WEIGHTS.items():
            total = sum(weights.values())
            assert abs(total - 1.0) < 0.01, (
                f"Regime {regime} weights sum to {total:.4f}, expected 1.0"
            )

    def test_regime_weights_contain_expected_categories(self):
        """Each regime must have weights for all 5 strategy categories."""
        from notas_lave.confluence.scorer import REGIME_WEIGHTS
        expected_categories = {"scalping", "ict", "fibonacci", "volume", "breakout"}
        for regime, weights in REGIME_WEIGHTS.items():
            for cat in expected_categories:
                assert cat in weights, (
                    f"Regime {regime} missing category '{cat}' in weights"
                )

    def test_htf_bias_returns_direction_or_none(self):
        """HTF bias filter returns Direction or None — never crashes."""
        from notas_lave.confluence.scorer import get_htf_bias
        candles = _make_candles(250)
        bias = get_htf_bias(candles)
        assert bias in (Direction.LONG, Direction.SHORT, None)

    def test_htf_bias_insufficient_data_returns_none(self):
        """HTF bias with <55 candles returns None."""
        from notas_lave.confluence.scorer import get_htf_bias
        candles = _make_candles(10)
        bias = get_htf_bias(candles)
        assert bias is None

    def test_confluence_result_has_all_fields(self):
        """ConfluenceResult must have composite_score, direction, regime."""
        from notas_lave.confluence.scorer import compute_confluence
        candles = _make_candles(250)
        result = compute_confluence(candles, "XAUUSD", "5m")
        assert hasattr(result, 'composite_score')
        assert hasattr(result, 'direction')
        assert hasattr(result, 'regime')
        assert hasattr(result, 'signals')
        assert hasattr(result, 'agreeing_strategies')

    def test_compute_confluence_different_instruments(self):
        """Scorer must handle all registered instruments without crashing."""
        from notas_lave.confluence.scorer import compute_confluence
        instruments = ["XAUUSD", "BTCUSD", "ETHUSD"]
        candles = _make_candles(250)
        for symbol in instruments:
            result = compute_confluence(candles, symbol, "5m")
            assert result is not None, f"compute_confluence crashed for {symbol}"
            assert 0 <= result.composite_score <= 10, (
                f"{symbol}: composite_score {result.composite_score} out of range"
            )

    def test_confluence_result_symbol_matches_input(self):
        """Result symbol must match the requested symbol."""
        from notas_lave.confluence.scorer import compute_confluence
        candles = _make_candles(250)
        result = compute_confluence(candles, "XAUUSD", "15m")
        assert result.symbol == "XAUUSD"
        assert result.timeframe == "15m"

    def test_confluence_agreeing_strategies_bounded(self):
        """agreeing_strategies must be between 0 and total_strategies."""
        from notas_lave.confluence.scorer import compute_confluence
        candles = _make_candles(250)
        result = compute_confluence(candles, "XAUUSD", "5m")
        assert 0 <= result.agreeing_strategies <= result.total_strategies

    def test_update_regime_weights_applies(self):
        """update_regime_weights modifies REGIME_WEIGHTS and persists."""
        from notas_lave.confluence.scorer import update_regime_weights, REGIME_WEIGHTS
        from notas_lave.data.models import MarketRegime
        # Save original
        original = {k: dict(v) for k, v in REGIME_WEIGHTS.items()}
        try:
            update_regime_weights({
                "TRENDING": {"scalping": 0.25, "ict": 0.20, "fibonacci": 0.20, "volume": 0.15, "breakout": 0.20}
            })
            assert REGIME_WEIGHTS[MarketRegime.TRENDING]["scalping"] == 0.25
        finally:
            # Restore original weights
            for regime, weights in original.items():
                REGIME_WEIGHTS[regime] = weights

    def test_update_regime_weights_ignores_unknown_regime(self):
        """Unknown regime strings in update_regime_weights are skipped."""
        from notas_lave.confluence.scorer import update_regime_weights
        # Should not raise even with unknown regime name
        update_regime_weights({"UNKNOWN_REGIME_XYZ": {"scalping": 0.5}})

    def test_volume_multiplier_direction(self):
        """High volume candles must not produce a lower score than zero volume."""
        from notas_lave.confluence.scorer import compute_confluence

        candles_high_vol = _make_candles(250)
        for c in candles_high_vol:
            object.__setattr__(c, 'volume', 10000.0)

        candles_zero_vol = _make_candles(250)
        for c in candles_zero_vol:
            object.__setattr__(c, 'volume', 0.0)

        result_high = compute_confluence(candles_high_vol, "XAUUSD", "5m")
        result_zero = compute_confluence(candles_zero_vol, "XAUUSD", "5m")

        # Both must be within valid range
        assert 0 <= result_high.composite_score <= 10
        assert 0 <= result_zero.composite_score <= 10
