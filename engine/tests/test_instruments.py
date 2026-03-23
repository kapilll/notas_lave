"""Tests for instrument specs and position sizing — the most critical module."""

import pytest
from notas_lave.data.instruments import get_instrument, InstrumentSpec


class TestPositionSizing:
    """Position sizing errors can cause 10-100x the intended risk."""

    def test_gold_basic_sizing(self):
        """Gold: $100K account, 1% risk, $10 SL = 1.0 lot."""
        spec = get_instrument("XAUUSD")
        lots = spec.calculate_position_size(
            entry=2000.0, stop_loss=1990.0, account_balance=100_000, risk_pct=0.01
        )
        # $1000 risk / ($10 * 100oz) = 1.0 lot
        assert lots == 1.0

    def test_gold_small_sl(self):
        """Gold: tight $2 SL = larger position (5 lots)."""
        spec = get_instrument("XAUUSD")
        lots = spec.calculate_position_size(
            entry=2000.0, stop_loss=1998.0, account_balance=100_000, risk_pct=0.01
        )
        # $1000 / ($2 * 100) = 5.0 lots
        assert lots == 5.0

    def test_btc_sizing(self):
        """BTC: $100K, 1% risk, $500 SL."""
        spec = get_instrument("BTCUSD")
        lots = spec.calculate_position_size(
            entry=85000, stop_loss=84500, account_balance=100_000, risk_pct=0.01
        )
        # $1000 / ($500 * 1) = 2.0 BTC
        assert lots == 2.0

    def test_leveraged_sizing_risk_limited(self):
        """With leverage, risk budget is the binding constraint."""
        spec = get_instrument("BTCUSDT")
        lots = spec.calculate_position_size(
            entry=85000, stop_loss=84700, account_balance=12.0,
            risk_pct=0.02, leverage=15.0,
        )
        # Risk = $0.24, loss per lot = $300, lots = 0.0008
        assert lots == 0.0008
        # Verify margin fits: notional = 0.0008 * 85000 = $68, margin = $68/15 = $4.53
        margin = lots * 85000 / 15
        assert margin < 12.0  # Must fit in balance

    def test_leveraged_sizing_margin_limited(self):
        """With large SL, margin becomes the binding constraint."""
        spec = get_instrument("BTCUSDT")
        lots = spec.calculate_position_size(
            entry=85000, stop_loss=80000, account_balance=12.0,
            risk_pct=0.50,  # Very high risk % to force margin limit
            leverage=15.0,
        )
        # Risk budget says 6.0 / 5000 = 0.0012 BTC
        # But margin limit: 12 * 0.80 / (85000/15) = 0.0016 BTC
        # Should take minimum
        margin = lots * 85000 / 15
        assert margin <= 12.0  # Must not exceed balance

    def test_zero_sl_returns_zero(self):
        """SL at entry = 0 risk = no position."""
        spec = get_instrument("XAUUSD")
        lots = spec.calculate_position_size(
            entry=2000.0, stop_loss=2000.0, account_balance=100_000
        )
        assert lots == 0.0

    def test_min_lot_rejected_when_over_risk(self):
        """QR-07: If min_lot exceeds risk budget, reject the trade (return 0.0).

        $10 account, 1% risk = $0.10 risk budget.
        Gold $10 SL: loss per lot = $10 * 100oz = $1000.
        Needed lots = $0.10 / $1000 = 0.0001.
        Clamped to min_lot 0.01 → actual risk = 0.01 * $10 * 100 = $10 (100% of account!).
        Must return 0.0 to protect the account.
        """
        spec = get_instrument("XAUUSD")
        lots = spec.calculate_position_size(
            entry=2000.0, stop_loss=1990.0, account_balance=10.0, risk_pct=0.01
        )
        assert lots == 0.0  # Trade rejected — min_lot would exceed risk budget

    def test_min_lot_oversized_gold_small_account(self):
        """QR-07: Classic dangerous scenario — $100 account, 0.3% risk, Gold $5 SL.

        Risk budget = $100 * 0.003 = $0.30.
        Needed lots = $0.30 / ($5 * 100) = 0.0006.
        Clamped to 0.01 → actual risk = 0.01 * $5 * 100 = $5.00 (5% of account!).
        Must return 0.0.
        """
        spec = get_instrument("XAUUSD")
        lots = spec.calculate_position_size(
            entry=2000.0, stop_loss=1995.0, account_balance=100.0, risk_pct=0.003
        )
        assert lots == 0.0  # Trade rejected — 0.3% risk would become 5%

    def test_min_lot_accepted_when_within_risk(self):
        """When account is large enough, min_lot is fine and returned normally."""
        spec = get_instrument("XAUUSD")
        lots = spec.calculate_position_size(
            entry=2000.0, stop_loss=1990.0, account_balance=100_000, risk_pct=0.01
        )
        # $1000 risk / $1000 per lot = 1.0 lot — well above min_lot, no issue
        assert lots == 1.0

    def test_min_notional_rejects_tiny_order(self):
        """AT-14: CoinDCX rejects orders below min notional (5 USDT).

        Tiny account + tight risk = position so small the notional value
        is below the exchange minimum. Must return 0.0 instead of letting
        the order fail at the exchange.
        """
        spec = get_instrument("BTCUSDT")
        lots = spec.calculate_position_size(
            entry=85000, stop_loss=84700, account_balance=1.0,
            risk_pct=0.01, leverage=15.0,
        )
        # Risk = $0.01, lots ≈ 0.0000333 → notional = ~$2.83 < $5 min
        assert lots == 0.0  # Rejected: below min notional

    def test_min_notional_accepts_valid_order(self):
        """AT-14: Orders above min notional pass through normally."""
        spec = get_instrument("BTCUSDT")
        lots = spec.calculate_position_size(
            entry=85000, stop_loss=84700, account_balance=12.0,
            risk_pct=0.02, leverage=15.0,
        )
        # Notional = 0.0008 * 85000 = $68 >> $5 min
        assert lots > 0.0

    def test_min_notional_zero_no_effect(self):
        """FundingPips instruments have min_notional=0 — no notional check."""
        spec = get_instrument("XAUUSD")
        assert spec.min_notional == 0.0
        # Even small valid trades pass (this already works via QR-07)
        lots = spec.calculate_position_size(
            entry=2000.0, stop_loss=1990.0, account_balance=100_000, risk_pct=0.01
        )
        assert lots == 1.0


