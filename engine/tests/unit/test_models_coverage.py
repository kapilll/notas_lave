"""Tests to cover remaining lines in core/models.py and data/models.py — Candle validators."""

import pytest
from notas_lave.data.models import Candle, MarketRegime
from notas_lave.data.instruments import get_instrument, get_personal_instruments, get_prop_instruments
from datetime import datetime, timezone


class TestCandleValidators:
    """Covers the validator branches in Candle (nan/inf, non-positive, high<low, negative volume)."""

    def test_valid_candle_passes(self):
        c = Candle(
            timestamp=datetime(2026, 3, 15, 10, tzinfo=timezone.utc),
            open=2000.0, high=2010.0, low=1990.0, close=2005.0, volume=100.0,
        )
        assert c.close == 2005.0

    def test_nan_value_raises(self):
        with pytest.raises(ValueError, match="NaN"):
            Candle(
                timestamp=datetime(2026, 3, 15, 10, tzinfo=timezone.utc),
                open=float("nan"), high=2010.0, low=1990.0, close=2005.0, volume=100.0,
            )

    def test_inf_value_raises(self):
        with pytest.raises(ValueError, match="NaN"):
            Candle(
                timestamp=datetime(2026, 3, 15, 10, tzinfo=timezone.utc),
                open=float("inf"), high=2010.0, low=1990.0, close=2005.0, volume=100.0,
            )

    def test_non_positive_open_raises(self):
        with pytest.raises(ValueError, match="positive"):
            Candle(
                timestamp=datetime(2026, 3, 15, 10, tzinfo=timezone.utc),
                open=0.0, high=2010.0, low=1990.0, close=2005.0, volume=100.0,
            )

    def test_high_less_than_low_raises(self):
        with pytest.raises(ValueError, match="high"):
            Candle(
                timestamp=datetime(2026, 3, 15, 10, tzinfo=timezone.utc),
                open=2000.0, high=1980.0, low=1990.0, close=2005.0, volume=100.0,
            )

    def test_negative_volume_raises(self):
        with pytest.raises(ValueError, match="volume"):
            Candle(
                timestamp=datetime(2026, 3, 15, 10, tzinfo=timezone.utc),
                open=2000.0, high=2010.0, low=1990.0, close=2005.0, volume=-1.0,
            )

    def test_body_ratio_doji(self):
        """Candle where open == close → doji (body_ratio=0)."""
        c = Candle(
            timestamp=datetime(2026, 3, 15, 10, tzinfo=timezone.utc),
            open=2000.0, high=2010.0, low=1990.0, close=2000.0, volume=100.0,
        )
        assert c.body_ratio == 0.0

    def test_upper_wick_zero_for_bullish_close_at_high(self):
        """When close == high, no upper wick."""
        c = Candle(
            timestamp=datetime(2026, 3, 15, 10, tzinfo=timezone.utc),
            open=2000.0, high=2010.0, low=1990.0, close=2010.0, volume=100.0,
        )
        assert c.upper_wick == pytest.approx(0.0)

    def test_lower_wick_zero_for_bearish_close_at_low(self):
        """When close == low, no lower wick."""
        c = Candle(
            timestamp=datetime(2026, 3, 15, 10, tzinfo=timezone.utc),
            open=2005.0, high=2010.0, low=1990.0, close=1990.0, volume=100.0,
        )
        assert c.lower_wick == pytest.approx(0.0)


class TestInstrumentRegistry:
    def test_get_unknown_instrument_raises(self):
        with pytest.raises(KeyError):
            get_instrument("NONEXISTENT_TICKER")

    def test_get_personal_instruments_all_leveraged(self):
        personal = get_personal_instruments()
        assert len(personal) > 0
        assert all(spec.max_leverage > 1 for spec in personal)

    def test_get_prop_instruments_all_unleveraged(self):
        prop = get_prop_instruments()
        assert len(prop) > 0
        assert all(spec.max_leverage <= 1 for spec in prop)

    def test_personal_and_prop_cover_all_instruments(self):
        """All instruments are either personal or prop — no orphans."""
        from notas_lave.data.instruments import INSTRUMENTS
        personal = set(s.symbol for s in get_personal_instruments())
        prop = set(s.symbol for s in get_prop_instruments())
        all_symbols = set(INSTRUMENTS.keys())
        assert personal | prop == all_symbols
        assert personal & prop == set()  # No overlap

    def test_spread_overlap_session(self):
        """XAUUSD overlap session (12-16 UTC)."""
        spec = get_instrument("XAUUSD")
        spread = spec.get_spread(hour_utc=14, day_of_week=2)
        assert spread > 0

    def test_spread_newyork_session(self):
        """XAUUSD New York session (17-21 UTC)."""
        spec = get_instrument("XAUUSD")
        spread = spec.get_spread(hour_utc=18, day_of_week=1)
        assert spread > 0

    def test_spread_late_session(self):
        """XAUUSD late session (22-23 UTC) uses late multiplier."""
        spec = get_instrument("XAUUSD")
        spread = spec.get_spread(hour_utc=22, day_of_week=3)
        assert spread > spec.spread_typical  # Late = 1.5x

    def test_crypto_quiet_hours(self):
        """BTC outside active hours → quiet session."""
        spec = get_instrument("BTCUSD")
        quiet_spread = spec.get_spread(hour_utc=5, day_of_week=1)  # Mon 5am
        assert quiet_spread > 0

    def test_zero_price_pnl(self):
        """calculate_pnl handles zero lots gracefully."""
        spec = get_instrument("XAUUSD")
        pnl = spec.calculate_pnl(entry=2000.0, exit=2010.0, lots=0.0, direction="LONG")
        assert pnl == 0.0

    def test_unknown_spread_instrument_uses_crypto_default(self):
        """Instruments without explicit spread multipliers use _crypto_default."""
        # SOLUSD has no explicit multiplier in SPREAD_MULTIPLIERS
        spec = get_instrument("SOLUSD")
        spread = spec.get_spread(hour_utc=14, day_of_week=2)
        assert spread > 0