class TestPnLCalculation:
    """P&L errors mean you don't know if you're winning or losing."""

    def test_gold_long_win(self):
        spec = get_instrument("XAUUSD")
        pnl = spec.calculate_pnl(entry=2000, exit=2010, lots=1.0, direction="LONG")
        assert pnl == 1000.0  # $10 * 100oz = $1000

    def test_gold_short_win(self):
        spec = get_instrument("XAUUSD")
        pnl = spec.calculate_pnl(entry=2010, exit=2000, lots=1.0, direction="SHORT")
        assert pnl == 1000.0

    def test_gold_long_loss(self):
        spec = get_instrument("XAUUSD")
        pnl = spec.calculate_pnl(entry=2000, exit=1990, lots=1.0, direction="LONG")
        assert pnl == -1000.0

    def test_btc_long_win(self):
        spec = get_instrument("BTCUSD")
        pnl = spec.calculate_pnl(entry=85000, exit=85500, lots=0.1, direction="LONG")
        assert pnl == 50.0  # $500 * 1 * 0.1 = $50


class TestLiquidationPrice:
    """Wrong liquidation price = unexpected account wipeout."""

    def test_btc_long_liquidation(self):
        spec = get_instrument("BTCUSDT")
        liq = spec.calculate_liquidation_price(
            entry=85000, lots=0.001, balance=12.0, leverage=15.0, direction="LONG"
        )
        assert liq < 85000  # Liq must be below entry for longs
        assert liq > 0

    def test_btc_short_liquidation(self):
        spec = get_instrument("BTCUSDT")
        liq = spec.calculate_liquidation_price(
            entry=85000, lots=0.001, balance=12.0, leverage=15.0, direction="SHORT"
        )
        assert liq > 85000  # Liq must be above entry for shorts


class TestFees:
    """Fee calculation errors erode profits silently."""

    def test_coindcx_taker_fee(self):
        spec = get_instrument("BTCUSDT")
        fee = spec.calculate_trading_fee(entry=85000, lots=0.001, is_maker=False)
        # 0.04% * $85000 * 0.001 = $0.034
        assert abs(fee - 0.034) < 0.001

    def test_fundingpips_no_fee(self):
        spec = get_instrument("XAUUSD")
        fee = spec.calculate_trading_fee(entry=2000, lots=1.0)
        assert fee == 0.0  # FundingPips fees are in spread, not explicit


class TestSpread:
    def test_long_spread_worse(self):
        spec = get_instrument("XAUUSD")
        fill = spec.apply_spread(2000.0, "LONG")
        assert fill > 2000.0  # Longs pay ASK (higher)

    def test_short_spread_worse(self):
        spec = get_instrument("XAUUSD")
        fill = spec.apply_spread(2000.0, "SHORT")
        assert fill < 2000.0  # Shorts get BID (lower)
